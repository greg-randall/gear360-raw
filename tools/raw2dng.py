#!/usr/bin/env python3
"""Wrap a Gear 360 headerless Bayer dump in a DNG using PiDNG.

The camera's `st cap seq dump on ssif` writes files like
`0_0_11648_5824x2896_bayer_12-16.raw`: little-endian uint16, no header,
12-bit data in 16-bit words. This script only adds DNG tags around the data;
demosaicing is left to dcraw / darktable / Adobe Camera Raw.

Defaults are the values measured for the SM-R210 (see docs/lab-notebook.md, "RAW test 2"):
GRBG pattern, 12-bit data high-aligned in 16-bit words, black 4096, white 65472.
Use `--pattern all` to write one DNG per Bayer pattern for comparison.

Colour (default `--colour camera`): ColorMatrix1 (illuminant A) and ColorMatrix2 (D65) are derived from
the camera's own colour-correction matrix and its lens-EEPROM AWB calibration points. Pass the
as-shot white balance read with `st cap iq awb wbgain` via `--wb-gains R B`; by default each
file's 360_NNNN_wb.txt (written by the camera's raw watcher) is read automatically.

Metadata: Make/Model are the camera's own (SAMSUNG / SM-R210, as in its JPEGs) so PTGui and other tools treat the DNG
as the same camera; UniqueCameraModel stays "Samsung SM-R210 ssif dump" (raw converters key colour profiles on it).
For camera-named raws, the shot's EXIF (exposure time, aperture, ISO, exposure program/mode, metering, capture times,
focal length 1.2 mm and its 35 mm equivalent) is copied from 360_NNNN.JPG with exiftool, plus a lens name. PTGui needs
the exposure times to group and merge HDR brackets. --no-exif skips this.

Defect pixels: the raw dump is taken before the camera's defect correction, so its factory hot/dead pixel list
(adj_dpc.bin from `st util dump`, see docs/defect-pixels.md) is applied here: each listed pixel is replaced by the
median of its same-colour neighbours. `--dpc auto` picks the list level from the shot's ISO and shutter speed the way
the camera does; `--dpc none` leaves the data untouched.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np
from pidng.core import RAW2DNG
from pidng.defs import (CalibrationIlluminant, CFAPattern, DNGVersion,
                        Orientation, PhotometricInterpretation,
                        PreviewColorSpace)
from pidng.dng import DNGTags, Tag

import dpc_decode

# Measured on the SM-R210 ssif dump, 2026-10-10 (16-bit units).
DEFAULT_WIDTH = 5824
DEFAULT_HEIGHT = 2896
DEFAULT_PATTERN = "GRBG"
DEFAULT_BLACK = 4096   # 256 in 12-bit; median of unlit corners, both lenses, all channels
DEFAULT_WHITE = 65472  # 4092 in 12-bit; clipped highlights pile up here

PATTERNS = {
    "RGGB": CFAPattern.RGGB,
    "GRBG": CFAPattern.GRBG,
    "BGGR": CFAPattern.BGGR,
    "GBRG": CFAPattern.GBRG,
}

# --- Camera colour data, read from the SM-R210 (see docs/lab-notebook.md "Camera colour pipeline") ---
# `st cap iq awb deltae` FrontCC: white-balanced camera RGB -> linear sRGB. Rows sum to 1.
CAMERA_CC = np.array([[1.804688, -0.742188, -0.062500],
                      [-0.210938, 1.453125, -0.242188],
                      [0.015625, -0.593750, 1.578125]])
# Lens EEPROM AWB calibration points (EEPA_AWB_*, raw R/G and B/G x 4096); WB gain = 4096 / value.
# Which illuminant each point is was inferred from the gains, not documented.
WB_GAINS_D65 = (4096 / 1716, 1.0, 4096 / 2287)  # EEPA_AWB_EEPROM_POINT2 (coolest point, ~daylight)
WB_GAINS_A = (4096 / 2839, 1.0, 4096 / 1444)    # EEPA_AWB_LOW_GAIN (warm point, ~tungsten; paired with FrontCC)
# `deltae` tone curve: 14-bit linear in -> 10-bit out. Optional ProfileToneCurve.
TONE_X = [0, 32, 74, 140, 232, 365, 550, 810, 1169, 1664, 2338, 3243, 4438, 5980, 7894, 10180, 12840, 15872, 16383]
TONE_Y = [0, 8, 21, 45, 80, 128, 194, 269, 355, 452, 556, 657, 748, 828, 895, 953, 998, 1022, 1023]

# --- Standard colorimetry constants (colour-science would supply these, but its import is broken
# here by a system/user matplotlib conflict, so the published values are used directly) ---
# IEC 61966-2-1 sRGB: XYZ (D65) -> linear sRGB.
XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314],
                        [-0.9692660, 1.8760108, 0.0415560],
                        [0.0556434, -0.2040259, 1.0572252]])
# Bradford cone-response matrix (Lam 1985, as used by ICC / Lindbloom).
BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                     [-0.7502, 1.7135, 0.0367],
                     [0.0389, -0.0685, 1.0296]])
# CIE 1931 2-degree white points, Y = 1.
XYZ_D65 = np.array([0.95047, 1.0, 1.08883])
XYZ_A = np.array([1.09850, 1.0, 0.35585])


def bradford_adapt(src_white, dst_white):
    """Matrix adapting XYZ under src_white to XYZ under dst_white (von Kries in Bradford space)."""
    src_lms = BRADFORD @ src_white
    dst_lms = BRADFORD @ dst_white
    return np.linalg.inv(BRADFORD) @ np.diag(dst_lms / src_lms) @ BRADFORD


def colour_matrix(wb_gains, illuminant_xyz):
    """DNG ColorMatrix (XYZ under the illuminant -> camera native RGB) from the camera's own CC.

    Camera model: linear_sRGB = CC @ diag(wb) @ camera, with the scene adapted to D65.
    So camera = diag(1/wb) @ inv(CC) @ XYZ_TO_SRGB @ adapt(illuminant -> D65) @ XYZ.
    Normalised so the illuminant's white maps to a camera neutral with max component 1.
    """
    m = (np.diag(1.0 / np.asarray(wb_gains)) @ np.linalg.inv(CAMERA_CC)
         @ XYZ_TO_SRGB @ bradford_adapt(illuminant_xyz, XYZ_D65))
    return m / (m @ illuminant_xyz).max()


def srational(values, denom=1_000_000):
    return [[int(round(v * denom)), denom] for v in np.ravel(values)]


def rational(values, denom=1_000_000):
    return [[int(round(abs(v) * denom)), denom] for v in np.ravel(values)]


IDENTITY_MATRIX = srational(np.eye(3))


def report_stats(raw):
    """Print value statistics so black/white level and bit alignment can be chosen."""
    flat = raw.ravel()
    pcts = np.percentile(flat, [0, 0.01, 1, 50, 99, 99.99, 100])
    print(f"min {flat.min()}  max {flat.max()}  mean {flat.mean():.1f}")
    print("percentiles 0/0.01/1/50/99/99.99/100: " + " ".join(f"{p:.0f}" for p in pcts))
    low4 = np.count_nonzero(flat & 0xF)
    print(f"values with any of the low 4 bits set: {low4} of {flat.size} "
          f"({'data looks LOW-aligned' if low4 else 'low 4 bits always 0: data may be HIGH-aligned'})")
    # Per-position means of each 2x2 Bayer cell, to help guess the pattern.
    for (dy, dx) in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        print(f"  cell ({dy},{dx}) mean {raw[dy::2, dx::2].mean():.1f}")


def build_tags(width, height, pattern, black, white, colour, wb_gains, tone_curve):
    t = DNGTags()
    t.set(Tag.ImageWidth, width)
    t.set(Tag.ImageLength, height)
    t.set(Tag.TileWidth, width)
    t.set(Tag.TileLength, height)
    t.set(Tag.Orientation, Orientation.Horizontal)
    t.set(Tag.PhotometricInterpretation, PhotometricInterpretation.Color_Filter_Array)
    t.set(Tag.SamplesPerPixel, 1)
    t.set(Tag.BitsPerSample, 16)
    t.set(Tag.CFARepeatPatternDim, [2, 2])
    t.set(Tag.CFAPattern, pattern)
    t.set(Tag.BlackLevel, black)
    t.set(Tag.WhiteLevel, white)
    if colour == "camera":
        t.set(Tag.ColorMatrix1, srational(colour_matrix(WB_GAINS_A, XYZ_A)))
        t.set(Tag.CalibrationIlluminant1, CalibrationIlluminant.Standard_Light_A)
        t.set(Tag.ColorMatrix2, srational(colour_matrix(WB_GAINS_D65, XYZ_D65)))
        t.set(Tag.CalibrationIlluminant2, CalibrationIlluminant.D65)
    else:
        t.set(Tag.ColorMatrix1, IDENTITY_MATRIX)
        t.set(Tag.CalibrationIlluminant1, CalibrationIlluminant.D65)
    # AsShotNeutral is the raw value of a neutral grey relative to green: 1 / WB gain.
    t.set(Tag.AsShotNeutral, rational([1.0 / g for g in wb_gains]))
    if tone_curve:
        pts = []
        for x, y in zip(TONE_X, TONE_Y):
            pts += [x / TONE_X[-1], y / TONE_Y[-1]]
        t.set(Tag.ProfileName, "SM-R210 camera tone curve")
        t.set(Tag.ProfileToneCurve, pts)
    t.set(Tag.Make, "SAMSUNG")         # as in the camera's JPEG EXIF
    t.set(Tag.Model, "SM-R210")
    t.set(Tag.UniqueCameraModel, "Samsung SM-R210 ssif dump")
    t.set(Tag.DNGVersion, DNGVersion.V1_4)
    t.set(Tag.DNGBackwardVersion, DNGVersion.V1_2)
    t.set(Tag.PreviewColorSpace, PreviewColorSpace.sRGB)
    return t


WB_LINE = re.compile(r"WB gain front is \d+ \d+ \d+ ([\d.]+) ([\d.]+) ([\d.]+)")


def sidecar_wb(raw_path):
    """WB gains (R, 1, B) from the 360_NNNN_wb.txt the camera's raw watcher writes next to 360_NNNN.raw, or None."""
    wb_path = os.path.splitext(raw_path)[0] + "_wb.txt"
    if not os.path.exists(wb_path):
        return None
    m = WB_LINE.search(open(wb_path, errors="replace").read())
    if not m:
        print(f"  {wb_path}: no 'WB gain front' line, ignoring it")
        return None
    return float(m.group(1)), 1.0, float(m.group(3))


# EXIF copied from the shot's camera JPEG (same capture as the raw dump, so the values are exact).
EXIF_FROM_JPEG = ["ExposureTime", "FNumber", "ISO", "ExposureProgram", "ExposureMode", "ExposureCompensation",
                  "MeteringMode", "DateTimeOriginal", "CreateDate", "ModifyDate", "FocalLength",
                  "FocalLengthIn35mmFormat", "MaxApertureValue", "SensingMethod"]
LENS_MAKE, LENS_MODEL = "SAMSUNG", "SM-R210 1.2mm f/2.2 dual fisheye"


def camera_jpeg(raw_path):
    stem = os.path.splitext(raw_path)[0]
    for ext in (".JPG", ".jpg", ".jpeg", ".JPEG"):
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def copy_exif(dng, raw_path):
    """Copy the shot's EXIF from its camera JPEG into the DNG with exiftool; returns a one-line report."""
    if shutil.which("exiftool") is None:
        return "exiftool not found: DNG has no exposure/focal-length EXIF (install exiftool or use --no-exif)"
    jpg = camera_jpeg(raw_path)
    cmd = ["exiftool", "-overwrite_original", "-m", f"-LensMake={LENS_MAKE}", f"-LensModel={LENS_MODEL}"]
    if jpg:
        cmd += ["-TagsFromFile", jpg] + [f"-{t}" for t in EXIF_FROM_JPEG]
    r = subprocess.run(cmd + [dng], capture_output=True, text=True)
    if r.returncode != 0:
        return f"exiftool failed: {r.stderr.strip() or r.stdout.strip()}"
    got = subprocess.run(["exiftool", "-s3", "-ExposureTime", "-ISO", "-FNumber", "-FocalLength", dng],
                         capture_output=True, text=True).stdout.split()
    if not jpg:
        return f"no camera JPEG next to {os.path.basename(raw_path)}: lens name only, NO exposure EXIF"
    return f"EXIF from {os.path.basename(jpg)}: " + " / ".join(got)


def read_jpeg_exposure(jpg_path):
    """(exposure time in s, ISO) from the camera JPEG with exiftool, or (None, None)."""
    if not jpg_path or not os.path.exists(jpg_path) or not shutil.which("exiftool"):
        return None, None
    out = subprocess.run(["exiftool", "-T", "-n", "-ExposureTime", "-ISO", jpg_path],
                         capture_output=True, text=True).stdout.strip().split("\t")
    try:
        return float(out[0]), int(float(out[1]))
    except (ValueError, IndexError):          # "-" for a missing tag
        return None, None


def pick_dpc_level(iso, exposure_time):
    """Defect-table level for a shot, as the camera's selector picks it (A7 0x803d0e84).

    The selector compares APEX Sv/Tv: Tv >= 4 (1/16 s or faster), Tv >= 0 (up to 1 s); Sv <= 7 (ISO 400),
    Sv <= 9 (ISO 1600). Its alternative ISO-only rule (an unidentified mode setting) isn't modelled.
    """
    if exposure_time is None or iso is None:
        return 2, "LV2, no ISO/shutter in EXIF"
    fast, mid = exposure_time <= 1 / 16, exposure_time <= 1.0
    if fast:
        level = 1 if iso <= 400 else 2 if iso <= 1600 else 3
    elif mid:
        level = 2 if iso <= 400 else 3
    else:
        level = 3
    t = f"1/{round(1 / exposure_time)} s" if exposure_time < 1 else f"{exposure_time:g} s"
    return level, f"LV{level} for ISO {iso}, {t}"


_DPC_CACHE = {}


def find_dpc_tables(raw_path):
    """adj_dpc.bin next to the raw, in the working directory, or in this project's calibration dump."""
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(os.path.dirname(os.path.abspath(raw_path)), "adj_dpc.bin"),
              "adj_dpc.bin",
              os.path.join(here, "..", "calibration", "util_dump", "extracted", "tmp", "adj_dpc.bin")):
        if os.path.isfile(c):
            return os.path.normpath(c)
    return None


def load_dpc_tables(path):
    """The six still tables {(lens, level): (rows, cols)} from adj_dpc.bin, decoded once per run."""
    if path not in _DPC_CACHE:
        data = open(path, "rb").read()
        found = dpc_decode.find_tables(data)[:6]
        _DPC_CACHE[path] = {(name.split("_")[0], int(name[-1])): dpc_decode.decode(data, start, n)
                            for name, (start, n) in zip(dpc_decode.NAMES[:6], found)}
    return _DPC_CACHE[path]


def apply_dpc(raw, tables, level):
    """Replace each listed defect with the median of its 8 same-colour neighbours (2 px away), in place.

    Neighbours that would fall outside the lens half are mirrored to the other side, so they keep the same colour.
    Returns the number of pixels replaced per lens.
    """
    counts = {}
    half_w = raw.shape[1] // 2
    for lens, x0 in (("FRONT", 0), ("REAR", half_w)):
        rows, cols = tables[(lens, level)]
        half = raw[:, x0:x0 + half_w]
        h, w = half.shape

        def step(v, d, size):
            u = v + d
            return np.where((u < 0) | (u >= size), v - d, u)
        nbrs = [half[step(rows, dy, h), step(cols, dx, w)]
                for dy in (-2, 0, 2) for dx in (-2, 0, 2) if dy or dx]
        half[rows, cols] = np.median(np.stack(nbrs), axis=0).astype(raw.dtype)
        counts[lens] = len(rows)
    return counts


def convert(path, args):
    if args.wb_gains:
        wb_gains, wb_src = (args.wb_gains[0], 1.0, args.wb_gains[1]), "--wb-gains"
    else:
        wb_gains = sidecar_wb(path)
        wb_src = os.path.basename(os.path.splitext(path)[0] + "_wb.txt")
        if wb_gains is None:
            wb_gains, wb_src = WB_GAINS_D65, "default daylight point (no _wb.txt found)"

    expected = args.width * args.height * 2
    size = os.path.getsize(path)
    if size != expected:
        print(f"SKIP {path}: {size} bytes, expected {expected} for {args.width}x{args.height} uint16")
        return False

    raw = np.fromfile(path, dtype="<u2").reshape(args.height, args.width)
    print(f"read {path}: {args.width}x{args.height} uint16")
    report_stats(raw)

    if args.dpc != "none":
        tables_path = args.dpc_tables or find_dpc_tables(path)
        if not tables_path:
            print("  defect pixels: not corrected, no adj_dpc.bin found (give --dpc-tables, or --dpc none)")
        else:
            if args.dpc == "auto":
                exposure, iso = read_jpeg_exposure(camera_jpeg(path))
                level, reason = pick_dpc_level(iso, exposure)
            else:
                level, reason = int(args.dpc[-1]), f"forced {args.dpc.upper()}"
            counts = apply_dpc(raw, load_dpc_tables(tables_path), level)
            print(f"  defect pixels: {counts['FRONT']:,} front / {counts['REAR']:,} rear replaced "
                  f"({reason}; tables {tables_path})")

    print(f"using pattern {args.pattern}, black {args.black}, white {args.white}, colour {args.colour}, "
          f"WB gains R {wb_gains[0]:.3f} B {wb_gains[2]:.3f} (from {wb_src}), "
          f"tone curve {'on' if args.tone_curve else 'off'}")

    outdir = args.outdir or os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    names = list(PATTERNS) if args.pattern == "all" else [args.pattern]
    for i, name in enumerate(names, 1):
        start = time.time()
        r = RAW2DNG()
        r.options(build_tags(args.width, args.height, PATTERNS[name], args.black, args.white,
                             args.colour, wb_gains, args.tone_curve),
                  path=outdir, compress=False)
        # Camera-named raws (360_NNNN.raw, moved next to their JPEG) -> 360_NNNN.dng; others keep the pattern suffix
        dng_name = stem if (args.pattern != "all" and stem.startswith("360_")) else f"{stem}_{name}"
        out = r.convert(raw, filename=dng_name)
        print(f"  [{i}/{len(names)}] wrote {out} in {time.time() - start:.1f}s", flush=True)
        if not args.no_exif:
            print(f"      {copy_exif(out, path)}", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", nargs="+", help="headerless uint16 little-endian Bayer dump(s)")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH, help=f"default {DEFAULT_WIDTH}")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help=f"default {DEFAULT_HEIGHT}")
    ap.add_argument("--black", type=int, default=DEFAULT_BLACK, help=f"black level, default {DEFAULT_BLACK}")
    ap.add_argument("--white", type=int, default=DEFAULT_WHITE, help=f"white level, default {DEFAULT_WHITE}")
    ap.add_argument("--pattern", choices=list(PATTERNS) + ["all"], default=DEFAULT_PATTERN,
                    help=f"Bayer pattern, default {DEFAULT_PATTERN}; 'all' writes one DNG per pattern")
    ap.add_argument("--outdir", default=None, help="output directory (default: next to the input)")
    ap.add_argument("--colour", choices=["camera", "none"], default="camera",
                    help="'camera' (default): ColorMatrix1/2 from the camera's FrontCC and EEPROM AWB points; "
                         "'none': identity placeholder")
    ap.add_argument("--wb-gains", type=float, nargs=2, metavar=("R", "B"), default=None,
                    help="as-shot WB gains from `st cap iq awb wbgain` (e.g. 2.164 1.820), used for every file; "
                         "default: each file's 360_NNNN_wb.txt, else the daylight point "
                         f"{WB_GAINS_D65[0]:.3f} {WB_GAINS_D65[2]:.3f}")
    ap.add_argument("--no-exif", action="store_true",
                    help="don't copy EXIF (exposure, ISO, focal length, ...) from the shot's camera JPEG")
    ap.add_argument("--tone-curve", action="store_true",
                    help="embed the camera's 19-point tone curve as ProfileToneCurve")
    ap.add_argument("--dpc", choices=["auto", "lv1", "lv2", "lv3", "none"], default="auto",
                    help="defect-pixel correction: 'auto' (default: picks LV from EXIF ISO/shutter), "
                         "'lv1'/'lv2'/'lv3', or 'none'")
    ap.add_argument("--dpc-tables", default=None,
                    help="the camera's adj_dpc.bin (from st util dump); default: next to the raw, the working "
                         "directory, or calibration/util_dump/extracted/tmp/")
    args = ap.parse_args()

    if args.colour == "camera":
        np.set_printoptions(precision=4, suppress=True)
        print(f"ColorMatrix1 (A):\n{colour_matrix(WB_GAINS_A, XYZ_A)}")
        print(f"ColorMatrix2 (D65):\n{colour_matrix(WB_GAINS_D65, XYZ_D65)}")
    done = 0
    for k, path in enumerate(args.raw, 1):
        print(f"=== [{k}/{len(args.raw)}] {path}", flush=True)
        done += convert(path, args)
    print(f"converted {done} of {len(args.raw)} file(s)")
    if done < len(args.raw):
        sys.exit(1)


if __name__ == "__main__":
    main()
