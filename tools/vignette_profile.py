#!/usr/bin/env python3
"""Estimate the brightness fall-off (vignetting) of each Gear 360 lens from a pile of ordinary camera JPEGs.

For every JPEG and each lens half, pixels are binned by angle off the optical axis (exact lens model and OPAX
centre from opax_stitch.py); the per-bin median of linearised (sRGB -> linear) R, G, B is divided by the median
of the central 0-15 deg. The per-image profiles are then combined with a median across images, so scene content
(ceiling vs floor, windows) averages out. Images that are mostly dark or clipped are skipped and reported.

This measures what is left in the camera JPEG after the camera's own lens-shading correction (if any).

Usage:
  python3 tools/vignette_profile.py OUT_PREFIX JPEG [JPEG ...]
Writes OUT_PREFIX.csv (angle, per-lens per-channel relative brightness, image count) and OUT_PREFIX.png (plot).
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opax_stitch import OPAX, SQ, theta_of_rho  # noqa: E402

BIN = 1.0      # degrees
MAX_DEG = 96


def srgb_to_linear(x):
    x = x / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def angle_map(L, size, scale):
    """Off-axis angle (deg) for every pixel of a lens square downsampled by `scale`."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xs + 0.5) / scale - 0.5 - L['xc']
    w = (ys + 0.5) / scale - 0.5 - L['yc']
    det = L['c'] - L['d'] * L['e']
    a = (u - L['d'] * w) / det
    b = (L['c'] * w - L['e'] * u) / det
    rho = np.hypot(a, b)
    return np.degrees(theta_of_rho(rho) + np.pi / 2), rho


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out_prefix')
    ap.add_argument('jpegs', nargs='+')
    ap.add_argument('--scale', type=float, default=0.25, help='downsample factor for speed (default 0.25)')
    ap.add_argument('--swap', action='store_true', help='JPEG half 0 = OPAX Right')
    args = ap.parse_args()
    names = ('Right', 'Left') if args.swap else ('Left', 'Right')
    size = int(round(SQ * args.scale))
    edges = np.arange(0, MAX_DEG + BIN, BIN)
    nb = len(edges) - 1
    maps = []
    for nm in names:
        ang, rho = angle_map(OPAX[nm], size, args.scale)
        inside = rho <= OPAX[nm]['radius'] - 10
        maps.append((np.digitize(ang, edges) - 1, inside))
    profiles = [[], []]
    t0 = time.time()
    for k, path in enumerate(args.jpegs, 1):
        img = cv2.imread(path)
        if img is None or img.shape[:2] != (int(SQ), int(2 * SQ)):
            print(f'[{k}/{len(args.jpegs)}] skip {path}: not a 5792x2896 camera JPEG', file=sys.stderr, flush=True)
            continue
        small = cv2.resize(img, (2 * size, size), interpolation=cv2.INTER_AREA)
        used = []
        for i in range(2):
            half = small[:, i * size:(i + 1) * size].astype(np.float64)
            lin = srgb_to_linear(half)
            idx, inside = maps[i]
            ok = inside & (half.max(axis=2) < 250) & (half.min(axis=2) > 3)
            if ok.mean() < 0.5:
                used.append(f'lens{i} skipped ({ok.mean():.0%} usable)')
                continue
            prof = np.full((nb, 3), np.nan)
            for b in range(nb):
                m = ok & (idx == b)
                if m.sum() >= 50:
                    prof[b] = np.median(lin[m], axis=0)
            centre = np.nanmedian(prof[:15], axis=0)
            if not np.all(centre > 0):
                used.append(f'lens{i} skipped (dark centre)')
                continue
            profiles[i].append(prof / centre)
            used.append(f'lens{i} ok')
        print(f'[{k}/{len(args.jpegs)}] {os.path.basename(path)}: {", ".join(used)}  ({time.time() - t0:.0f}s)',
              file=sys.stderr, flush=True)
    if not profiles[0] and not profiles[1]:
        sys.exit('no usable images')
    centres = (edges[:-1] + edges[1:]) / 2
    rows = ['angle_deg,' + ','.join(f'{names[i]}_{c}' for i in range(2) for c in 'BGR') + ',n_left,n_right']
    agg = []
    for i in range(2):
        p = np.array(profiles[i]) if profiles[i] else np.full((1, nb, 3), np.nan)
        agg.append((np.nanmedian(p, axis=0), np.sum(~np.isnan(p[..., 1]), axis=0)))
    for b in range(nb):
        vals = [f'{agg[i][0][b, c]:.4f}' for i in range(2) for c in range(3)]
        rows.append(f'{centres[b]:.1f},' + ','.join(vals) + f',{agg[0][1][b]},{agg[1][1][b]}')
    open(args.out_prefix + '.csv', 'w').write('\n'.join(rows) + '\n')
    print(f'wrote {args.out_prefix}.csv ({len(profiles[0])} / {len(profiles[1])} lens profiles used)')
    for a in (30, 60, 75, 85, 90, 93):
        b = int(a / BIN)
        print(f'  {a:3d} deg: ' + '  '.join(
            f'{names[i]} G {agg[i][0][b, 1]:.3f} (B/G {agg[i][0][b, 0] / agg[i][0][b, 1]:.3f}, '
            f'R/G {agg[i][0][b, 2] / agg[i][0][b, 1]:.3f})' for i in range(2)))
    # plot
    H, W = 500, 900
    plot = np.full((H, W, 3), 255, np.uint8)
    ymax = max(1.0, float(np.nanmax([np.nanmax(a[0]) for a in agg])))
    ymax = float(np.ceil(ymax * 4) / 4)   # y axis runs 0..ymax, so values above 1 stay on the chart
    for yv in np.arange(0.25, ymax + 1e-6, 0.25 if ymax <= 2 else 0.5):
        y = int(H - 30 - yv / ymax * (H - 60))
        cv2.line(plot, (40, y), (W - 10, y), (220, 220, 220), 1)
        cv2.putText(plot, f'{yv:.2f}', (2, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    for a in range(0, MAX_DEG + 1, 15):
        x = int(40 + a / MAX_DEG * (W - 50))
        cv2.line(plot, (x, 30), (x, H - 30), (230, 230, 230), 1)
        cv2.putText(plot, str(a), (x - 8, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    colours = [(255, 0, 0), (0, 160, 0), (0, 0, 255)]
    for i, style in ((0, 2), (1, 1)):
        for c in range(3):
            pts = [(int(40 + centres[b] / MAX_DEG * (W - 50)), int(H - 30 - agg[i][0][b, c] / ymax * (H - 60)))
                   for b in range(nb) if not np.isnan(agg[i][0][b, c])]
            for p, q in zip(pts, pts[1:]):
                cv2.line(plot, p, q, colours[c], style)
    cv2.putText(plot, f'relative brightness vs off-axis angle (thick: {names[0]}, thin: {names[1]})', (40, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.imwrite(args.out_prefix + '.png', plot)
    print(f'wrote {args.out_prefix}.png')


if __name__ == '__main__':
    main()
