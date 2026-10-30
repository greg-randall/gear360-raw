# Lens model

Every photo from the SM-R210 carries the unit's factory lens calibration, and the camera's stitcher library uses it with a fixed OCamCalib-style fisheye model. This page covers where the numbers live, what each one means, and how to turn a pixel into a ray.

## Where the calibration lives

- The camera's JPEGs are unstitched dual fisheye (EXIF `SamsungTrailer 0x0a60 = "Jpeg360_2D_NotStitched"`). Stitching happens in Samsung's phone app, or on the camera only in Street View/OSC mode, both through `GlobeStitcher` in `/usr/lib/libdi-alg-imagestitch.so`.
- The Samsung maker note tag `0x0012` is 160 bytes: 20 little-endian float64 values. We found it identical in every photo we checked, from 2021 to 2026.
- `st util dump` writes `/mnt/mmc/dump.tgz` (an uncompressed tar despite the name), which includes `eeprom_a.bin` and `eeprom_b.bin`, the two raw lens-module EEPROMs (8192 bytes each). EEPROM file offset = dfmstool table offset − 0x200.
- The 16 float64 values at EEPROM file offset 0xd0 (`OPTICAL_AXIS_01..16`) are byte-identical to maker note `0x0012`, in both EEPROMs. `OPTICAL_AXIS_17..40` are 0. `OPTICAL_AXIS_FLAG` (file 0x210) = 2.
- `ADE_ImageStitch_get_OPAX(out, size)` in the stitcher library reads offsets 0xd0, 0xd8 … 0x168 from adjust-data block `0x85c2` (the EEPROM) into `out[0..19]`, so the record in the photo is the EEPROM record.
- So this record ("OPAX") is the complete factory geometric calibration for the unit, stored per lens pair (the same set in both modules). There's no further hidden lens model in the EEPROM.
- The factory calibration dates (`CREATE_DATE`) on our unit are A = 20171101 and B = 20171031. The set ID string is `CH80135F5E80174` in both EEPROMs.

The values below are from our unit. Yours will differ; read them from any of your photos with exiftool or from `st util dump`.

## The 15 fields

Record layout: `[0]` = int32 2 (format version; it reads as 1e-323 if you treat it as a double), `[1..15]` = calibration, `[16..19]` = 0. The camera app has a getter per field (`CHardwareInfoProvider::get_optical_axis_<name>()` → `get_opax_by_param(n)`) and the label strings appear in the same order, which is where the names come from. These names are verified.

| rec | name | our value | used by the camera's GlobeStitcher as |
|---|---|---|---|
| 0 | OpaxVersion | 2 (int) | must be 2, else defaults |
| 1 | LeftCenterX | 1444.656 | lens 1 OCam `xc` (×2048/2896), horizontal / u |
| 2 | LeftCenterY | 1446.121 | lens 1 `yc`, vertical / v |
| 3 | RightCenterX | 1444.060 | lens 2 `xc` |
| 4 | RightCenterY | 1447.008 | lens 2 `yc` |
| 5 | LeftRadius | 1444.303 | not used on camera (image circle radius, px) |
| 6 | RightRadius | 1440.992 | not used on camera |
| 7 | LeftAffineX | 1.000304 | lens 1 OCam `c` |
| 8 | LeftAffineY | 6.55e-5 | lens 1 `d` |
| 9 | LeftAffineZ | 6.55e-5 | lens 1 `e` |
| 10 | RightAffineX | 1.000595 | lens 2 `c` |
| 11 | RightAffineY | -1.40e-4 | lens 2 `d` |
| 12 | RightAffineZ | -1.40e-4 | lens 2 `e` |
| 13 | DiffX | 4.630 | not used on camera |
| 14 | DiffY | 7.433 | not used on camera |
| 15 | DiffRollAngle | 1.256 | not used on camera |
| 16 | SpecResult? | 0 | `get_optical_axis_spec_result` exists; index not checked |

Left = lens 1 and Right = lens 2. Centres and radii are in pixels of a 2896-px lens square.

The full 160-byte record is also sent to the phone (DLNA `OpaxValue`, `RVFOpaxDataInfo`) and to the PC app (`E_PC_CMD_ID_OPAX`), so the phone and PC stitchers probably use the Radius and Diff fields (inferred).

## From the EEPROM record to the GL stitcher

The stitcher's `GlobeStitcher::init(__globeOPAI*, globeOPAX*, float*)` doesn't take the 20-double record. Its `globeOPAX` is 2 lenses × 5 doubles. The converter is `main_init(char* opax, char* opai)`, called from `ADE_ImageStitch_Initialize`. Verified from the disassembly:

- If `rec[0] != 2` it logs "[Use default]opax…" and sets rec[1..4] = 1448.0 (half of 2896), rec[7] = rec[10] = 1.0 and rec[8], rec[9], rec[11], rec[12] = 0.
- If `rec[0] == 2`, with `s = 2048 / 2896`:

```
opax1 = [rec[2]·s, rec[1]·s, rec[7], rec[8], rec[9]]
opax2 = [rec[4]·s, rec[3]·s, rec[10], rec[11], rec[12]]
```

- rec[5], rec[6] and rec[13..15] are not read by `main_init` or by `GlobeStitcher`.
- The `angle` argument (3 floats) comes from a global, not from OPAX. It's probably the gyro attitude from EXIF Yaw/Pitch/RollAngle; unverified.
- The OPAI record goes to `GenerateLscInfoRGB`, so OPAI is lens shading, not geometry. See [stitching.md](stitching.md#lens-shading).
- If `opax` is NULL, `setDefaultOpax()` uses built-in values for a ~2048-px image: lens 1 = [1011.45, 1014.82, 0.996647, 0, 0], lens 2 = [1024.50, 1028.96, 0.997043, 0, 0].

## The OCamCalib variant

`GlobeStitcher::initialize` calls `get_ocam_model_default(ocam_model*, pol, invpol, centre, affine, size)` once per lens. The struct layout matches OCamCalib's `ocam_model` (Scaramuzza) exactly. Verified.

`pol`, `invpol` and size are shared firmware constants (`.data` 0x57e198), the same for both lenses and every unit:

```
pol    (6) = [-1.5726272232, 1.0398124751, -0.2998335059, 0.3542703799, -0.2635065184, 0.0709548046]
invpol (6) = [971.9375896974, 526.1058092068, -499.094003808, -645.9034011167, -336.1369527907, -65.8206694527]
size       = 2048 × 2048
```

Per lens, `centre[0]` → `yc` and `centre[1]` → `xc`, so `xc` = rec[1]·s and `yc` = rec[2]·s for lens 1, and `xc` = rec[3]·s, `yc` = rec[4]·s for lens 2. The affine `c, d, e` are rec[7..9] (lens 1) and rec[10..12] (lens 2).

This differs from stock OCamCalib: the polynomials work in the angle `θ = atan(z / √(x²+y²))`, with θ = −π/2 on the optical axis and 0 at 90° off-axis.

world2cam (ray to pixel, at 2048 scale):

```
rho = Σ invpol[i]·θ^i          (rejects θ >= 0.2 rad)
x' = rho·x/‖xy‖,  y' = rho·y/‖xy‖
u' = c·x' + d·y'
v' = e·x' + y'
```

cam2world (pixel to ray): undo the affine, then

```
r = ‖(u', v')‖
θ = Σ pol[i]·(r / 529.4726)^i
z = tan(θ)·r
```

The texture lookup in `CGL_ACCapture::p_getTexCoord(θ, φ, ocam)`:

```
ρ = invpol(θ)
u = (c·ρcosφ + d·ρsinφ + xc) / width
v = (e·ρcosφ + ρsinφ + yc) / height
```

So `xc` is the horizontal (u) centre and `yc` the vertical (v) centre, which is why rec[1], rec[2] are lens 1 (cx, cy).

Field of view: world2cam rejects θ ≥ 0.2 rad (11.46° past 90°), so the model's usable field is about 2·(90° + 11.46°) ≈ 203°. As a sanity check, invpol(−π/2) ≈ 0.3 px (the axis sits at the centre), invpol(0) = 971.9 px at 2048 scale = 1374.6 px at 2896 scale (90° off-axis), and invpol(0.2) ≈ 1051 px → 1487 px. In practice the image circle ends about 4–5° past 90° (≈190° per lens), so the overlap between lenses is narrow.

`tools/opax_stitch.py` uses the same model, written for 2896-px lens squares with `rho = rho_2048 · 2896/2048` and φ the image-plane angle (x right, y down):

```
col = xc + c·rho·cos(φ) + d·rho·sin(φ)
row = yc + e·rho·cos(φ) +   rho·sin(φ)
```

## Image geometry

- The camera JPEG is 5792×2896: two 2896-px squares cropped from the raw's two 2912-px halves, with no resampling. The raw (see [raw-capture.md](raw-capture.md)) is 5824×2896.
- ECC registration of raw against JPEG on shot 360_0334 (correlation 0.90) gave `raw-half px = JPEG-square px + (7.42, -0.14)` for both halves, with scale 1.0002 and rotation 0.003°. There's no left/right swap. Two other pairs registered poorly (dark, little texture). `tools/raw_jpeg_geometry.py` is the tool that measured it.
- So the OPAX centres apply to raw files with that fixed shift, and no per-shot circle finding is needed.
- Circle fits of the bright image circle in the JPEGs put the centres within ~1–3 px of OPAX. The radii came out 1448–1453 px depending on the threshold, against OPAX 1441/1444.

`opax_stitch.py` maps a lens-square pixel to a file pixel as `(p + offset) · scale`, plus the half's x origin. Its layouts (`--layout`, guessed from the image size if omitted):

| layout | file | half width | offset | scale |
|---|---|---|---|---|
| `jpeg` | 5792×2896 camera JPEG | 2896 | (0, 0) | 1 |
| `rawhalf` | 2912×1448 half-size raw TIFF (raw2dng/dcraw `-h`) | 1456 | (7.42, −0.14) | 0.5 |
| `raw` | 5824×2896 full-size demosaiced raw | 2912 | (7.42, −0.14) | 1 |

## Open questions

- Which JPEG half is Left. Half 0's fitted circle is ~3 px larger than half 1's, and LeftRadius − RightRadius = 3.3, which is moderate evidence that JPEG half 0 = OPAX Left. Not verified. The tools assume half 0 = Left; `--swap` exchanges them.
- Which physical lens (front or rear) is Left. Not verified.
- The units of DiffX, DiffY and DiffRollAngle. My guess is a pixel offset (2896 scale) between the two lenses' axes and a relative roll in degrees. At 12.98 px/deg, 4.63 / 7.43 px would be 0.36° / 0.57°. DiffRollAngle 1.256 doesn't match the roll of ≈ +0.25° measured from indoor scenes if it's in degrees.
- The camera's stitcher ignores the Diff fields and estimates the lens-to-lens alignment from image content on every shot (`GlobeStitcher::PreACModuleCalculation`, the "AC" auto-calibration, with `findPoints` feature matching at the seam and Ceres). It then applies a seam mesh warp (`Renderer::ResetSphereWarpData` / `CorrectSphereWarpData`). The internals of these steps aren't decoded.

The disassembly came from `tools/disasm.py` (Capstone and pyelftools) run on `libdi-alg-imagestitch.so` from the R210 firmware. Run it on your own copy to check the functions named above.

Source: [Lens calibration ("OPAX") is embedded in every photo](lab-notebook.md#lens-calibration-opax-is-embedded-in-every-photo-2026-10-10), [`st util dump`: pref + lens EEPROM dump](lab-notebook.md#st-util-dump-pref--lens-eeprom-dump-2026-10-10), [OPAX decoded from the stitcher library, offline](lab-notebook.md#opax-decoded-from-the-stitcher-library-offline-2026-10-11), [`main_init`: EEPROM record → GL opax](lab-notebook.md#main_init-eeprom-record--gl-opax-verified), [The lens model is OCamCalib (Scaramuzza), verified](lab-notebook.md#the-lens-model-is-ocamcalib-scaramuzza-verified), [Meaning of the 15 EEPROM values: all named](lab-notebook.md#meaning-of-the-15-eeprom-values-all-named-verified), [What this gives us for stitching](lab-notebook.md#what-this-gives-us-for-stitching), [Stitching from the decoded lens model: first tests](lab-notebook.md#stitching-from-the-decoded-lens-model-first-tests-2026-10-11)
