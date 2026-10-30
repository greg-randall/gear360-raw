#!/usr/bin/env python3
"""Solve the Gear 360 lens-2 rotation and lens baseline from projector-grid shots.

Each shot shows a projected line grid (utils/make_grid.sh) near the seam, seen by both lenses.
Per shot:
  1. render both lenses into one shared perspective view of the screen (lens 2 under the nominal 180 deg
     rotation), using the camera's own lens model + OPAX (tools/opax_stitch.py);
  2. grid method: oriented ridge filters pick out each line family, a Gabor filter at the family's spatial
     frequency gives a phase that grows by 2 pi per line, and unwrapping it gives continuous lattice
     coordinates (u, v) at every pixel of the grid (robust to the text labels; a constant phase bias from the
     labels is absorbed by the per-shot homography below);
  3. the integer lattice offset between the two lenses comes from the phase difference in the overlap, and is
     checked by comparing the label-carrying cell contents in lattice-rectified images (labels are unique).
     That check is weak along rows (neighbouring labels differ by one letter), so the offset actually used is
     the one, within +-2 cells of the rounded phase difference, whose closed-form per-shot lens-1 rotation
     agrees with the other shots (choose_offsets); --offset overrides it.
ChArUco mode (--charuco BOARD.json, board from utils/make_charuco.py): step 2-3 are replaced by OpenCV's ChArUco
detector on the green channel of each lens's view; corners are matched across the lenses by ID (no offset search) and
their lattice coords are the board corner positions in squares. --detect-only reports counts without solving.
Observations are pixels sampled every 10 px in the measured region: (u, v) -> lens ray. Detections are cached in
--out as obs_<shot>.npz (--redetect to redo).
Then a joint least-squares fit over all shots:
  shared: lens-2 rotation correction (yaw, pitch, roll) and lens-2 centre c (3-vector, lens-0 frame);
  per shot: H (3x3, lattice index -> lens-0 ray direction; absorbs projector keystone) and the screen plane
  (unit normal n, distance d from lens 0). Scale gauge: the first shot's plane distance is held at 1, so c
  comes out in units of that distance.
  Residuals: angle between each observed ray and its prediction (lens 0: H; lens 2: plane point seen from c).
The screen is a pull-down screen and not perfectly flat; that shows up as residual.

Usage:
  python3 tools/grid_solve.py captures/2026-10-11/360_037[5-9].JPG --out calibration/grid_solve [--swap]
"""
import argparse
import json
import os
import sys
import time

# Cap threads at half the cores (the machine has hard-reset under full load); must precede numpy's import.
# Override with GRID_SOLVE_THREADS.
THREADS = int(os.environ.get('GRID_SOLVE_THREADS', max(1, (os.cpu_count() or 2) // 2)))
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_v, str(THREADS))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.interpolate import griddata  # noqa: E402
from scipy.optimize import least_squares  # noqa: E402
from skimage.restoration import unwrap_phase  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opax_stitch as ox  # noqa: E402

VIEW_W, VIEW_H, VIEW_FOV = 2400, 1800, 100.0


cv2.setNumThreads(THREADS)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def screen_dir(img, L, lay, h, R, mode='green'):
    """World direction of the projected pattern as seen by lens h, from the median of its pixels: 'green' = clearly
    green pixels (line grid), 'bright' = bright pixels in any colour (white or green ChArUco board)."""
    half = lay['half']
    sq = img[:, h * half:(h + 1) * half].astype(np.float32)
    b, g, r = cv2.split(sq)
    if mode == 'green':
        m = (g > b + 25) & (g > r + 25) & (g > 60)
    else:
        lum = np.maximum(np.maximum(b, g), r)
        m = lum > max(60.0, 0.5 * float(np.percentile(lum, 99.5)))
    ys, xs = np.nonzero(m)
    if len(xs) < 500:
        return None
    v = ox.px_to_lens_ray(np.array(np.median(xs) + h * half), np.array(float(np.median(ys))), L, lay, h)
    return R @ v


class View:
    """Perspective view: pixel (u, v) <-> world direction."""

    def __init__(self, z):
        z = z / np.linalg.norm(z)
        up = np.array([0, -1.0, 0]) if abs(z[1]) < 0.9 else np.array([1.0, 0, 0])
        x = np.cross(up, z)
        x /= np.linalg.norm(x)
        self.B = np.stack([x, np.cross(z, x), z])     # rows: x, y, z axes of the view in world coords
        self.f = (VIEW_W / 2) / np.tan(np.radians(VIEW_FOV / 2))

    def dirs(self, u, v):
        d = np.stack([u - VIEW_W / 2 + 0.5, v - VIEW_H / 2 + 0.5, np.full_like(u, self.f)], axis=-1) @ self.B
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def px(self, d):
        c = d @ self.B.T
        return c[..., 0] / c[..., 2] * self.f + VIEW_W / 2 - 0.5, c[..., 1] / c[..., 2] * self.f + VIEW_H / 2 - 0.5


def render(img, view, L, lay, h, R):
    u, v = np.meshgrid(np.arange(VIEW_W, dtype=np.float64), np.arange(VIEW_H, dtype=np.float64))
    d = view.dirs(u, v)
    col, row, ok = ox.lens_ray_to_px(d @ R, L, lay, h)          # world -> lens frame: R^T d
    out = cv2.remap(img, col.astype(np.float32), row.astype(np.float32), cv2.INTER_CUBIC)
    # keep only this lens's image circle (beyond it the remap would read the other half of the JPEG)
    ok &= np.hypot(col - h * lay['half'] - L['xc'], row - L['yc']) < L['radius'] - 8
    out[~ok] = 0
    return out, ok


def ridge_kernel(theta_deg, s_across=1.6, s_along=12.0):
    r = int(3 * s_along)
    y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    t = np.radians(theta_deg)
    along = x * np.cos(t) + y * np.sin(t)
    across = -x * np.sin(t) + y * np.cos(t)
    k = (1 - across ** 2 / s_across ** 2) * np.exp(-across ** 2 / (2 * s_across ** 2) - along ** 2 / (2 * s_along ** 2))
    k -= k.mean()
    return k / np.abs(k).sum()


def line_map(g, inner, base):
    """Ridge response of bright lines within +-14 deg of `base` (0 = horizontal, 90 = vertical)."""
    out = None
    for dd in range(-14, 15, 2):
        r = cv2.filter2D(g, -1, ridge_kernel(base + dd))
        out = r if out is None else np.maximum(out, r)
    out = np.clip(out, 0, None)
    out[~inner] = 0
    return out


def peak_freq(R, inner, normal_deg):
    """Strongest spatial frequency of R with its normal within 25 deg of normal_deg, period 30-85 px.
    Returned in a canonical half-plane (positive along normal_deg) so both lenses get the same phase direction."""
    H, W = R.shape
    win = np.outer(np.hanning(H), np.hanning(W)).astype(np.float32)
    P = np.abs(np.fft.fftshift(np.fft.fft2((R - R[inner].mean()) * inner * win))) ** 2
    cy, cx = H // 2, W // 2
    fy, fx = np.mgrid[-cy:H - cy, -cx:W - cx]
    fy = fy / H
    fx = fx / W
    fr = np.hypot(fx, fy)
    ang = np.degrees(np.arctan2(fy, fx)) % 180
    m = (fr > 1 / 85) & (fr < 1 / 30) & (np.abs(((ang - normal_deg + 90) % 180) - 90) < 25)
    P[~m] = 0
    k = np.unravel_index(np.argmax(P), P.shape)
    f = np.array([fx[k], fy[k]])
    # the line map has harmonics; if there is real power at half this frequency, that is the fundamental
    hy, hx = int(round(cy + f[1] * H / 2)), int(round(cx + f[0] * W / 2))
    if P[hy - 2:hy + 3, hx - 2:hx + 3].max() > 0.2 * P[k]:
        k = np.unravel_index(np.argmax(P[hy - 2:hy + 3, hx - 2:hx + 3]), (5, 5))
        k = (hy - 2 + k[0], hx - 2 + k[1])
        f = np.array([fx[k], fy[k]])
    nrm = np.array([np.cos(np.radians(normal_deg)), np.sin(np.radians(normal_deg))])
    return f if f @ nrm > 0 else -f


def grid_phase(view_img, ok):
    """Grid method: unwrapped phase of each line family -> continuous lattice coordinates (u, v) per pixel.
    u counts near-vertical lines (increasing to the right), v near-horizontal lines (increasing downwards).
    Returns u, v (NaN outside the measured region) and the two periods in px."""
    g = view_img[..., 1].astype(np.float32)
    g = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    inner = cv2.erode(ok.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)
    res, periods = [], []
    for base, normal in ((90, 0), (0, 90)):           # u from vertical lines, v from horizontal lines
        R = line_map(g, inner, base)
        f = peak_freq(R, inner, normal)
        period = 1 / np.hypot(*f)
        sig = 0.9 * period
        r = int(3 * sig)
        y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
        env = np.exp(-(x ** 2 + y ** 2) / (2 * sig ** 2))
        arg = 2 * np.pi * (f[0] * x + f[1] * y)
        kc = env * np.cos(arg)
        kc -= kc.sum() / env.sum() * env               # remove the DC response
        ks = env * np.sin(arg)
        Rc = cv2.filter2D(R, -1, kc)
        Rs = cv2.filter2D(R, -1, ks)
        amp = np.hypot(Rc, Rs)
        m = (amp > 0.25 * np.percentile(amp[inner], 95)) & inner
        m = cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        nlab, lab = cv2.connectedComponents(m.astype(np.uint8))
        if not m.any():
            return None
        m = lab == np.argmax(np.bincount(lab[m]))
        unw = unwrap_phase(np.ma.array(np.arctan2(Rs, Rc), mask=~m)).filled(np.nan)
        # cv2.filter2D correlates, so the phase decreases along +f; flip so it increases
        res.append(-unw / (2 * np.pi))
        periods.append(period)
    return res[0], res[1], periods


def rectify(view_img, u, v, valid, ppc=16):
    """Resample a view into lattice coordinates (ppc px per cell). Returns image and (u0, v0) of its origin."""
    yy, xx = np.nonzero(valid)
    step = max(1, len(yy) // 60000)
    yy, xx = yy[::step], xx[::step]
    uu, vv = u[yy, xx], v[yy, xx]
    u0, v0 = np.floor(uu.min()), np.floor(vv.min())
    w = int(np.ceil((uu.max() - u0) * ppc)) + 1
    h = int(np.ceil((vv.max() - v0) * ppc)) + 1
    gu, gv = np.meshgrid(u0 + np.arange(w) / ppc, v0 + np.arange(h) / ppc)
    tri_x = griddata((uu, vv), xx.astype(np.float32), (gu, gv), method='linear')
    tri_y = griddata((uu, vv), yy.astype(np.float32), (gu, gv), method='linear')
    bad = np.isnan(tri_x) | np.isnan(tri_y)
    g = cv2.cvtColor(view_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    out = cv2.remap(g, np.nan_to_num(tri_x).astype(np.float32), np.nan_to_num(tri_y).astype(np.float32),
                    cv2.INTER_LINEAR)
    out[bad] = np.nan
    return out, (u0, v0)


def lattice_offset(views, uv, valids, guess, ppc=16, search=2):
    """Integer (du, dv) to add to lens-1 lattice coords so they match lens 0: compare the label-carrying cell
    interiors (grid lines masked, they match at any integer shift) in lattice-rectified images around the
    rounded phase difference. The guess alone is not enough: under the nominal rotation the lenses are
    misaligned by up to ~1 cell, so rounding can land on the wrong integer."""
    r0, o0 = rectify(views[0], uv[0][0], uv[0][1], valids[0], ppc)
    r1, o1 = rectify(views[1], uv[1][0], uv[1][1], valids[1], ppc)
    scores = {}
    for du in range(guess[0] - search, guess[0] + search + 1):
        for dv in range(guess[1] - search, guess[1] + search + 1):
            # lens-1 lattice (a, b) -> lens-0 lattice (a + du, b + dv); place r1 in r0's grid
            sx = int(round((o1[0] + du - o0[0]) * ppc))
            sy = int(round((o1[1] + dv - o0[1]) * ppc))
            h1, w1 = r1.shape
            ys0, xs0 = max(0, sy), max(0, sx)
            ye0, xe0 = min(r0.shape[0], sy + h1), min(r0.shape[1], sx + w1)
            if ye0 - ys0 < 2 * ppc or xe0 - xs0 < 2 * ppc:
                continue
            a = r0[ys0:ye0, xs0:xe0]
            b = r1[ys0 - sy:ye0 - sy, xs0 - sx:xe0 - sx]
            m = ~np.isnan(a) & ~np.isnan(b)
            # both rectified origins are integer lattice coords, so cell borders sit at multiples of ppc
            yy, xx = np.mgrid[ys0:ye0, xs0:xe0]
            m &= ((yy % ppc) >= ppc // 5) & ((yy % ppc) < ppc - ppc // 5)
            m &= ((xx % ppc) >= ppc // 5) & ((xx % ppc) < ppc - ppc // 5)
            if m.sum() < 2 * ppc * ppc:
                continue
            aa = a[m] - a[m].mean()
            bb = b[m] - b[m].mean()
            scores[(du, dv)] = (float((aa * bb).sum() / np.sqrt((aa * aa).sum() * (bb * bb).sum())),
                                int(m.sum() // (ppc * ppc)))
    if not scores:
        return None, scores
    return max(scores, key=lambda k: scores[k][0]), scores


def load_charuco(spec_path):
    """Board + detector from the JSON written by utils/make_charuco.py."""
    spec = json.load(open(spec_path))
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, spec['dictionary']))
    board = cv2.aruco.CharucoBoard((spec['squares_x'], spec['squares_y']), float(spec['square_px']),
                                   float(spec['marker_px']), dictionary)
    board.setLegacyPattern(bool(spec['legacy_pattern']))
    cp = cv2.aruco.CharucoParameters()
    cp.tryRefineMarkers = True
    det = cv2.aruco.CharucoDetector(board, cp, cv2.aruco.DetectorParameters(), cv2.aruco.RefineParameters())
    return spec, det


def charuco_detect(gray, det):
    """Detect corners in a view; also tries the mirror image (ArUco cannot decode mirrored markers, and the screen
    may be seen mirrored) and keeps whichever decodes more markers. Returns (xy (n, 2), ids (n,), n_markers,
    mirrored)."""
    best = None
    for mirrored in (False, True):
        im = gray[:, ::-1].copy() if mirrored else gray
        corners, ids, _, mids = det.detectBoard(im)
        nm = 0 if mids is None else len(mids)
        if ids is None or len(ids) == 0:
            xy, idv = np.zeros((0, 2)), np.zeros(0, int)
        else:
            xy = corners.reshape(-1, 2).astype(np.float64)
            idv = ids.ravel().astype(int)
            if mirrored:
                xy[:, 0] = gray.shape[1] - 1 - xy[:, 0]
        if best is None or nm > best[2]:
            best = (xy, idv, nm, mirrored)
    return best


def detect_shot_charuco(path, lenses, lay, out_dir, spec, det):
    """ChArUco path: corners matched across the lenses by ID, lattice coords = board corner position in squares."""
    img = cv2.imread(path)
    if img is None:
        sys.exit(f'cannot read {path}')
    name = os.path.splitext(os.path.basename(path))[0]
    Rs = [np.eye(3), ox.R_NOMINAL2]
    dirs = [screen_dir(img, L, lay, h, R, mode='bright') for h, (L, R) in enumerate(zip(lenses, Rs))]
    if any(d is None for d in dirs):
        log(f'  {name}: board not found in both lenses, skipped')
        return None
    view = View(dirs[0] + dirs[1])
    ncx = spec['squares_x'] - 1
    for attempt in (1, 2):
        obs, found, views, notes = [], [], [], []
        for h in (0, 1):
            vimg, ok = render(img, view, lenses[h], lay, h, Rs[h])
            xy, ids, nm, mirrored = charuco_detect(vimg[..., 1], det)
            notes.append(f'  {name} lens {h}: {nm}/{spec["markers"]} markers, {len(ids)}/{spec["inner_corners"]} '
                         f'corners{" (mirrored view)" if mirrored else ""}')
            ij = np.stack([ids % ncx + 1, ids // ncx + 1], axis=1).astype(np.float64)
            ray = view.dirs(xy[:, 0], xy[:, 1]) @ Rs[h] if len(xy) else np.zeros((0, 3))
            obs.append((ij, ray))
            found.append((xy, ids))
            views.append(vimg)
        # the bright-pixel screen direction can be pulled off the board (lamp, window, light on the floor):
        # re-centre the view on the corners actually found and detect again
        world = [r @ R.T for (_, r), R in zip(obs, Rs) if len(r)]
        if attempt == 2 or not world:
            break
        centre = unit(np.concatenate(world).mean(0))
        shift = np.degrees(np.arccos(np.clip(centre @ view.B[2], -1, 1)))
        log(f'  {name}: first pass {len(found[0][1])} + {len(found[1][1])} corners; re-centring the view by '
            f'{shift:.1f} deg on them')
        view = View(centre)
    for n in notes:
        log(n)
    shared = np.intersect1d(found[0][1], found[1][1])
    log(f'  {name}: {len(shared)} corners seen by both lenses')
    vis = cv2.addWeighted(views[0], 0.5, views[1], 0.5, 0)
    for h, colr in ((0, (0, 0, 255)), (1, (255, 0, 255))):
        for (x, y), i in zip(*found[h]):
            p = (int(round(x)), int(round(y)))
            cv2.drawMarker(vis, p, colr, cv2.MARKER_CROSS if h == 0 else cv2.MARKER_TILTED_CROSS, 14, 2)
            if h == 0 or i not in found[0][1]:
                cv2.putText(vis, str(i), (p[0] + 6, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colr, 1)
    cv2.imwrite(os.path.join(out_dir, f'charuco_{name}.jpg'), vis)
    if min(len(found[0][1]), len(found[1][1])) < 4 or len(shared) < 4:
        log(f'  {name}: too few corners to use (need >= 4 per lens and >= 4 shared), skipped')
        return None
    return dict(name=name, obs=obs, raw_obs1=obs[1], phase_diff=(0.0, 0.0), guess=(0, 0),
                label_scores={(0, 0): (1.0, int(len(shared)))}, label_pick=(0, 0), overlap=int(len(shared)))


def detect_shot(path, lenses, lay, out_dir, sample=10):
    img = cv2.imread(path)
    if img is None:
        sys.exit(f'cannot read {path}')
    name = os.path.splitext(os.path.basename(path))[0]
    Rs = [np.eye(3), ox.R_NOMINAL2]
    dirs = [screen_dir(img, L, lay, h, R) for h, (L, R) in enumerate(zip(lenses, Rs))]
    if any(d is None for d in dirs):
        log(f'  {name}: grid not found in both lenses, skipped')
        return None
    view = View(dirs[0] + dirs[1])
    views, uv, valids = [], [], []
    for h in (0, 1):
        vimg, ok = render(img, view, lenses[h], lay, h, Rs[h])
        r = grid_phase(vimg, ok)
        if r is None:
            log(f'  {name} lens {h}: no grid phase, skipped')
            return None
        u, v, periods = r
        valid = ~np.isnan(u) & ~np.isnan(v)
        log(f'  {name} lens {h}: periods {periods[0]:.1f} x {periods[1]:.1f} px, measured region {valid.sum()} px '
            f'(~{valid.sum() / (periods[0] * periods[1]):.0f} cells)')
        views.append(vimg)
        uv.append((u, v))
        valids.append(valid)
    both = valids[0] & valids[1]
    if both.sum() < 2000:
        log(f'  {name}: lenses overlap on only {both.sum()} px of grid, skipped')
        return None
    du = uv[0][0][both] - uv[1][0][both]
    dv = uv[0][1][both] - uv[1][1][both]
    guess = (int(np.round(np.median(du))), int(np.round(np.median(dv))))
    off, scores = lattice_offset(views, uv, valids, guess)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
    log(f'  {name}: overlap {both.sum()} px; phase difference lens0 - lens1 median ({np.median(du):+.3f}, '
        f'{np.median(dv):+.3f}) cells -> guess {guess}; label check picks {off} (NCC {ranked[0][1][0]:.3f}, '
        f'next {ranked[1][0]} {ranked[1][1][0]:.3f})')
    # debug: lattice lines of both lenses on the blended view
    vis = cv2.addWeighted(views[0], 0.5, views[1], 0.5, 0)
    for h, colr in ((0, (0, 0, 255)), (1, (255, 0, 255))):
        uu = uv[h][0] + (off[0] if h == 1 else 0)
        vv = uv[h][1] + (off[1] if h == 1 else 0)
        for a in (uu, vv):
            fl = np.floor(np.nan_to_num(a, nan=-1e9))
            e = np.zeros(a.shape, bool)
            e[:, 1:] |= (fl[:, 1:] != fl[:, :-1]) & valids[h][:, 1:] & valids[h][:, :-1]
            e[1:, :] |= (fl[1:, :] != fl[:-1, :]) & valids[h][1:, :] & valids[h][:-1, :]
            vis[e] = colr
    cv2.imwrite(os.path.join(out_dir, f'lattice_{name}.jpg'), vis)
    obs = []
    for h in (0, 1):
        sel = np.zeros_like(valids[h])
        sel[::sample, ::sample] = True
        ys, xs = np.nonzero(valids[h] & sel)
        d_world = view.dirs(xs.astype(np.float64), ys.astype(np.float64))
        ray = d_world @ Rs[h]
        ij = np.stack([uv[h][0][ys, xs], uv[h][1][ys, xs]], axis=1)
        obs.append((ij, ray))
    return dict(name=name, obs=obs, raw_obs1=obs[1], phase_diff=(float(np.median(du)), float(np.median(dv))),
                guess=guess, label_scores=scores, label_pick=off, overlap=int(both.sum()))


def save_shot(s, path):
    keys = sorted(s['label_scores'])
    np.savez(path, ij0=s['obs'][0][0], r0=s['obs'][0][1], ij1=s['raw_obs1'][0], r1=s['raw_obs1'][1],
             phase_diff=s['phase_diff'], guess=s['guess'], label_pick=s['label_pick'], overlap=s['overlap'],
             score_keys=np.array(keys, int).reshape(-1, 2),
             score_vals=np.array([s['label_scores'][k] for k in keys], float).reshape(-1, 2))


def load_shot(name, path):
    z = np.load(path)
    obs = [(z['ij0'], z['r0']), (z['ij1'], z['r1'])]
    scores = {tuple(int(v) for v in k): (float(a), int(b)) for k, (a, b) in zip(z['score_keys'], z['score_vals'])}
    return dict(name=name, obs=obs, raw_obs1=obs[1], phase_diff=tuple(z['phase_diff']),
                guess=tuple(int(v) for v in z['guess']), label_scores=scores,
                label_pick=tuple(int(v) for v in z['label_pick']), overlap=int(z['overlap']))


def kabsch_rotation(s, off):
    """Closed-form lens-1 rotation for one shot under a lattice offset, ignoring parallax. Lens-0 rays define a
    homography lattice -> direction; lens-1 points inside lens 0's lattice range (no extrapolation) are paired
    with it. Returns (correction rotation vector in deg relative to R_NOMINAL2, median residual deg, n points)."""
    ij0, r0 = s['obs'][0]
    ij1, r1 = s['raw_obs1']
    H = init_H(ij0, r0)
    q1 = ij1 + np.array(off, float)
    lo, hi = np.percentile(ij0, 2, axis=0), np.percentile(ij0, 98, axis=0)
    m = np.all((q1 > lo) & (q1 < hi), axis=1)
    if m.sum() < 30:
        return None, None, int(m.sum())
    q = unit((H @ np.c_[q1[m], np.ones(m.sum())].T).T)
    if np.sum(q * r0.mean(0)) < 0:
        q = -q
    U, _, Vt = np.linalg.svd(q.T @ r1[m])
    R = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt     # q ~ R r1
    err = np.degrees(angle(q, r1[m] @ R.T))
    w, _ = cv2.Rodrigues(ox.R_NOMINAL2.T @ R)
    return np.degrees(w.ravel()), float(np.median(err)), int(m.sum())


def choose_offsets(shots, du_search=2, dv_search=1):
    """Pick each shot's lattice offset so that one lens-1 rotation explains all shots. A wrong offset is absorbed
    by that shot's rotation (about a cell, ~3 deg), around an axis that depends on where the shot looks, so the
    wrong choices disagree with the other shots."""
    cands = []
    for s in shots:
        g = s['guess']
        rows = []
        for du in range(g[0] - du_search, g[0] + du_search + 1):
            for dv in range(g[1] - dv_search, g[1] + dv_search + 1):
                w, med, n = kabsch_rotation(s, (du, dv))
                if w is not None:
                    rows.append(((du, dv), w, med, n))
        cands.append(rows)
    best = None
    for si, rows in enumerate(cands):
        for anchor in rows:
            pick = [min(r2, key=lambda c: np.linalg.norm(c[1] - anchor[1])) for r2 in cands]
            for _ in range(3):                        # re-centre on the consensus
                wc = np.median([c[1] for c in pick], axis=0)
                pick = [min(r2, key=lambda c: np.linalg.norm(c[1] - wc)) for r2 in cands]
            cost = sum(np.linalg.norm(c[1] - wc) for c in pick)
            if best is None or cost < best[0]:
                best = (cost, pick, wc)
    cost, pick, wc = best
    log(f'offset choice by rotation consensus: consensus correction rotvec {np.round(wc, 3)} deg, '
        f'total spread {cost:.3f} deg')
    for s, rows, c in zip(shots, cands, pick):
        others = sorted((np.linalg.norm(r[1] - wc), r[0]) for r in rows if r[0] != c[0])
        label = s['label_scores'].get(c[0], (float('nan'), 0))[0]
        log(f'  {s["name"]}: offset {c[0]} (rotation {np.linalg.norm(c[1] - wc):.3f} deg from consensus, '
            f'kabsch median residual {c[2]:.3f} deg over {c[3]} pts; next {others[0][1]} at {others[0][0]:.3f} deg); '
            f'phase guess {s["guess"]}, label check picked {s["label_pick"]} (label NCC of chosen {label:.3f})')
        for r in rows:
            log(f'      cand {r[0]}: rotvec {np.round(r[1], 3)} deg, |d| {np.linalg.norm(r[1] - wc):.3f}, '
                f'resid {r[2]:.3f}')
    return [c[0] for c in pick]


def apply_offset(s, off):
    ij1, r1 = s['raw_obs1']
    s['obs'] = [s['obs'][0], (ij1 + np.array(off, float), r1)]
    s['offset'] = off
    s['frac'] = (s['phase_diff'][0] - off[0], s['phase_diff'][1] - off[1])


def rodrigues(w):
    R, _ = cv2.Rodrigues(np.asarray(w, np.float64).reshape(3, 1))
    return R


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def angle(a, b):
    return np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1))


def init_H(ij, ray):
    """Fit lattice (i, j) -> lens-0 ray with a homography to the ray's own tangent plane."""
    z = unit(ray.mean(0))
    x = unit(np.cross([0, 1.0, 0] if abs(z[1]) < 0.9 else [1.0, 0, 0], z))
    y = np.cross(z, x)
    B = np.stack([x, y, z])
    c = ray @ B.T
    uv = c[:, :2] / c[:, 2:3]
    Hp, _ = cv2.findHomography(ij.astype(np.float64), uv, 0)
    # direction = B^T @ [u, v, 1] (scaled) = B^T @ Hp @ [i, j, 1]
    return B.T @ Hp


def refine_H(H, hom_ij0, r0, robust_deg):
    """Lens-0-only fit of one shot's homography (good start for the joint fit)."""
    def res(h):
        Hm = h.reshape(3, 3)
        return np.degrees(np.concatenate([(unit((Hm @ hom_ij0.T).T) - r0).ravel(),
                                          np.radians([np.linalg.norm(Hm) - 1.0])]))
    return least_squares(res, H.ravel(), loss='soft_l1', f_scale=robust_deg, x_scale='jac').x.reshape(3, 3)


def solve(shots, robust_deg, fix_c=False, distance=None, fixed_dist=(), dist_sigma=0.1):
    """Joint fit. Lattice coords are normalised per shot (zero mean, unit spread over lens 0) so the homography is
    well conditioned. Residuals are the 3 components of (predicted - observed) unit direction, in degrees: smooth
    at zero, unlike the unsigned angle. Gauges: |H| and |n| held at 1 by a soft penalty.
    Scale: with `distance` (metres), shots named in fixed_dist have their screen distance held at it and the rest get
    a prior distance +- dist_sigma, so c comes out in metres; without it shot 0's distance is held at 1."""
    ns = len(shots)
    if distance is None:
        fixed = {0: 1.0}
        prior = {}
    else:
        fixed = {si: distance for si, s in enumerate(shots) if s['name'] in fixed_dist}
        prior = {si: distance for si in range(ns) if si not in fixed}
        if not fixed:
            sys.exit('--distance needs at least one shot in --fixed-distance to set the scale')
    for s in shots:
        ij0 = s['obs'][0][0]
        s['nrm'] = (ij0.mean(0), ij0.std(0).mean())
    hom = [lambda ij, s=s: np.c_[(ij - s['nrm'][0]) / s['nrm'][1], np.ones(len(ij))] for s in shots]
    # parameters: w (3, lens-2 correction, Rodrigues), c (3), per shot: H (9), n (3), d
    x0 = [np.zeros(3), np.zeros(3)]
    for si, s in enumerate(shots):
        ij0, r0 = s['obs'][0]
        H = init_H(hom[si](ij0)[:, :2], r0)
        H /= np.linalg.norm(H)
        if np.sum((H @ hom[si](ij0).T).T * r0) < 0:         # H @ [i, j, 1] must point along the rays
            H = -H
        H = refine_H(H, hom[si](ij0), r0, robust_deg)
        d0 = fixed.get(si, prior.get(si, 1.0))
        x0 += [H.ravel(), unit(r0.mean(0)), np.array([d0])]
    log(f'  lens-0 homographies refined for {ns} shots')
    x0 = np.concatenate(x0)

    def unpack(x):
        w, c = x[:3], (np.zeros(3) if fix_c else x[3:6])
        per = [(x[k:k + 9].reshape(3, 3), x[k + 9:k + 12], x[k + 12]) for k in range(6, 6 + 13 * ns, 13)]
        return w, c, per

    def predict(x):
        """Per shot: (pred0, obs0, pred1, obs1) unit directions in the lens-0 frame."""
        w, c, per = unpack(x)
        R2 = ox.R_NOMINAL2 @ rodrigues(w)
        out = []
        for si, (s, (H, n, d)) in enumerate(zip(shots, per)):
            ij0, r0 = s['obs'][0]
            ij1, r1 = s['obs'][1]
            p0 = unit((H @ hom[si](ij0).T).T)
            q = unit((H @ hom[si](ij1).T).T)
            dd = fixed.get(si, d)
            X = q * (dd / np.sum(q * unit(n), axis=1))[:, None]
            out.append((p0, r0, unit(X - c), r1 @ R2.T))
        return out

    def residuals(x):
        _, _, per = unpack(x)
        res = []
        for si, ((p0, r0, p1, o1), (H, n, d)) in enumerate(zip(predict(x), per)):
            res += [(p0 - r0).ravel(), (p1 - o1).ravel(),
                    np.radians([np.linalg.norm(H) - 1.0, np.linalg.norm(n) - 1.0])]
            if si in prior:                                  # 1 sigma off the prior costs f_scale (deg units)
                res.append(np.radians([(d - prior[si]) / dist_sigma * robust_deg]))
        return np.degrees(np.concatenate(res))

    def errors(x):
        return [(np.degrees(angle(p0, r0)), np.degrees(angle(p1, o1))) for p0, r0, p1, o1 in predict(x)]

    if fix_c:
        x0 = np.delete(x0, np.s_[3:6])
        full = lambda x: np.insert(x, 3, np.zeros(3))  # noqa: E731
    else:
        full = lambda x: x  # noqa: E731
    t0 = time.time()
    log(f'solving: {sum(len(s["obs"][0][0]) + len(s["obs"][1][0]) for s in shots)} observations, {len(x0)} params'
        f'{" (rotation only)" if fix_c else ""}')
    sol = least_squares(lambda x: residuals(full(x)), x0, loss='soft_l1', f_scale=robust_deg, x_scale='jac',
                        ftol=1e-12, xtol=1e-12, gtol=1e-10, max_nfev=3000, verbose=2)
    log(f'  done in {time.time() - t0:.1f}s, status {sol.status}: {sol.message}; nfev {sol.nfev}, '
        f'optimality {sol.optimality:.3g}')
    x = full(sol.x)
    return sol, unpack(x), errors(x), fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images', nargs='+')
    ap.add_argument('--out', required=True, help='directory for debug images and the report')
    ap.add_argument('--swap', action='store_true', help='JPEG half 0 = OPAX Right')
    ap.add_argument('--robust', type=float, default=0.1, help='soft-L1 scale, degrees')
    ap.add_argument('--no-translation', action='store_true', help='fit rotation only (lens centre fixed at 0)')
    ap.add_argument('--distance', type=float, help='camera-to-screen distance in metres (sets the scale)')
    ap.add_argument('--fixed-distance', default='', metavar='SHOT,SHOT',
                    help='shots taken at exactly --distance (e.g. 360_0375,360_0376); the rest get a prior')
    ap.add_argument('--distance-sigma', type=float, default=0.1, help='prior spread for the other shots, metres')
    ap.add_argument('--redetect', action='store_true', help='ignore cached obs_<shot>.npz detections in --out')
    ap.add_argument('--charuco', metavar='BOARD.json',
                    help='shots show a ChArUco board (utils/make_charuco.py JSON) instead of the line grid')
    ap.add_argument('--detect-only', action='store_true', help='detect and report, no solve (e.g. test shots)')
    ap.add_argument('--offset', action='append', default=[], metavar='SHOT=DU,DV',
                    help='force a shot\'s lattice offset, e.g. 360_0375=12,3 (repeatable)')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    lay = ox.LAYOUTS['jpeg']
    lenses, names = ox.lens_setup(args)
    log(f'using {THREADS} threads of {os.cpu_count()} (GRID_SOLVE_THREADS to change)')
    overrides = {}
    for o in args.offset:
        nm, val = o.split('=')
        overrides[nm] = tuple(int(v) for v in val.split(','))
    spec = det = None
    if args.charuco:
        spec, det = load_charuco(args.charuco)
        log(f'ChArUco board {spec["squares_x"]} x {spec["squares_y"]} ({spec["dictionary"]}), '
            f'{spec["inner_corners"]} corners')
    shots = []
    for k, p in enumerate(args.images, 1):
        name = os.path.splitext(os.path.basename(p))[0]
        cache = os.path.join(args.out, f'obs_{"charuco_" if args.charuco else ""}{name}.npz')
        if os.path.exists(cache) and not args.redetect:
            try:
                shots.append(load_shot(name, cache))
                log(f'=== [{k}/{len(args.images)}] {p}: detection cached in {cache}')
                continue
            except Exception as e:                      # e.g. zero-filled after a hard reset
                log(f'=== [{k}/{len(args.images)}] {p}: cache {cache} unreadable ({e}), detecting again')
        log(f'=== [{k}/{len(args.images)}] {p}')
        if args.charuco:
            s = detect_shot_charuco(p, lenses, lay, args.out, spec, det)
        else:
            s = detect_shot(p, lenses, lay, args.out)
        if s:
            save_shot(s, cache)
            shots.append(s)
    if not shots:
        sys.exit('no usable shots')
    if args.detect_only:
        log(f'--detect-only: {len(shots)} usable shot(s) of {len(args.images)}, no solve')
        return
    offs = [(0, 0)] * len(shots) if args.charuco else choose_offsets(shots)   # ChArUco: matched by corner ID
    for s, off in zip(shots, offs):
        if s['name'] in overrides:
            log(f'  {s["name"]}: offset overridden {off} -> {overrides[s["name"]]}')
            off = overrides[s['name']]
        apply_offset(s, off)
    fixed_names = [v for v in args.fixed_distance.split(',') if v]
    unknown = set(fixed_names) - {s['name'] for s in shots}
    if unknown:
        sys.exit(f'--fixed-distance names not among the shots: {sorted(unknown)}')
    sol, (w, c, per), errs, fixed = solve(shots, args.robust, args.no_translation, args.distance, fixed_names,
                                          args.distance_sigma)
    unit_name = 'm' if args.distance else 'units of shot-0 screen distance'
    dist_unit = ' m' if args.distance else ""
    R = rodrigues(w)
    y, p, r = ox.ypr_from(R)
    print(f'lenses: half0={names[0]} half1={names[1]}; shots used: {len(shots)} of {len(args.images)}; '
          f'{"rotation only" if args.no_translation else "rotation + lens-2 centre"}')
    print(f'lens-2 correction (yaw, pitch, roll) = ({y:+.4f}, {p:+.4f}, {r:+.4f}) deg  -> opax_stitch --rot '
          f'{y:.4f} {p:.4f} {r:.4f}')
    print(f'lens-2 centre in lens-0 frame ({unit_name}): ({c[0]:+.5f}, {c[1]:+.5f}, {c[2]:+.5f}), '
          f'|c| = {np.linalg.norm(c):.5f}')
    for si, (s, (H, n, d), (e0, e1)) in enumerate(zip(shots, per, errs)):
        dd = fixed.get(si, d)
        print(f'  {s["name"]}: lens0 {len(e0)} pts median err {np.median(e0):.3f} deg, lens1 {len(e1)} pts median '
              f'{np.median(e1):.3f} / 90th pct {np.percentile(e1, 90):.3f} deg; plane distance {dd:.3f}{dist_unit}'
              f'{" (fixed)" if si in fixed else ""}; '
              f'offset {s["offset"]}, nominal misalignment ({s["frac"][0]:+.3f}, {s["frac"][1]:+.3f}) cells')


if __name__ == '__main__':
    main()
