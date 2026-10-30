#!/usr/bin/env python3
"""Pool ChArUco corner matches from many shots into one PTGui project (one lens-1/lens-2 image pair).

Each corner seen by both lenses in any shot becomes one control point. The relation between the two lenses is the same
in every shot, so the pairs can all go on a single image pair; PTGui then fits one lens model and one lens-2 rotation
to all of them, and the result is saved as a template to apply to any raw. All pairs come from the shots' distance
(5 ft for 2026-10-12), so the template is exact for that distance; nearer objects will show some seam parallax.

Corners come from tools/grid_solve.py --charuco detection caches (obs_charuco_<shot>.npz, rays in each lens frame);
each is mapped back to DNG (raw layout, 5824x2896) pixels with the same lens model that produced it, so the model
cancels: the DNG position is the JPEG position plus the measured raw offset (opax_stitch RAW_OFFSET).

The project is built from an existing PTGui project used as a template (lens, layout, settings kept); its control
points are replaced, both images are pointed at --image, and it is marked not optimised.

Usage:
  python3 tools/charuco_to_pts.py 360_0383 360_0384 ... 360_0390 --cache-dir calibration/charuco_test \\
      --template "captures/2026-10-11/360_0376 Panorama.pts" --image 360_0384.dng \\
      --out "captures/2026-10-12-charuco/charuco_pooled.pts"
"""
import argparse
import copy
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opax_stitch as ox  # noqa: E402


def shared_pairs(path):
    """Rays of the corners seen by both lenses, matched by board position (= corner ID)."""
    z = np.load(path)
    k0 = {tuple(v): i for i, v in enumerate(np.rint(z['ij0']).astype(int))}
    pairs = [(k0[tuple(v)], j) for j, v in enumerate(np.rint(z['ij1']).astype(int)) if tuple(v) in k0]
    if not pairs:
        return np.zeros((0, 3)), np.zeros((0, 3))
    i0, i1 = np.array(pairs).T
    return z['r0'][i0], z['r1'][i1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('shots', nargs='+', help='shot names, e.g. 360_0384')
    ap.add_argument('--cache-dir', required=True, help='directory with obs_charuco_<shot>.npz')
    ap.add_argument('--template', required=True, help='existing PTGui project (.pts) with this camera set up')
    ap.add_argument('--image', required=True, help='DNG both images point at (path relative to --out\'s folder)')
    ap.add_argument('--out', required=True, help='project to write')
    ap.add_argument('--swap', action='store_true', help='file half 0 = OPAX Right')
    ap.add_argument('--decimals', type=int, default=0,
                    help='decimal places for control-point pixels; PTGui 12 rejects fractions ("not a number"), '
                         'so 0 (rounding costs <= 0.5 px, ~0.03 deg at the seam)')
    args = ap.parse_args()

    lay = ox.LAYOUTS['raw']
    lenses, names = ox.lens_setup(args)
    proj = json.load(open(args.template, encoding='utf-8'))
    p = proj['project']
    groups = p['imagegroups']
    if len(groups) != 2:
        sys.exit(f'template must have 2 image groups (one per lens), found {len(groups)}')
    # which template image is which file half (crop-centre offset: negative long side = left half)
    gl = p['globallenses'][0]['lens']['params']['cropcenteroffset']['longside']
    halves = [0 if (g['individualcropcenter']['longside'] if g['individualcropcenter'] else gl) < 0 else 1
              for g in groups]
    if sorted(halves) != [0, 1]:
        sys.exit(f'could not tell the template images apart from their crop centres: {halves}')
    img_of_half = {h: i for i, h in enumerate(halves)}
    print(f'template {args.template}: image {img_of_half[0]} = file half 0 ({names[0]}), '
          f'image {img_of_half[1]} = file half 1 ({names[1]})')

    cps, per_shot = [], []
    for shot in args.shots:
        path = os.path.join(args.cache_dir, f'obs_charuco_{shot}.npz')
        if not os.path.exists(path):
            sys.exit(f'no detection cache {path}; run grid_solve.py --charuco --detect-only on the shot first')
        r0, r1 = shared_pairs(path)
        xy = []
        for h, r in ((0, r0), (1, r1)):
            col, row, ok = ox.lens_ray_to_px(r, lenses[h], lay, h)
            if not ok.all():
                sys.exit(f'{shot}: {int((~ok).sum())} corners fall outside lens {h}\'s model range')
            # round-trip check: back to rays with the inverse mapping
            back = ox.px_to_lens_ray(col, row, lenses[h], lay, h)
            err = np.degrees(np.arccos(np.clip(np.sum(back * r, axis=1), -1, 1)))
            if len(err) and err.max() > 1e-3:
                sys.exit(f'{shot} lens {h}: pixel round trip off by {err.max():.4f} deg')
            xy.append(np.stack([col, row], axis=1))

        def px(v):
            return int(round(float(v))) if args.decimals == 0 else round(float(v), args.decimals)
        for (x0, y0), (x1, y1) in zip(*xy):
            a = [img_of_half[0], 0, px(x0), px(y0)]
            b = [img_of_half[1], 0, px(x1), px(y1)]
            cps.append({'t': 0, '0': a, '1': b} if a[0] == 0 else {'t': 0, '0': b, '1': a})
        per_shot.append((shot, len(r0)))
        if len(r0):
            print(f'  {shot}: {len(r0)} pairs; DNG x {xy[0][:, 0].min():.0f}..{xy[0][:, 0].max():.0f} | '
                  f'{xy[1][:, 0].min():.0f}..{xy[1][:, 0].max():.0f}, y {min(xy[0][:, 1].min(), xy[1][:, 1].min()):.0f}'
                  f'..{max(xy[0][:, 1].max(), xy[1][:, 1].max()):.0f}')
        else:
            print(f'  {shot}: 0 pairs')
    print(f'{len(cps)} control points from {len(args.shots)} shots')

    out = copy.deepcopy(proj)
    q = out['project']
    q['controlpoints'] = cps
    q['hasbeenoptimized'] = False
    out_dir = os.path.dirname(os.path.abspath(args.out))
    dng = os.path.join(out_dir, args.image)
    st = os.stat(dng) if os.path.exists(dng) else None
    if st is None:
        print(f'note: {dng} does not exist yet; make it before opening the project')
    for g in q['imagegroups']:
        for im in g['images']:
            im['filename'] = args.image
            if st is not None:
                im['metadata']['filesize'] = st.st_size
                im['metadata']['filetimestamp'] = int(st.st_mtime)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent='\t')
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
