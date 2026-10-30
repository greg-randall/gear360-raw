#!/usr/bin/env python3
"""Inspect a headerless Gear 360 dump file and say what it most likely contains.

For each file: value statistics, which low bits are used, per-2x2-phase means (a Bayer mosaic shows
two equal phases, the greens; a demosaiced/luma image shows four equal phases), and a quick-look
PNG (2x2 binned, gamma 2.2, per-file stretch). Optionally correlates the quick look against each
half of a camera JPEG to find which lens and which crop it is.

Usage: python3 tools/inspect_dump.py FILE.raw [...] --width 2912 --height 2896 [--jpeg 360_NNNN.JPG] --out DIR
"""
import argparse
import os
import sys

import cv2
import numpy as np


def load(path, width, height):
    data = np.fromfile(path, dtype="<u2")
    if data.size != width * height:
        sys.exit(f"{path}: {data.size} words, expected {width}x{height} = {width * height}")
    return data.reshape(height, width)


def describe(img):
    flat = img.ravel()
    lines = [f"min {flat.min()}  max {flat.max()}  mean {flat.mean():.1f}  median {np.median(flat):.0f}"]
    used = 0
    for v in np.unique(flat[::97]):
        used |= int(v)
    low = (used & -used).bit_length() - 1 if used else "all"
    lines.append(f"bits used (sampled OR): 0x{used:04x}  -> low zero bits: {low}")
    pct = np.percentile(flat, [0.1, 1, 5, 50, 95, 99, 99.9])
    lines.append("percentiles 0.1/1/5/50/95/99/99.9: " + " ".join(f"{p:.0f}" for p in pct))
    # 2x2 phase means over the central region (inside the image circle).
    h, w = img.shape
    c = img[h // 4:3 * h // 4, w // 4:3 * w // 4].astype(np.float64)
    ph = {f"({y},{x})": c[y::2, x::2].mean() for y in (0, 1) for x in (0, 1)}
    lines.append("2x2 phase means (centre): " + "  ".join(f"{k} {v:.1f}" for k, v in ph.items()))
    # Neighbour differences: a mosaic has large same-row neighbour differences relative to 2-px steps.
    d1 = np.abs(np.diff(c[:, ::1], axis=1)).mean()
    d2 = np.abs(c[:, 2:] - c[:, :-2]).mean()
    lines.append(f"mean |x+1 - x| {d1:.1f}   mean |x+2 - x| {d2:.1f}   ratio {d1 / max(d2, 1e-9):.2f} "
                 "(>1 suggests a colour mosaic, ~0.6-0.8 a smooth single-channel image)")
    return lines


def quicklook(img):
    h, w = img.shape
    b = img[:h - h % 2, :w - w % 2].astype(np.float32)
    b = (b[0::2, 0::2] + b[0::2, 1::2] + b[1::2, 0::2] + b[1::2, 1::2]) / 4
    lo, hi = np.percentile(b, [0.5, 99.8])
    v = np.clip((b - lo) / max(hi - lo, 1), 0, 1) ** (1 / 2.2)
    return (v * 255).astype(np.uint8)


def match_jpeg(ql, jpeg_path):
    """Normalised cross-correlation of the quick look against each JPEG half (resized to match)."""
    j = cv2.imread(jpeg_path, cv2.IMREAD_GRAYSCALE)
    if j is None:
        return [f"could not read {jpeg_path}"]
    half = j.shape[1] // 2
    out = []
    for k in (0, 1):
        sq = j[:, k * half:(k + 1) * half]
        sq = cv2.resize(sq, (ql.shape[1], ql.shape[0]), interpolation=cv2.INTER_AREA)
        for flip_name, cand in (("as is", ql), ("flipped LR", ql[:, ::-1]), ("flipped UD", ql[::-1]),
                                ("rot180", ql[::-1, ::-1])):
            a = cand.astype(np.float32) - cand.mean()
            b = sq.astype(np.float32) - sq.mean()
            r = float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
            out.append((r, f"JPEG half {k}, {flip_name}: corr {r:.3f}"))
    out.sort(reverse=True)
    return [s for _, s in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", nargs="+")
    ap.add_argument("--width", type=int, default=2912, help="pixels per row (stride in 16-bit words)")
    ap.add_argument("--height", type=int, default=2896)
    ap.add_argument("--jpeg", help="camera JPEG to compare against")
    ap.add_argument("--out", required=True, help="directory for quick-look PNGs")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for k, path in enumerate(args.raw, 1):
        print(f"=== [{k}/{len(args.raw)}] {path}", flush=True)
        img = load(path, args.width, args.height)
        for line in describe(img):
            print("  " + line)
        ql = quicklook(img)
        png = os.path.join(args.out, os.path.splitext(os.path.basename(path))[0] + "_quicklook.png")
        cv2.imwrite(png, ql)
        print(f"  quick look: {png}")
        if args.jpeg:
            for line in match_jpeg(ql, args.jpeg):
                print("  " + line)


if __name__ == "__main__":
    main()
