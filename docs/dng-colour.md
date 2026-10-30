# DNG conversion and colour

How `tools/raw2dng.py` turns a Gear 360 raw dump into a DNG, and where its colour matrices and white balance come from.

## What raw2dng does

`raw2dng.py` wraps the headerless dump in a DNG using PiDNG. It does not demosaic; that is left to the raw converter (Adobe Camera Raw, darktable, dcraw). PTGui opens the DNGs directly.

For each file it checks the size against width × height × 2 and skips (and reports) any file that doesn't match, prints value statistics (percentiles, whether any low 4 bits are set, the mean of each 2×2 Bayer cell), writes the DNG, and copies the shot's EXIF from its JPEG. It shows `[k/N]` progress, ends with `converted X of N file(s)`, and exits with status 1 if any file was skipped.

Defaults are the values measured on the SM-R210 (see [raw-capture.md](raw-capture.md#file-format)):

| Option | Default |
|---|---|
| `--width` / `--height` | 5824 / 2896 |
| `--pattern` | `GRBG` (also `RGGB`, `BGGR`, `GBRG`, or `all`) |
| `--black` / `--white` | 4096 / 65472 |
| `--colour` | `camera` (or `none` for an identity placeholder matrix) |
| `--wb-gains R B` | each file's `360_NNNN_wb.txt`, else the daylight point (2.387, 1.791) |
| `--outdir` | next to the input |
| `--tone-curve` | off |
| `--no-exif` | off (EXIF is copied) |

A camera-named raw (`360_NNNN.raw`) becomes `360_NNNN.dng`. Other names, and every file written with `--pattern all`, get the pattern as a suffix, e.g. `0_0_11648_5824x2896_bayer_12-16_GRBG.dng`. The DNG is uncompressed, DNG version 1.4 (backward version 1.2), with Make `SAMSUNG` and Model `SM-R210` as in the camera's JPEGs, and UniqueCameraModel `Samsung SM-R210 ssif dump`.

Install the Python packages from `requirements.txt` (`numpy` and `pidng` are the ones this script uses). The EXIF copy needs `exiftool` on the PATH; without it the script still writes the DNG and says it has no exposure EXIF.

## Usage

One raw that the camera's watcher has already moved next to its JPEG and `_wb.txt`:

```
python3 tools/raw2dng.py 360_NNNN.raw
```

Several files at once; each one reads its own `360_NNNN_wb.txt`:

```
python3 tools/raw2dng.py 360_0375.raw 360_0376.raw 360_0377.raw
```

A dump with no sidecar, giving the `wbgain` reading by hand (these gains are then used for every file on the command line):

```
python3 tools/raw2dng.py 0_0_11648_5824x2896_bayer_12-16.raw --wb-gains 2.164 1.820
```

One DNG per Bayer pattern, to compare them:

```
python3 tools/raw2dng.py 360_NNNN.raw --pattern all
```

Embed the camera's tone curve, skip the EXIF copy, or write an identity colour matrix:

```
python3 tools/raw2dng.py 360_NNNN.raw --tone-curve
python3 tools/raw2dng.py 360_NNNN.raw --no-exif
python3 tools/raw2dng.py 360_NNNN.raw --colour none
```

To demosaic on the command line instead of in a raw editor, use `dcraw -w -T <file>.dng`. `-w` applies the DNG's AsShotNeutral (the shot's white balance), and `-T` writes an 8-bit sRGB TIFF, which is what `opax_stitch.py`'s lens-shading correction expects by default. The early notebook entries used `-a` (auto white balance from the whole image), which ignores the camera's white balance.

## Where the colour comes from

All the colour data was read from the camera with `st cap iq awb` commands.

`st cap iq awb deltae` prints the camera's colour-correction matrix, `FrontCC`. Its rows sum to 1.0, so it maps white-balanced camera RGB to output RGB, presumably linear sRGB:

```
 1.804688 -0.742188 -0.062500
-0.210938  1.453125 -0.242188
 0.015625 -0.593750  1.578125
```

The same command printed `WB Gain 1.442749 2.836563`, which is 4096/2839 and 4096/1444, exactly lens A's EEPROM `AWB_LOW_GAIN`. So the matrix is printed alongside the LOW calibration point. It also prints a 19-point tone curve (14-bit linear in, 10-bit out) and `Line adjust value OK, delta E 0.468523`, a factory production-line check that passed.

The lens-module EEPROMs (`EEPA_*` / `EEPB_*`, read with `dfmstool -a`) hold four AWB calibration points, as raw R/G and B/G × 4096. Lens A and lens B agree within about 1-2%. The light each point stands for is our inference from the gains:

| Point | R/G | B/G | WB gains (R, B) | Likely light (inferred) |
|---|---|---|---|---|
| POINT2 | 0.419 | 0.558 | 2.39, 1.79 | daylight, ~D65 |
| POINT3 | 0.518 | 0.398 | 1.93, 2.51 | ~4000 K |
| LOW | 0.693 | 0.353 | 1.44, 2.84 | tungsten, ~illuminant A |
| POINT4 | 0.841 | 0.280 | 1.19, 3.57 | ~2300 K |

## The colour matrices

The camera model behind the matrices is `linear sRGB = CC · diag(WB) · camera`, with CC = FrontCC and WB the white-balance gains for the illuminant. Inverting that gives the DNG ColorMatrix (XYZ to camera RGB):

```
ColorMatrix = diag(1/WB) · CC⁻¹ · M(XYZ→sRGB, D65) · Bradford(illuminant → D65)
```

normalised so the illuminant's white maps to a camera neutral whose largest component is 1. The Bradford step adapts XYZ under the calibration illuminant to D65 before the sRGB matrix; for the D65 matrix it does nothing. `raw2dng.py` writes:

- ColorMatrix1, CalibrationIlluminant1 = Standard Light A, from the LOW point (WB gains 4096/2839, 4096/1444).
- ColorMatrix2, CalibrationIlluminant2 = D65, from POINT2 (WB gains 4096/1716, 4096/2287).

This assumes the camera uses one fixed CC for every illuminant. That is unverified; it could interpolate between several.

On the first test dump exiftool read back:

```
ColorMatrix1   0.955 -0.342 -0.037 / -0.558 1.483 0.366 / -0.043 0.115 0.802
ColorMatrix2   0.671 -0.126 -0.085 / -0.460 1.308 0.119 / -0.086 0.204 0.400
AsShotNeutral  0.462 1 0.549
```

`--colour none` writes an identity ColorMatrix1 (labelled D65) instead. That was the first placeholder, and it gave a slight magenta cast.

## White balance per shot

AsShotNeutral is 1 / WB gain for each channel. The gains come from `st cap iq awb wbgain`, which prints the live AWB gains for each lens (256 = 1.0). On the camera, `rawwatch.sh` saves that output as `360_NNNN_wb.txt` straight after moving each raw, and `raw2dng.py` reads the `WB gain front is …` line from it. Only the front lens's gains are used. An indoor reading by a window gave front R 2.164 / B 1.820 and rear R 2.176 / B 1.809, so AsShotNeutral ≈ R 0.462, B 0.549.

Precedence: `--wb-gains` if given (for every file), else each file's `_wb.txt`, else the POINT2 daylight gains.

## Results

Opened in Photoshop's Adobe Camera Raw, the first DNG (converted with `--wb-gains 2.164 1.820`) was judged "color looks about perfect".

A second shot had a ColorChecker Passport in the left fisheye, in an office lit by mixed window daylight and monitors, with the chart small in frame. A `dcraw -w -h` render compared with the camera JPEG matched hues closely patch by patch. The dcraw render was flatter and less saturated, which is expected because the camera JPEG adds a tone curve and saturation. We have not done a numeric check.

`--tone-curve` embeds the camera's 19-point curve as a DNG ProfileToneCurve (profile name `SM-R210 camera tone curve`), to get closer to the camera JPEG's look.

The dumps have no lens-shading correction, so the DNGs show stronger vignetting than the camera's JPEGs. `raw2dng.py` doesn't correct it.

## EXIF

For a camera-named raw, `raw2dng.py` copies these tags from `360_NNNN.JPG` with exiftool: ExposureTime, FNumber, ISO, ExposureProgram, ExposureMode, ExposureCompensation, MeteringMode, DateTimeOriginal, CreateDate, ModifyDate, FocalLength, FocalLengthIn35mmFormat, MaxApertureValue and SensingMethod. It also sets LensMake `SAMSUNG` and LensModel `SM-R210 1.2mm f/2.2 dual fisheye`. PTGui needs the exposure times to group and merge HDR brackets. If there is no JPEG next to the raw, the DNG gets the lens name only.

The camera's EXIF records the requested exposure time, not the real one. A "1 s" shot measured about 0.173 s from its raw, and we think every request longer than about 1/6 s gets about 1/6 s, so DNGs of those shots carry the wrong (requested) ExposureTime. See [exposure.md](exposure.md).

## Not verified

- The tungsten matrix (ColorMatrix1): no tungsten shot yet.
- The illuminant each EEPROM AWB point stands for; the labels are inferred from the gains.
- The lens difference. `st cap iq awb adjgain` (65536 = 1.0) gives per-unit gains of front R 1.0162 / B 0.9550 and rear R 1.0326 / B 0.9406, and a rear-relative-to-front difference of R 1.0161 / B 0.9850. The two lenses differ by about 1.5% in R and B, which matters at the stitch seam. `raw2dng.py` doesn't apply this.
- Which half of the raw frame is the front lens and which is the rear.

Source: [Camera colour pipeline from `st cap iq awb` (2026-10-10)](lab-notebook.md#camera-colour-pipeline-from-st-cap-iq-awb-2026-10-10), [DNG colour v1 — works (2026-10-10)](lab-notebook.md#dng-colour-v1--works-2026-10-10), [RAW test 3: second dump shot + ColorChecker in frame (2026-10-10)](lab-notebook.md#raw-test-3-second-dump-shot--colorchecker-in-frame-2026-10-10), [Camera session 1 — RAW test 2: `st cap seq dump on ssif` ✅ (2026-10-10)](lab-notebook.md#camera-session-1--raw-test-2-st-cap-seq-dump-on-ssif--2026-10-10), [Power RAW retest, web UI sizes and preview, grid shots, PTGui lens numbers (2026-10-11)](lab-notebook.md#power-raw-retest-web-ui-sizes-and-preview-grid-shots-ptgui-lens-numbers-2026-10-11), [Long exposures are capped at ~1/6 s: measured (2026-10-12)](lab-notebook.md#long-exposures-are-capped-at-16-s-measured-2026-10-12)
