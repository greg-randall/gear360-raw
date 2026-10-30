#!/usr/bin/env python3
"""Make a ChArUco calibration board to display on the projector at the Gear 360 lens seam.

A chessboard whose white squares each hold a unique ArUco marker, so every inner corner has an ID and the two lenses'
views match by ID (no lattice-offset ambiguity, unlike the line grid from make_grid.sh). Generated with OpenCV's own
cv2.aruco.CharucoBoard; the board definition is written next to the image as JSON so detection uses the same settings.

Defaults: 1920x1080 screen, 16 x 9 squares of 120 px (120 inner corners), markers 70% of a square, DICT_4X4_250.
A square size that does not divide the screen leaves a centred black margin (e.g. 96 px -> 20 x 11, 12 px top/bottom).
Writes a white-on-black and a green-on-black version (green: the sensor's sharpest channel).

Usage: python3 utils/make_charuco.py [--out-dir utils] [--square 120] [--self-test]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out-dir', default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--width', type=int, default=1920)
    ap.add_argument('--height', type=int, default=1080)
    ap.add_argument('--square', type=int, default=120, help='square size in screen px')
    ap.add_argument('--marker-frac', type=float, default=0.7, help='marker size as a fraction of the square')
    ap.add_argument('--dict', default='DICT_4X4_250', help='cv2.aruco predefined dictionary name')
    ap.add_argument('--self-test', action='store_true', help='detect the board in the generated image')
    args = ap.parse_args()

    nx, ny = args.width // args.square, args.height // args.square
    bw, bh = nx * args.square, ny * args.square            # board size; centred, leftover is a black margin
    mx, my = (args.width - bw) // 2, (args.height - bh) // 2
    marker = int(round(args.square * args.marker_frac))
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dict))
    n_markers = (nx * ny) // 2
    if n_markers > dictionary.bytesList.shape[0]:
        sys.exit(f'{n_markers} markers needed, {args.dict} has {dictionary.bytesList.shape[0]}')
    board = cv2.aruco.CharucoBoard((nx, ny), float(args.square), float(marker), dictionary)
    img = np.zeros((args.height, args.width), np.uint8)
    img[my:my + bh, mx:mx + bw] = board.generateImage((bw, bh), marginSize=0, borderBits=1)

    os.makedirs(args.out_dir, exist_ok=True)
    stem = f'charuco_{args.width}x{args.height}_{nx}x{ny}'
    white = os.path.join(args.out_dir, f'{stem}_white.png')
    green = os.path.join(args.out_dir, f'{stem}_green.png')
    cv2.imwrite(white, img)
    g = np.zeros((args.height, args.width, 3), np.uint8)
    g[..., 1] = img                                     # BGR: green channel only
    cv2.imwrite(green, g)
    spec = dict(squares_x=nx, squares_y=ny, square_px=args.square, marker_px=marker, dictionary=args.dict,
                legacy_pattern=bool(board.getLegacyPattern()), width=args.width, height=args.height,
                board_origin_px=[mx, my],
                inner_corners=(nx - 1) * (ny - 1), markers=n_markers, opencv=cv2.__version__)
    spec_path = os.path.join(args.out_dir, f'{stem}.json')
    with open(spec_path, 'w') as f:
        json.dump(spec, f, indent=1)
    print(f'wrote {white}\nwrote {green}\nwrote {spec_path}')
    print(f'{nx} x {ny} squares of {args.square} px, markers {marker} px ({args.dict}), '
          f'{spec["inner_corners"]} inner corners, {n_markers} markers')

    if args.self_test:
        det = cv2.aruco.CharucoDetector(board)
        for path in (white, green):
            im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            corners, ids, mcorners, mids = det.detectBoard(im)
            nc = 0 if ids is None else len(ids)
            nm = 0 if mids is None else len(mids)
            print(f'self-test {os.path.basename(path)}: {nm}/{n_markers} markers, '
                  f'{nc}/{spec["inner_corners"]} corners')


if __name__ == '__main__':
    main()
