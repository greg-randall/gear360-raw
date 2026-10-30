#!/usr/bin/env python3
"""Measure how the camera JPEG's lens squares sit inside the raw dump, and fit the fisheye image circles.

The JPEG is 5792x2896 (two 2896x2896 lens squares); the raw dump is 5824x2896 (two 2912x2896 halves).
OPAX (the factory lens calibration) is in 2896-px lens-square coordinates, so to use it on raw/DNG files
we need the offset of each JPEG square inside the raw. This script:

  1. registers each JPEG half against each raw half (both at half resolution) with OpenCV ECC (affine),
     reporting translation, scale and rotation in full-resolution raw pixels, and which raw half matches
     which JPEG half;
  2. fits a circle (scikit-image CircleModel + RANSAC) to the edge of the bright image circle in each
     JPEG half and raw half, for comparison with OPAX Left/Right CenterX/Y and Radius.

Inputs per pair: the camera JPEG and a half-size demosaiced TIFF of the raw (as made by raw2dng.py / dcraw -h,
2912x1448). Usage:
  python3 tools/raw_jpeg_geometry.py JPEG TIFF [JPEG TIFF ...]
"""
import argparse
import sys
import time

import cv2
import numpy as np
from skimage.measure import CircleModel, ransac

OPAX = {  # rec index: value, from calibration/makernote_0x0012_opax.bin (2896-px lens-square coordinates)
    'LeftCenterX': 1444.655517578125, 'LeftCenterY': 1446.1207275390625,
    'RightCenterX': 1444.0599365234375, 'RightCenterY': 1447.00830078125,
    'LeftRadius': 1444.302978515625, 'RightRadius': 1440.99169921875,
}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def to_gray_float(img):
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    img = img.astype(np.float32)
    return img / max(float(img.max()), 1.0)


def edge_image(gray):
    """Tone-insensitive image for registration: log, blur, gradient magnitude."""
    g = np.log1p(gray * 1000.0)
    g = cv2.GaussianBlur(g, (0, 0), 1.5)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    m = cv2.magnitude(gx, gy)
    return m / max(float(m.max()), 1e-6)


def register(jpeg_half, raw_half, dx0):
    """ECC affine: find W so that raw_half(W * [x, y, 1]) ~ jpeg_half(x, y). Returns (W, correlation)."""
    W = np.array([[1, 0, dx0], [0, 1, 0]], np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7)
    # template = jpeg half, input = raw half (raw is wider; ECC warps the input onto the template grid)
    tmpl = edge_image(jpeg_half)
    inp = edge_image(raw_half)
    cc, W = cv2.findTransformECC(tmpl, inp, W, cv2.MOTION_AFFINE, crit, None, 5)
    return W, cc


def fit_circle(gray, label):
    """Fit the bright image circle: threshold, take the outer edge along rays from the centroid, RANSAC circle."""
    g = cv2.GaussianBlur(gray, (0, 0), 2)
    # outside the image circle is near-black; threshold relative to the dark corners
    h, w = g.shape
    corners = np.concatenate([g[:h // 20, :w // 20].ravel(), g[:h // 20, -w // 20:].ravel(),
                              g[-h // 20:, :w // 20].ravel(), g[-h // 20:, -w // 20:].ravel()])
    dark = float(np.percentile(corners, 99))
    inside = g[h // 3:2 * h // 3, w // 3:2 * w // 3]
    bright = float(np.median(inside))
    thr = dark + 0.15 * (bright - dark)
    mask = g > thr
    ys, xs = np.nonzero(mask)
    cx0, cy0 = xs.mean(), ys.mean()
    pts = []
    rmax = int(np.hypot(w, h) / 2)
    for ang in np.linspace(0, 2 * np.pi, 720, endpoint=False):
        dx, dy = np.cos(ang), np.sin(ang)
        rs = np.arange(int(min(w, h) * 0.3), rmax)
        xx = np.round(cx0 + rs * dx).astype(int)
        yy = np.round(cy0 + rs * dy).astype(int)
        ok = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
        if not ok.any():
            continue
        rs, xx, yy = rs[ok], xx[ok], yy[ok]
        vals = mask[yy, xx]
        # outermost inside->outside transition along the ray
        trans = np.nonzero(vals[:-1] & ~vals[1:])[0]
        if len(trans) == 0:
            continue
        i = trans[-1]
        if xx[i] <= 1 or yy[i] <= 1 or xx[i] >= w - 2 or yy[i] >= h - 2:
            continue  # clipped by the frame edge: not the circle
        pts.append((cx0 + (rs[i] + 0.5) * dx, cy0 + (rs[i] + 0.5) * dy))
    pts = np.array(pts)
    if len(pts) < 20:
        log(f'  {label}: only {len(pts)} edge points; circle fit skipped')
        return None
    model, inliers = ransac(pts, CircleModel, min_samples=3, residual_threshold=2.0, max_trials=2000)
    cx, cy, r = model.params
    resid = np.abs(np.hypot(pts[inliers, 0] - cx, pts[inliers, 1] - cy) - r)
    return dict(cx=cx, cy=cy, r=r, n=len(pts), inliers=int(inliers.sum()), rms=float(np.sqrt((resid ** 2).mean())),
                thr=thr, dark=dark, bright=bright)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pairs', nargs='+', help='JPEG TIFF [JPEG TIFF ...]')
    args = ap.parse_args()
    if len(args.pairs) % 2:
        sys.exit('give JPEG TIFF pairs')
    pairs = list(zip(args.pairs[0::2], args.pairs[1::2]))
    for n, (jp, tf) in enumerate(pairs, 1):
        t0 = time.time()
        log(f'[{n}/{len(pairs)}] {jp}  vs  {tf}')
        J = cv2.imread(jp, cv2.IMREAD_UNCHANGED)
        R = cv2.imread(tf, cv2.IMREAD_UNCHANGED)
        if J is None or R is None:
            sys.exit(f'could not read {jp if J is None else tf}')
        log(f'  JPEG {J.shape}, TIFF {R.shape} {R.dtype}')
        jg = to_gray_float(cv2.resize(J, (J.shape[1] // 2, J.shape[0] // 2), interpolation=cv2.INTER_AREA))
        rg = to_gray_float(R)
        jw = jg.shape[1] // 2   # 1448 (half-res JPEG lens square)
        rw = rg.shape[1] // 2   # 1456 (half-res raw half)
        jh = [jg[:, :jw], jg[:, jw:]]
        rh = [rg[:, :rw], rg[:, rw:]]
        print(f'\n## {jp}  <->  {tf}')
        print('registration (full-res raw px; maps JPEG-square pixel (x, y) to raw-half pixel):')
        for ji in range(2):
            for ri in range(2):
                try:
                    W, cc = register(jh[ji], rh[ri], dx0=(rw - jw) / 2)
                except cv2.error as e:
                    print(f'  JPEG half {ji} vs raw half {ri}: ECC failed ({str(e).splitlines()[-1][:80]})')
                    continue
                # half-res affine -> full-res: x_full = 2 x_half + 0.5 convention cancels for the linear part;
                # translation: t_full = 2 t_half + 0.5 (A - I) * ... ~ 2 t_half (A ~ I)
                A = W[:, :2]
                t = W[:, 2] * 2
                sx, sy = np.hypot(A[0, 0], A[1, 0]), np.hypot(A[0, 1], A[1, 1])
                rot = np.degrees(np.arctan2(A[1, 0], A[0, 0]))
                print(f'  JPEG half {ji} vs raw half {ri}: corr {cc:.4f}  dx {t[0]:+8.3f}  dy {t[1]:+8.3f}  '
                      f'scale x {sx:.5f} y {sy:.5f}  rot {rot:+.4f} deg')
        print('circle fits (full-res px, each in its own half: JPEG square 2896 wide, raw half 2912 wide):')
        for name, halves in (('JPEG', jh), ('raw', rh)):
            for i, img in enumerate(halves):
                c = fit_circle(img, f'{name} half {i}')
                if c:
                    print(f'  {name} half {i}: cx {2 * c["cx"] + 0.5:8.2f}  cy {2 * c["cy"] + 0.5:8.2f}  '
                          f'r {2 * c["r"]:8.2f}  (edge pts {c["n"]}, inliers {c["inliers"]}, '
                          f'rms {2 * c["rms"]:.2f} px)')
        print('OPAX (JPEG-square px): Left  cx {LeftCenterX:.2f} cy {LeftCenterY:.2f} '
              'r {LeftRadius:.2f}'.format(**OPAX))
        print('                       Right cx {RightCenterX:.2f} cy {RightCenterY:.2f} '
              'r {RightRadius:.2f}'.format(**OPAX))
        log(f'  done in {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
