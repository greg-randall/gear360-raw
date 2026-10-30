#!/usr/bin/env python3
"""Stitch Gear 360 (SM-R210) dual-fisheye images with the camera's own lens model + per-unit OPAX calibration.

Lens model (decoded from libdi-alg-imagestitch.so, see docs/lab-notebook.md "OPAX decoded"): OCamCalib variant where the
polynomials work in theta = elevation above the image plane (theta = -pi/2 on the optical axis, 0 at 90 deg
off-axis). Shared firmware constants, defined for a 2048-px lens texture:
    rho_2048(theta) = sum(INVPOL[i] * theta**i)
Per lens (OPAX, in 2896-px JPEG lens-square pixels): centre (xc, yc) and affine (c, d, e):
    col = xc + c*rho*cos(phi) + d*rho*sin(phi)
    row = yc + e*rho*cos(phi) +   rho*sin(phi)
with rho = rho_2048 * 2896/2048 and phi the image-plane angle (x right, y down).

Image layouts (lens-square pixel -> file pixel: (p + offset) * scale, plus the half's x origin):
    jpeg    : 5792x2896 camera JPEG, halves 2896 wide, offset (0, 0), scale 1
    rawhalf : 2912x1448 half-size raw TIFF (raw2dng/dcraw -h), halves 1456 wide, offset RAW_OFFSET, scale 0.5
    raw     : 5824x2896 full-size demosaiced raw, halves 2912 wide, offset RAW_OFFSET, scale 1
RAW_OFFSET was measured by registering raw vs JPEG (tools/raw_jpeg_geometry.py, calibration/raw_jpeg_geometry.txt).

Which JPEG half is OPAX "Left" is not verified; --swap exchanges the assignment.

Commands:
  solve  IMAGE  : match the overlap ring and solve the small lens-2 rotation correction (yaw/pitch/roll)
  stitch IMAGE OUT [--rot Y P R] : render an equirectangular panorama

stitch pipeline (what Samsung's stitcher does, as far as we can tell, minus its auto-calibration step):
  1. remap both lenses to equirectangular with the exact lens model; lens 2 rotated by 180 deg + --rot;
  2. coverage of each lens = inside its OPAX image-circle radius (minus --edge-margin px);
  3. seam gain: per-channel median ratio of the two lenses in the overlap band, split evenly between them;
  4. optional --flow: OpenCV DIS optical flow between the two lenses in a strip around the 90 deg seam
     (forward/backward checked, smoothed, clamped); inside +-band each lens is warped part of the way so a
     scene point lands at the same place from both sides, which hides near-field parallax;
  5. blend: multiband (Laplacian pyramid, hard seam at 90 deg) or a linear feather across +-band.
The pyramid blend is a small float32 implementation rather than cv2.detail.MultiBandBlender because that
one only takes 8-bit or int16 images, which would drop a bit from 16-bit raw renders.
"""
import argparse
import sys
import time

import cv2
import numpy as np

INVPOL = [971.9375896974, 526.1058092068, -499.094003808, -645.9034011167, -336.1369527907, -65.8206694527]
TEX = 2048.0
SQ = 2896.0
K = SQ / TEX
THETA_MAX = 0.2  # world2cam rejects theta >= 0.2 rad (about 101.5 deg off-axis)

OPAX = {
    'Left': dict(xc=1444.655517578125, yc=1446.1207275390625, c=1.0003042350904905,
                 d=6.55360925240386e-05, e=6.55360925240386e-05, radius=1444.302978515625),
    'Right': dict(xc=1444.0599365234375, yc=1447.00830078125, c=1.000595229889347,
                  d=-0.00014006204583861753, e=-0.00014006204583861753, radius=1440.99169921875),
    'DiffX': 4.6301984786987305, 'DiffY': 7.432691904700505, 'DiffRollAngle': 1.2563269531044017,
}
RAW_OFFSET = (7.42, -0.14)  # raw-half px = JPEG-square px + offset (pair 360_0334, ECC corr 0.90)

LAYOUTS = {
    'jpeg': dict(half=2896, offset=(0.0, 0.0), scale=1.0),
    'rawhalf': dict(half=1456, offset=RAW_OFFSET, scale=0.5),
    'raw': dict(half=2912, offset=RAW_OFFSET, scale=1.0),
}


# Samsung lens-shading (vignetting) correction, from libdi-alg-imagestitch.so (see docs/lab-notebook.md "Lens shading"):
# gain(r) = sum(c[i] * r**i) per colour channel, r = distance from the lens centre / 1448 px (half the 2896-px lens
# square, i.e. 2 x normalised texture distance). The first polynomial is picked by the per-lens OPAI value
# (maker note 0x0013: 0x743 and 0x7ca on our unit -> both >= 1300 -> set 'hi'); the other two are fixed.
# Channel order assumed R, G, B (the renderer fills a vector3df with them; not verified).
LSC_POLY_FIRST = {
    'lo': [1.0, 0.357137, -2.68483, 13.6964, -21.9303, 12.4693],     # OPAI value / 100 < 4
    'mid': [1.0, 0.35964, -2.70365, 13.7924, -22.0839, 12.5566],    # < 13
    'hi': [1.0, 0.325752, -2.37229, 12.7928, -20.9402, 12.1364],    # >= 13
}
LSC_POLY_G = [1.0, 0.314724, -2.18452, 11.8701, -19.2398, 11.0958]
LSC_POLY_B = [1.0, 0.244838, -1.38679, 8.98952, -15.132, 9.083]
LSC_SET = 'hi'
LSC_HALF = SQ / 2  # r = 1 at 1448 px


def lsc_gain(r):
    """RGB gain (..., 3) for normalised radius r (Samsung LSC polynomials)."""
    out = []
    for c in (LSC_POLY_FIRST[LSC_SET], LSC_POLY_G, LSC_POLY_B):
        g = np.zeros_like(r)
        for i, k in enumerate(c):
            g += k * r ** i
        out.append(g)
    return np.stack(out, axis=-1)


def srgb_decode(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb_encode(x):
    x = np.maximum(x, 0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def apply_lsc(img, lay, lenses, domain, strength=1.0):
    """Return a float32 copy of the whole dual-fisheye image with the lens-shading gain applied per half.

    domain 'srgb': decode sRGB, multiply in linear light, re-encode (for camera JPEGs).
    domain 'linear': multiply the values directly (linear raw renders).
    strength blends between no correction (0) and full (1): gain**strength.
    """
    scale = full_scale(img)
    f = as3(img).astype(np.float32) / scale
    h, w = f.shape[:2]
    for i, L in enumerate(lenses):
        x0 = i * lay['half']
        cols = np.arange(lay['half'], dtype=np.float64)
        rows = np.arange(h, dtype=np.float64)
        u = (cols + 0.5) / lay['scale'] - 0.5 - lay['offset'][0] - L['xc']
        v = (rows + 0.5) / lay['scale'] - 0.5 - lay['offset'][1] - L['yc']
        r = np.hypot(u[None, :], v[:, None]) / LSC_HALF
        g = lsc_gain(np.minimum(r, 1.05)) ** strength
        if f.shape[2] == 3:
            g = g[..., ::-1]          # OpenCV images are BGR
        else:
            g = g[..., 1:2]           # grey: use the green curve
        part = f[:, x0:x0 + lay['half']]
        if domain == 'srgb':
            part = srgb_encode(srgb_decode(part) * g)
        else:
            part = part * g
        f[:, x0:x0 + lay['half']] = part.astype(np.float32)
    log(f'lens shading: gain at r=0.95 (90 deg) R/G/B = {np.round(lsc_gain(np.array(0.95)), 3).tolist()}, '
        f'domain {domain}, strength {strength}')
    return (f * scale).astype(np.float32)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def rho_px(theta):
    t = np.asarray(theta, np.float64)
    r = np.zeros_like(t)
    for i, p in enumerate(INVPOL):
        r += p * t ** i
    return r * K


# inverse of rho_px on [-pi/2, THETA_MAX] by table lookup (rho is monotonic there)
_TH = np.linspace(-np.pi / 2, THETA_MAX, 20001)
_RH = rho_px(_TH)
assert np.all(np.diff(_RH) > 0), 'rho(theta) not monotonic'


def theta_of_rho(rho):
    return np.interp(rho, _RH, _TH)


def rot(yaw, pitch, roll):
    """Rotation matrix from degrees: yaw about Y (down axis), pitch about X (right), roll about Z (forward)."""
    y, p, r = np.radians([yaw, pitch, roll])
    Ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    Rz = np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


R_NOMINAL2 = rot(180, 0, 0)  # lens 2 looks backwards: frame rotated 180 deg about the vertical axis


def lens_ray_to_px(v, L, lay, half_index):
    """Unit rays in a lens frame (x right, y down, z forward), shape (..., 3) -> file pixel (col, row), valid mask."""
    x, y, z = v[..., 0], v[..., 1], v[..., 2]
    rxy = np.hypot(x, y)
    alpha = np.arctan2(rxy, z)          # angle off the optical axis
    theta = alpha - np.pi / 2
    valid = theta < THETA_MAX
    rho = rho_px(np.minimum(theta, THETA_MAX))
    with np.errstate(invalid='ignore', divide='ignore'):
        cphi = np.where(rxy > 0, x / rxy, 1.0)
        sphi = np.where(rxy > 0, y / rxy, 0.0)
    col = L['xc'] + L['c'] * rho * cphi + L['d'] * rho * sphi
    row = L['yc'] + L['e'] * rho * cphi + rho * sphi
    col = (col + lay['offset'][0]) * lay['scale'] + half_index * lay['half']
    row = (row + lay['offset'][1]) * lay['scale']
    return col, row, valid


def px_to_lens_ray(col, row, L, lay, half_index):
    """Inverse of lens_ray_to_px."""
    u = (col - half_index * lay['half']) / lay['scale'] - lay['offset'][0] - L['xc']
    w = row / lay['scale'] - lay['offset'][1] - L['yc']
    # undo affine [[c, d], [e, 1]]
    det = L['c'] - L['d'] * L['e']
    a = (u - L['d'] * w) / det        # rho*cos(phi)
    b = (L['c'] * w - L['e'] * u) / det  # rho*sin(phi)
    rho = np.hypot(a, b)
    alpha = theta_of_rho(rho) + np.pi / 2
    with np.errstate(invalid='ignore', divide='ignore'):
        cphi = np.where(rho > 0, a / rho, 1.0)
        sphi = np.where(rho > 0, b / rho, 0.0)
    s = np.sin(alpha)
    return np.stack([s * cphi, s * sphi, np.cos(alpha)], axis=-1)


def lens_setup(args):
    names = ('Right', 'Left') if args.swap else ('Left', 'Right')
    return [OPAX[names[0]], OPAX[names[1]]], names


def load(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        sys.exit(f'cannot read {path}')
    return img


def guess_layout(img, name):
    if name:
        return LAYOUTS[name]
    h, w = img.shape[:2]
    for k, lay in LAYOUTS.items():
        if w == 2 * lay['half'] and abs(h - SQ * lay['scale']) < 1:
            log(f'layout: {k} ({w}x{h})')
            return lay
    sys.exit(f'unknown layout {w}x{h}; pass --layout')


def seam_px(v, sw, sh, band_s):
    """World (= lens-0 frame) directions -> pixel coords in a ring_dirs strip of size sw x sh, +-band_s rad."""
    lam = np.arctan2(v[..., 1], v[..., 0])
    beta = np.arcsin(np.clip(v[..., 2], -1, 1))
    return (lam + np.pi) / (2 * np.pi) * sw - 0.5, (band_s - beta) / (2 * band_s) * sh - 0.5


def seam_dirs(px, py, sw, sh, band_s):
    """Inverse of seam_px."""
    lam = (px + 0.5) / sw * 2 * np.pi - np.pi
    beta = band_s - (py + 0.5) / sh * 2 * band_s
    return np.stack([np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta)], axis=-1)


def as3(a):
    return a if a.ndim == 3 else a[..., None]


def gray_of(a):
    a = as3(a)
    return a[..., 0] if a.shape[2] == 1 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)


def wrap_pad(a, pad):
    return np.concatenate([a[:, -pad:], a, a[:, :pad]], axis=1)


def blur_wrap(a, sigma):
    """Gaussian blur that wraps horizontally (the strip is a full 360 deg ring)."""
    pad = int(3 * sigma) + 1
    return cv2.GaussianBlur(wrap_pad(a, pad), (0, 0), sigma)[:, pad:-pad]


def full_scale(img):
    if img.dtype == np.uint8:
        return 255.0
    if img.dtype == np.uint16:
        return 65535.0
    return float(img.max())


def seam_strips(img, lay, lenses, Rs, sw, sh, band_s, alpha_max):
    """Render both lenses into the seam strip. Returns float32 strips (h, w, ch) and per-lens coverage masks."""
    dirs = ring_dirs(sw, sh, np.degrees(band_s))
    strips, cover = [], []
    for i, (L, R) in enumerate(zip(lenses, Rs)):
        v = dirs @ R
        col, row, valid = lens_ray_to_px(v, L, lay, i)
        st = cv2.remap(img, col.astype(np.float32), row.astype(np.float32), cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT)
        strips.append(as3(st).astype(np.float32))
        cover.append(valid & (np.arccos(np.clip(v[..., 2], -1, 1)) <= alpha_max[i]))
    return strips, cover


def seam_gain(strips, ok, sat):
    """Per-channel gain g = median(lens0 / lens1) over usable overlap pixels."""
    a, b = strips
    g = []
    for c in range(a.shape[2]):
        m = ok & (a[..., c] < sat) & (b[..., c] < sat) & (a[..., c] > 0) & (b[..., c] > 0)
        if m.sum() < 1000:
            log(f'  gain: channel {c}: only {int(m.sum())} usable pixels, using 1.0')
            g.append(1.0)
            continue
        g.append(float(np.median(a[..., c][m] / b[..., c][m])))
    return np.array(g, np.float32)


def seam_flow(g0, g1, lit, px_per_deg, args):
    """DIS flow f with g0(x) ~ g1(x + f), forward/backward checked, support-weighted smoothing, clamped."""
    max_px = args.flow_max * px_per_deg
    pad = int(max_px) + 32
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    log(f'  DIS optical flow on {g0.shape[1]}x{g0.shape[0]} seam strip (both directions) ...')
    f01 = dis.calc(wrap_pad(g0, pad), wrap_pad(g1, pad), None)[:, pad:-pad]
    f10 = dis.calc(wrap_pad(g1, pad), wrap_pad(g0, pad), None)[:, pad:-pad]
    h, w = g0.shape
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    back = cv2.remap(f10, gx + f01[..., 0], gy + f01[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    fb = np.hypot(f01[..., 0] + back[..., 0], f01[..., 1] + back[..., 1])
    mag = np.hypot(f01[..., 0], f01[..., 1])
    good = lit & (fb < args.flow_fb * px_per_deg) & (mag < max_px)
    log(f'  flow: {lit.sum()} overlap px, {good.sum()} pass fwd/back + max checks '
        f'({100 * good.sum() / max(lit.sum(), 1):.1f}%)')
    c = good.astype(np.float32)
    sig = max(args.flow_smooth * px_per_deg, 1.0)
    den = blur_wrap(c, sig)
    flow = blur_wrap(f01 * c[..., None], sig) / np.maximum(den, 0.2)[..., None]  # little support -> shrink to 0
    m = np.hypot(flow[..., 0], flow[..., 1])
    flow *= np.minimum(1.0, max_px / np.maximum(m, 1e-6))[..., None]
    m = np.minimum(m, max_px)[lit]
    if m.size:
        log(f'  smoothed flow in overlap: median {np.median(m) / px_per_deg:.3f} deg, '
            f'95th pct {np.percentile(m, 95) / px_per_deg:.3f} deg, max {m.max() / px_per_deg:.3f} deg')
    return flow.astype(np.float32)


def pyramid_blend(layers, weights, levels):
    """Laplacian-pyramid blend of float32 (h, w, ch) layers with (h, w) weights. levels=0 is a plain weighted sum."""
    acc, wacc = None, None
    for img, wgt in zip(layers, weights):
        g, ws = img, wgt.astype(np.float32)
        parts, wparts = [], []
        for _ in range(levels):
            down = cv2.pyrDown(g)
            up = as3(cv2.pyrUp(down, dstsize=(g.shape[1], g.shape[0])))
            parts.append((g - up) * ws[..., None])
            wparts.append(ws)
            g, ws = as3(down), cv2.pyrDown(ws)
        parts.append(g * ws[..., None])
        wparts.append(ws)
        if acc is None:
            acc, wacc = parts, wparts
        else:
            acc = [a + p for a, p in zip(acc, parts)]
            wacc = [a + p for a, p in zip(wacc, wparts)]
    acc = [a / np.maximum(w, 1e-6)[..., None] for a, w in zip(acc, wacc)]
    out = acc[-1]
    for lap in reversed(acc[:-1]):
        out = as3(cv2.pyrUp(out, dstsize=(lap.shape[1], lap.shape[0]))) + lap
    return out


def cmd_stitch(args):
    t0 = time.time()
    img = load(args.image)
    lay = guess_layout(img, args.layout)
    lenses, names = lens_setup(args)
    Rs = (np.eye(3), R_NOMINAL2 @ rot(*args.rot))
    src_dtype, src_scale = img.dtype, full_scale(img)
    if args.lsc != 'off':
        domain = args.lsc if args.lsc != 'auto' else ('srgb' if img.dtype == np.uint8 else 'linear')
        img = apply_lsc(img, lay, lenses, domain, args.lsc_strength)
        if img.shape[2] == 1:
            img = img[..., 0]
    W = args.width
    H = W // 2
    nch = 1 if img.ndim == 2 else img.shape[2]
    px_per_deg = W / 360.0
    band = np.radians(args.band)
    # usable image circle per lens, from the OPAX radius (2896-px lens-square units, same as rho)
    alpha_max = [float(theta_of_rho(L['radius'] - args.edge_margin)) + np.pi / 2 for L in lenses]
    log(f'image circle (OPAX radius - {args.edge_margin} px): lens 0 ({names[0]}) to '
        f'{np.degrees(alpha_max[0]):.2f} deg, lens 1 ({names[1]}) to {np.degrees(alpha_max[1]):.2f} deg off-axis')
    if np.degrees(min(alpha_max)) - 90 < args.band:
        log(f'WARNING: --band {args.band} reaches past the image circle; blend will use black edge pixels')

    gains = [np.ones(nch, np.float32), np.ones(nch, np.float32)]
    flow = None
    band_s = band + np.radians(2.0)
    sw, sh = W, max(16, int(round(2 * np.degrees(band_s) * px_per_deg)))
    if args.gain or args.flow:
        log(f'rendering {sw}x{sh} seam strips (+-{np.degrees(band_s):.1f} deg) ...')
        strips, cover = seam_strips(img, lay, lenses, Rs, sw, sh, band_s, alpha_max)
        grays = [gray_of(st) for st in strips]
        lit = cover[0] & cover[1]
        for gr, cv in zip(grays, cover):
            med = float(np.median(gr[cv])) if cv.any() else 0.0
            lit &= cv2.GaussianBlur(gr, (0, 0), 2) > args.dark * med
        lit = cv2.erode(lit.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        rows_beta = band_s - (np.arange(sh) + 0.5) / sh * 2 * band_s
        inner = lit & (np.abs(rows_beta) < band)[:, None]
        if args.gain:
            g = seam_gain(strips, inner, 0.98 * src_scale)
            gains = [1 / np.sqrt(g), np.sqrt(g)]
            log(f'  seam gain lens0/lens1 per channel: {np.round(g, 4).tolist()} (split evenly)')
        if args.flow:
            st = [s * gn for s, gn in zip(strips, gains)]
            gr = [gray_of(s) for s in st]
            both = np.concatenate([gr[0][lit], gr[1][lit]])
            scale = float(np.percentile(both, 99.5)) if both.size else 1.0
            g8 = [(np.clip(x / max(scale, 1e-6), 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8) for x in gr]
            flow = seam_flow(g8[0], g8[1], lit, px_per_deg, args)
            if args.save_seam:
                h, w = g8[0].shape
                gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
                warped = cv2.remap(g8[1], gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_WRAP)
                mag = np.hypot(flow[..., 0], flow[..., 1]) / (args.flow_max * px_per_deg)
                viz = np.vstack([g8[0], g8[1], warped, (np.clip(mag, 0, 1) * 255).astype(np.uint8)])
                cv2.imwrite(args.save_seam, viz)
                log(f'  wrote {args.save_seam} (rows: lens 0, lens 1, lens 1 warped onto lens 0, flow magnitude)')

    layers = [np.zeros((H, W, nch), np.float32) for _ in range(2)]
    covers = [np.zeros((H, W), bool) for _ in range(2)]
    tmap = np.zeros((H, W), np.float32)
    lon = (np.arange(W) + 0.5) / W * 2 * np.pi - np.pi
    step = max(1, (1 << 21) // W)
    log(f'remapping both lenses to {W}x{H} ...')
    for r0 in range(0, H, step):
        r1 = min(H, r0 + step)
        lat = np.pi / 2 - (np.arange(r0, r1) + 0.5) / H * np.pi
        lo, la = np.meshgrid(lon, lat)
        world = np.stack([np.cos(la) * np.sin(lo), -np.sin(la), np.cos(la) * np.cos(lo)], axis=-1)
        beta = np.arcsin(np.clip(world[..., 2], -1, 1))   # elevation above the seam plane, towards lens 0
        t = np.clip((band - beta) / (2 * band), 0, 1)       # 0 = lens-0 side of the band, 1 = lens-1 side
        tmap[r0:r1] = t
        dirs = [world, world]
        if flow is not None:
            inband = (np.abs(beta) < band)[..., None]
            px, py = seam_px(world, sw, sh, band_s)
            f = cv2.remap(flow, px.astype(np.float32), py.astype(np.float32), cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_WRAP) * inband
            # scene point at strip x0 (lens 0) and x0 + f (lens 1) is drawn at x0 + t f
            d0 = seam_dirs(px - t * f[..., 0], py - t * f[..., 1], sw, sh, band_s)
            d1 = seam_dirs(px + (1 - t) * f[..., 0], py + (1 - t) * f[..., 1], sw, sh, band_s)
            dirs = [np.where(inband, d0, world), np.where(inband, d1, world)]
        for i, (L, R) in enumerate(zip(lenses, Rs)):
            v = dirs[i] @ R
            col, row, valid = lens_ray_to_px(v, L, lay, i)
            covers[i][r0:r1] = valid & (np.arccos(np.clip(v[..., 2], -1, 1)) <= alpha_max[i])
            warped = cv2.remap(img, col.astype(np.float32), row.astype(np.float32), cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_CONSTANT)
            layers[i][r0:r1] = as3(warped).astype(np.float32) * gains[i]
        log(f'  rows {r1}/{H} ({100 * r1 / H:.0f}%)')

    # outside a lens's image circle, give its layer the other lens's pixels so pyramid levels see no black edge
    for i in range(2):
        m = ~covers[i]
        layers[i][m] = layers[1 - i][m]
    if args.blend == 'multiband':
        w0 = (tmap < 0.5).astype(np.float32)
        levels = args.levels or max(1, int(np.log2(max(2 * args.band * px_per_deg, 2))))
    else:
        w0 = 1 - tmap
        levels = 0
    w0[~covers[0]] = 0
    w0[~covers[1] & covers[0]] = 1
    log(f'blending ({args.blend}, {levels} pyramid levels) ...')
    out = pyramid_blend(layers, [w0, 1 - w0], levels)
    if nch == 1:
        out = out[..., 0]
    if src_dtype == np.uint8:
        out = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    elif src_dtype == np.uint16:
        out = np.clip(out + 0.5, 0, 65535).astype(np.uint16)
    cv2.imwrite(args.out, out)
    log(f'wrote {args.out} in {time.time() - t0:.1f}s (lens-2 correction yaw/pitch/roll = {args.rot})')


def kabsch(a, b):
    """Rotation R minimising |R a_i - b_i|."""
    Hm = a.T @ b
    U, _, Vt = np.linalg.svd(Hm)
    D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
    return Vt.T @ D @ U.T


def ypr_from(R):
    """Inverse of rot(): R = Ry @ Rx @ Rz -> (yaw, pitch, roll) degrees."""
    pitch = np.degrees(np.arcsin(-R[1, 2]))
    yaw = np.degrees(np.arctan2(R[0, 2], R[2, 2]))
    roll = np.degrees(np.arctan2(R[1, 0], R[1, 1]))
    return yaw, pitch, roll


def ring_dirs(width, height, band):
    """World directions for a strip around the seam circle (90 deg off lens-1 axis).

    Column = longitude around the lens-1 axis (+Z), row = elevation beta from +band (towards lens 1) to -band.
    """
    lam = (np.arange(width) + 0.5) / width * 2 * np.pi - np.pi
    beta = np.radians(band) - (np.arange(height) + 0.5) / height * 2 * np.radians(band)
    lam, beta = np.meshgrid(lam, beta)
    return np.stack([np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta)], axis=-1)


def render_strip(img, L, lay, i, R, dirs):
    v = dirs @ R
    col, row, valid = lens_ray_to_px(v, L, lay, i)
    out = cv2.remap(img, col.astype(np.float32), row.astype(np.float32), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT)
    return out, valid


def grad(img):
    g = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.0)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def tile_matches(strips, valids, sw, sh, px_per_deg, args):
    """Phase-correlate gradient images of the two seam strips in tiles along the seam.

    Returns matched strip points (p0 in lens-0 strip, p1 in lens-1 strip) for tiles with a confident peak.
    """
    g0, g1 = grad(strips[0]), grad(strips[1])
    both = valids[0] & valids[1]
    rows = np.nonzero(both.mean(axis=1) > 0.3)[0]
    if len(rows) < 16:
        sys.exit('no overlap rows between the strips')
    r0, r1 = rows.min(), rows.max() + 1
    log(f'  overlap rows {r0}-{r1} of {sh} ({(r1 - r0) / px_per_deg:.1f} deg)')
    tw = int(args.tile * px_per_deg)
    win = cv2.createHanningWindow((tw, r1 - r0), cv2.CV_32F)
    p0, p1 = [], []
    for x0 in range(0, sw - tw + 1, max(tw // 2, 1)):
        m = both[r0:r1, x0:x0 + tw]
        if m.mean() < 0.8:
            continue
        a = g0[r0:r1, x0:x0 + tw]
        b = g1[r0:r1, x0:x0 + tw]
        if a.std() < args.min_texture or b.std() < args.min_texture:
            continue
        (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
        if args.verbose:
            log(f'    tile lon {x0 / px_per_deg - 180 + args.tile / 2:+7.1f}: dx {dx:+6.2f} dy {dy:+6.2f} px  '
                f'resp {resp:.3f}  tex {a.std():.1f}/{b.std():.1f}')
        if resp < args.min_response:
            continue
        c = np.array([x0 + tw / 2, (r0 + r1) / 2])
        p0.append(c)
        p1.append(c + [dx, dy])
    log(f'  tiles: {len(p0)} confident ({args.tile} deg wide, response >= {args.min_response})')
    return np.array(p0).reshape(-1, 2), np.array(p1).reshape(-1, 2)


def cmd_solve(args):
    t0 = time.time()
    img = load(args.image)
    lay = guess_layout(img, args.layout)
    lenses, names = lens_setup(args)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    px_per_deg = INVPOL[1] * K * np.pi / 180 * lay['scale']
    sw = int(round(360 * px_per_deg))          # strip at native resolution around the seam
    sh = int(round(2 * args.band * px_per_deg))
    dirs = ring_dirs(sw, sh, args.band)
    log(f'rendering {sw}x{sh} seam strips (+-{args.band} deg) ...')
    strips, valids, kps, descs = [], [], [], []
    sift = cv2.SIFT_create(nfeatures=args.features)
    for i, (L, R) in enumerate(zip(lenses, (np.eye(3), R_NOMINAL2))):
        st, valid = render_strip(gray, L, lay, i, R, dirs)
        lit = st[valid & (st > 2)]
        dark_thr = max(2.0, args.dark * float(np.median(lit))) if lit.size else 2.0
        mask = (valid & (cv2.GaussianBlur(st, (0, 0), 3) > dark_thr)).astype(np.uint8) * 255
        mask = cv2.erode(mask, np.ones((9, 9), np.uint8))
        kp, de = sift.detectAndCompute(st, mask)
        log(f'  lens {i} ({names[i]}): {len(kp)} keypoints')
        strips.append(st)
        valids.append(mask > 0)
        kps.append(np.array([k.pt for k in kp], np.float64))
        descs.append(de)
    if args.save_strips:
        cv2.imwrite(args.save_strips, np.vstack(strips))
        log(f'  wrote {args.save_strips} (top: lens 0, bottom: lens 1, nominal 180 deg)')
    if args.method == 'sift':
        m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(descs[0], descs[1], k=2)
        good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < args.ratio * b.distance]
        p0 = np.array([kps[0][g.queryIdx] for g in good]).reshape(-1, 2)
        p1 = np.array([kps[1][g.trainIdx] for g in good]).reshape(-1, 2)
        log(f'  {len(good)} ratio-test matches')
    else:
        p0, p1 = tile_matches(strips, valids, sw, sh, px_per_deg, args)
    d = p1 - p0
    d[:, 0] = (d[:, 0] + sw / 2) % sw - sw / 2      # wrap longitude
    near = np.hypot(d[:, 0], d[:, 1]) < args.maxshift * px_per_deg
    log(f'  {len(p0)} matches, {int(near.sum())} within {args.maxshift} deg of nominal')
    p0, p1 = p0[near], p1[near]
    if len(p0) < 6:
        sys.exit('too few matches')

    def strip_ray(p):
        lam = p[:, 0] / sw * 2 * np.pi - np.pi
        beta = np.radians(args.band) - p[:, 1] / sh * 2 * np.radians(args.band)
        return np.stack([np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta)], axis=-1)

    b = strip_ray(p0)       # true direction seen by lens 0 (world frame)
    a_nom = strip_ray(p1)   # direction lens 1 claims under the nominal 180 deg rotation
    rng = np.random.default_rng(0)
    best_in = None
    thr = np.radians(args.thresh)
    for _ in range(args.iters):
        idx = rng.choice(len(a_nom), 3, replace=False)
        Rc = kabsch(a_nom[idx], b[idx])
        err = np.arccos(np.clip(np.sum((a_nom @ Rc.T) * b, axis=1), -1, 1))
        inl = err < thr
        if best_in is None or inl.sum() > best_in.sum():
            best_in = inl
    Rc = kabsch(a_nom[best_in], b[best_in])
    err = np.degrees(np.arccos(np.clip(np.sum((a_nom @ Rc.T) * b, axis=1), -1, 1)))
    err0 = np.degrees(np.arccos(np.clip(np.sum(a_nom * b, axis=1), -1, 1)))
    # as a correction in the lens-2 frame: world = R_NOMINAL2 @ Rcorr @ ray2, where Rc @ R_NOMINAL2 = R_NOMINAL2 @ Rcorr
    Rcorr = R_NOMINAL2.T @ Rc @ R_NOMINAL2
    y, p, r = ypr_from(Rcorr)
    k = px_per_deg / lay['scale']
    print(f'image: {args.image}  lenses: half0={names[0]} half1={names[1]}')
    print(f'matches {len(p0)}, inliers {int(best_in.sum())} (thresh {args.thresh} deg)')
    print(f'inlier angular error: nominal 180deg only: median {np.median(err0[best_in]):.3f} deg; '
          f'after correction: median {np.median(err[best_in]):.3f}, 90th pct {np.percentile(err[best_in], 90):.3f} deg')
    print(f'lens-2 correction (yaw, pitch, roll) = ({y:+.4f}, {p:+.4f}, {r:+.4f}) deg   '
          f'-> use: --rot {y:.4f} {p:.4f} {r:.4f}')
    print(f'OPAX DiffX {OPAX["DiffX"]:.3f}, DiffY {OPAX["DiffY"]:.3f}, DiffRollAngle {OPAX["DiffRollAngle"]:.3f}; '
          f'at {k:.3f} px/deg (2896 scale, rho slope at 90 deg): DiffX = {OPAX["DiffX"] / k:.4f} deg, '
          f'DiffY = {OPAX["DiffY"] / k:.4f} deg')
    log(f'done in {time.time() - t0:.1f}s')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--layout', choices=list(LAYOUTS), help='default: guess from image size')
    ap.add_argument('--swap', action='store_true', help='JPEG half 0 = OPAX Right (default half 0 = Left)')
    sp = ap.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('stitch')
    s.add_argument('image')
    s.add_argument('out')
    s.add_argument('--rot', nargs=3, type=float, default=[0, 0, 0], metavar=('YAW', 'PITCH', 'ROLL'),
                   help='lens-2 correction in degrees on top of the nominal 180 deg')
    s.add_argument('--width', type=int, default=4096)
    s.add_argument('--blend', choices=['multiband', 'feather'], default='multiband')
    s.add_argument('--band', '--feather', dest='band', type=float, default=3.0,
                   help='seam band half-width in degrees around 90 deg (feather width, flow warp zone)')
    s.add_argument('--levels', type=int, default=0, help='multiband pyramid levels (0 = auto from --band)')
    s.add_argument('--no-gain', dest='gain', action='store_false', help='skip seam gain matching')
    s.add_argument('--edge-margin', type=float, default=20.0,
                   help='px inside the OPAX image-circle radius counted as usable (2896-px units)')
    s.add_argument('--dark', type=float, default=0.25, help='overlap px below this x median count as unusable')
    s.add_argument('--flow', action='store_true', help='optical-flow seam warp for near-field parallax')
    s.add_argument('--flow-max', type=float, default=3.0, help='largest flow kept, degrees')
    s.add_argument('--flow-smooth', type=float, default=0.5, help='flow smoothing sigma, degrees')
    s.add_argument('--flow-fb', type=float, default=0.15, help='forward/backward flow mismatch limit, degrees')
    s.add_argument('--lsc', choices=['auto', 'srgb', 'linear', 'off'], default='auto',
                   help="Samsung lens-shading correction: auto = srgb for 8-bit JPEGs, linear otherwise")
    s.add_argument('--lsc-strength', type=float, default=1.0, help='0 = none, 1 = full Samsung gain')
    s.add_argument('--save-seam', help='write a debug image of the seam strips and flow (needs --flow)')
    s.set_defaults(func=cmd_stitch)
    v = sp.add_parser('solve')
    v.add_argument('image')
    v.add_argument('--band', type=float, default=11.0, help='strip half-height around the seam, degrees')
    v.add_argument('--maxshift', type=float, default=3.0, help='reject matches further than this from nominal, deg')
    v.add_argument('--method', choices=['tiles', 'sift'], default='tiles')
    v.add_argument('--tile', type=float, default=6.0, help='tile width along the seam, degrees')
    v.add_argument('--min-response', type=float, default=0.15, help='phase-correlation peak threshold')
    v.add_argument('--min-texture', type=float, default=2.0, help='skip tiles with gradient std below this')
    v.add_argument('--dark', type=float, default=0.25, help='strip pixels below this x median count as dark/invalid')
    v.add_argument('--verbose', action='store_true')
    v.add_argument('--save-strips', help='write the two seam strips (stacked) to this image file')
    v.add_argument('--features', type=int, default=20000)
    v.add_argument('--ratio', type=float, default=0.75)
    v.add_argument('--thresh', type=float, default=0.3, help='RANSAC inlier threshold, degrees')
    v.add_argument('--iters', type=int, default=3000)
    v.set_defaults(func=cmd_solve)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
