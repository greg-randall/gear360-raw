#!/usr/bin/env python3
"""Score lens-2 rotations on a PTGui project's control points, using the camera's own lens model (OPAX).

The control points (e.g. placed by hand on projected-grid vertices) are mapped to rays with opax_stitch's lens model,
so PTGui's own lens fit (focal length, a/b/c distortion, shift) plays no part. Reports, as seam error in degrees:
  - nominal 180 deg rotation, no correction;
  - the best rotation for these points alone (closed form, Kabsch; parallax ignored, like PTGui);
  - PTGui's own image-2 yaw/pitch/roll under each sign convention, to find which one maps onto opax --rot;
  - any extra --rot candidates given (e.g. grid_solve results).
All corrections are printed in opax_stitch --rot terms: world = R_NOMINAL2 @ rot(yaw, pitch, roll) @ lens-2 ray.

Usage:
  python3 tools/ptgui_check.py "captures/2026-10-11/360_0376 Panorama.pts" \\
      --rot run4 -0.7778 -1.2227 0.3448 --rot run6 -0.5532 -0.7378 0.3169
"""
import argparse
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opax_stitch as ox  # noqa: E402


def angle_deg(a, b):
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1)))


def kabsch(a, b):
    """R minimising sum |a - R b| over unit rows."""
    U, _, Vt = np.linalg.svd(a.T @ b)
    return U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pts', help='PTGui project (.pts, JSON)')
    ap.add_argument('--layout', default='raw', choices=list(ox.LAYOUTS),
                    help='pixel layout of the images PTGui used (DNG 5824x2896 = raw)')
    ap.add_argument('--swap', action='store_true', help='file half 0 = OPAX Right')
    ap.add_argument('--rot', nargs=4, action='append', default=[], metavar=('NAME', 'YAW', 'PITCH', 'ROLL'),
                    help='extra opax --rot correction to score (repeatable)')
    args = ap.parse_args()

    p = json.load(open(args.pts, encoding='utf-8'))['project']
    groups = p['imagegroups']
    if len(groups) != 2:
        sys.exit(f'expected 2 image groups (one per lens), found {len(groups)}')
    pos = [g['position']['params'] for g in groups]
    lay = ox.LAYOUTS[args.layout]
    lenses, names = ox.lens_setup(args)

    # which file half each PTGui image is: its crop centre offset (negative long side = left half)
    gl = p['globallenses'][0]['lens']['params']['cropcenteroffset']['longside']
    halves = []
    for g in groups:
        cc = g['individualcropcenter']['longside'] if g['individualcropcenter'] else gl
        halves.append(0 if cc < 0 else 1)
    if sorted(halves) != [0, 1]:
        sys.exit(f'could not tell the two lenses apart from crop centres: {halves}')
    print(f'PTGui image 0 = file half {halves[0]} ({names[halves[0]]}), image 1 = file half {halves[1]} '
          f'({names[halves[1]]}); layout {args.layout}')
    for k, q in enumerate(pos):
        print(f'  PTGui image {k}: yaw {q["yaw"]:+.4f} pitch {q["pitch"]:+.4f} roll {q["roll"]:+.4f}')

    pts = {0: [], 1: []}
    for cp in p['controlpoints']:
        if cp.get('t', 0) != 0:
            continue
        a, b = cp['0'], cp['1']
        for img_idx, xy in ((a[0], a[2:]), (b[0], b[2:])):
            pts[halves[img_idx]].append(xy)
    r = []
    for h in (0, 1):
        xy = np.array(pts[h], float)
        r.append(ox.px_to_lens_ray(xy[:, 0], xy[:, 1], lenses[h], lay, h))
    r0, r1 = r
    print(f'{len(r0)} control-point pairs (normal type only)')
    off_axis = np.degrees(np.arccos(np.clip(r0[:, 2], -1, 1)))
    print(f'  lens-0 angle off axis: {off_axis.min():.1f} .. {off_axis.max():.1f} deg (seam = 90)')

    def score(Rcorr):
        e = angle_deg(r0, (ox.R_NOMINAL2 @ Rcorr @ r1.T).T)
        return np.median(e), np.percentile(e, 90), e.max()

    rows = [('nominal (no correction)', np.eye(3))]
    Rk = ox.R_NOMINAL2.T @ kabsch(r0, r1)
    rows.append(('best for these points (Kabsch)', Rk))
    # PTGui's correction relative to its image 0, in world axes; try every sign mapping onto opax's axes
    dy = (pos[1]['yaw'] - pos[0]['yaw'] + 180) % 360 - 180
    dy = dy - 180 if dy > 0 else dy + 180          # remove the 180 deg back-to-back turn
    dp = pos[1]['pitch'] - pos[0]['pitch']
    dr = pos[1]['roll'] - pos[0]['roll']
    print(f'PTGui correction beyond 180 deg (its axes): yaw {dy:+.4f} pitch {dp:+.4f} roll {dr:+.4f}')
    for sy, sp, sr in itertools.product((1, -1), repeat=3):
        Rw = ox.rot(sy * dy, sp * dp, sr * dr)                 # world-frame correction
        rows.append((f'PTGui, world signs ({sy:+d},{sp:+d},{sr:+d})', ox.R_NOMINAL2.T @ Rw @ ox.R_NOMINAL2))
    for name, y, pi, ro in args.rot:
        rows.append((name, ox.rot(float(y), float(pi), float(ro))))

    print(f'\n{"rotation":40s} {"--rot yaw":>10s} {"pitch":>8s} {"roll":>8s}   seam error deg: median  90th   max')
    for name, R in rows:
        y, pi, ro = ox.ypr_from(R)
        med, p90, mx = score(R)
        print(f'{name:40s} {y:+10.4f} {pi:+8.4f} {ro:+8.4f}   {med:20.3f} {p90:6.3f} {mx:6.3f}')


if __name__ == '__main__':
    main()
