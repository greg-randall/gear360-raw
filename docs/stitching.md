# Stitching

The camera saves two unstitched fisheye images per shot, and the RAW dump is the same layout. There are two ways to turn them into an equirectangular panorama: `tools/opax_stitch.py`, which uses the camera's own lens model, or PTGui with the ChArUco-calibrated template in `templates/`.

The lens model itself is described in [lens-model.md](lens-model.md). Getting a raw and a DNG is in [raw-capture.md](raw-capture.md) and [dng-colour.md](dng-colour.md).

## Route 1: opax_stitch.py

`tools/opax_stitch.py` remaps each fisheye with the firmware's OCam polynomial plus the per-unit OPAX centre and affine terms. No lens parameters are fitted. The OPAX values in the script are our unit's (the `OPAX` dict near the top). For another camera, replace them with the values from your own photos' maker note `0x0012`.

It has two commands:

- `solve IMAGE` estimates the small lens-2 rotation correction (yaw, pitch, roll) on top of the nominal 180°. It reprojects both lenses into a strip around the seam circle and phase-correlates tiles. It prints the result as a ready-to-use `--rot Y P R`.
- `stitch IMAGE OUT [--rot Y P R]` renders the panorama.

`--layout` and `--swap` belong to the top-level parser, so they go before the command name:

```
python3 tools/opax_stitch.py --layout raw stitch 360_0384.tif 360_0384_pano.tif --rot -0.14 -0.12 0.16
```

With a camera JPEG the layout is guessed from the size:

```
python3 tools/opax_stitch.py stitch 360_0384.JPG 360_0384_pano.jpg --rot -0.14 -0.12 0.16
```

`--rot -0.14 -0.12 0.16` is the lens-2 correction for our unit from the ChArUco calibration below. 16-bit input gives 16-bit output.

### What stitch does

1. Remaps both lenses to equirectangular with the exact lens model. Lens 2 is rotated by 180° plus `--rot`.
2. Sets each lens's coverage to the inside of its OPAX image-circle radius, minus `--edge-margin` px.
3. Seam gain: takes the per-channel median ratio of the two lenses in the overlap band and splits it evenly between them.
4. Optional `--flow`: computes OpenCV DIS optical flow between the two lenses in a strip around the 90° seam (forward/backward checked, smoothed, clamped). Inside ±band each lens is warped part of the way so a scene point lands in the same place from both sides, which hides near-field parallax.
5. Blends with a multiband Laplacian pyramid (hard seam at 90°), or a linear feather across ±band.

Lens shading correction (below) is applied before the remap unless `--lsc off`.

### Options

Global (before the command):

| flag | default | meaning |
|---|---|---|
| `--layout {jpeg,rawhalf,raw}` | guessed from size | input layout, see [lens-model.md](lens-model.md#image-geometry) |
| `--swap` | off | JPEG half 0 = OPAX Right (default half 0 = Left) |

`stitch IMAGE OUT`:

| flag | default | meaning |
|---|---|---|
| `--rot YAW PITCH ROLL` | 0 0 0 | lens-2 correction in degrees on top of the nominal 180° |
| `--width` | 4096 | output width in px |
| `--blend {multiband,feather}` | multiband | blend method |
| `--band` (alias `--feather`) | 3.0 | seam band half-width in degrees around 90° (feather width, flow warp zone) |
| `--levels` | 0 | multiband pyramid levels (0 = auto from `--band`) |
| `--no-gain` | off | skip seam gain matching |
| `--edge-margin` | 20.0 | px inside the OPAX image-circle radius counted as usable (2896-px units) |
| `--dark` | 0.25 | overlap px below this × median count as unusable |
| `--flow` | off | optical-flow seam warp for near-field parallax |
| `--flow-max` | 3.0 | largest flow kept, degrees |
| `--flow-smooth` | 0.5 | flow smoothing sigma, degrees |
| `--flow-fb` | 0.15 | forward/backward flow mismatch limit, degrees |
| `--lsc {auto,srgb,linear,off}` | auto | Samsung lens-shading correction; auto = srgb for 8-bit JPEGs, linear otherwise |
| `--lsc-strength` | 1.0 | 0 = none, 1 = full Samsung gain |
| `--save-seam FILE` | none | write a debug image of the seam strips and flow (needs `--flow`) |

`solve IMAGE`:

| flag | default | meaning |
|---|---|---|
| `--band` | 11.0 | strip half-height around the seam, degrees |
| `--maxshift` | 3.0 | reject matches further than this from nominal, degrees |
| `--method {tiles,sift}` | tiles | tile phase correlation, or SIFT matching |
| `--tile` | 6.0 | tile width along the seam, degrees |
| `--min-response` | 0.15 | phase-correlation peak threshold |
| `--min-texture` | 2.0 | skip tiles with gradient std below this |
| `--dark` | 0.25 | strip pixels below this × median count as dark/invalid |
| `--verbose` | off | more output |
| `--save-strips FILE` | none | write the two seam strips (stacked) to this image file |
| `--features` | 20000 | SIFT features |
| `--ratio` | 0.75 | SIFT ratio test |
| `--thresh` | 0.3 | RANSAC inlier threshold, degrees |
| `--iters` | 3000 | RANSAC iterations |

SIFT found too few matches in our tests, which is why tiles is the default. `solve` on ordinary indoor scenes doesn't give a usable yaw/pitch; see [Calibrating your own unit](#calibrating-your-own-unit).

## Lens shading

OPAI, the second calibration record, isn't a per-unit shading table. Decompiled from `libdi-alg-imagestitch.so` in Ghidra:

- `ADE_ImageStitch_get_OPAI` builds `{version 3, int from adjust data 0x85c2 offset 800, int from 0x85c4 offset 800, string from vconf}`. Maker note tag `0x0013` holds it: `[3, 0x743 (1859), 0x7ca (1994), "CH80135F5E80174"]` on our unit.
- `GenerateLscInfoRGB(model, value)` fills the coefficients from constants built into the library. Only the first polynomial depends on `value / 100` (< 4, < 13, ≥ 13). On our unit both lenses are ≥ 13.
- Model: RGB gain = per-channel 5th-order polynomial in r, `gain(r) = Σ c[i]·r^i`. `CGL_LSCRender::SetBlendInfo` computes r = 2 × the distance from the lens centre in normalised lens-texture coordinates, so r = 1 at 1448 px in the 2896-px lens square. The image-circle edge is r ≈ 1 and 90° off-axis is r ≈ 0.95. `p_SetGainFront` / `p_SetGainRear` evaluate the polynomials and the gain multiplies the image.

Coefficients c0…c5. The R, G, B order is assumed, not verified:

```
first, value/100 < 4  : 1, 0.357137, -2.68483, 13.6964, -21.9303, 12.4693
first, < 13           : 1, 0.35964,  -2.70365, 13.7924, -22.0839, 12.5566
first, >= 13 (ours)   : 1, 0.325752, -2.37229, 12.7928, -20.9402, 12.1364
second                : 1, 0.314724, -2.18452, 11.8701, -19.2398, 11.0958
third                 : 1, 0.244838, -1.38679,  8.98952, -15.132,   9.083
```

The struct also holds two more 7-float groups whose use isn't decoded.

The gain at r = 0.95 (90°) is 2.47 / 2.42 / 2.39 for R/G/B, so the edge is at about 41% of the centre. At r = 1 it is about 2.9×. Whether Samsung applies it in linear or gamma space isn't decoded; the renderer has gamma/degamma steps.

In `opax_stitch.py`, `--lsc auto` (the default) does sRGB-decode → gain → re-encode for 8-bit JPEGs and a plain multiply for 16-bit input. `--lsc-strength` scales it as gain^strength. The script uses the "≥ 13" first polynomial (`LSC_SET = 'hi'`).

First test, shot 360_0364, with a wall across the left seam (rows 1250–1450 of a 4096-wide pano):

- Without the correction the wall dips from about 101 to 67 at the seam (−34%).
- With the full correction it dips from 130 to 99 (−24%).
- So it helps but doesn't remove the dip. The low point sits about 3.7° past the seam, so part of it may be real light falloff on the wall. This scene can't tell the two apart.

The user's visual verdict on 360_0363 / 0364 was that brightness with the correction is "really pretty good", so `--lsc auto` stays the default. A clean check would be a tripod and a plain, evenly lit wall: one shot with a seam pointing at the wall, one rotated 90° so a lens centre points at the same spot.

`tools/vignette_profile.py` (median brightness against angle over many JPEGs) was dominated by scene content on our photo set (2.6× at 30°) and isn't usable as a vignetting measurement.

## Seam blending choices

With a fixed lens model and a narrow overlap around 90°, blending only hides misalignment. Near-field parallax is the real problem. What we looked at:

- enblend: seam optimisation, but slow and barely maintained.
- multiblend 2.0: much faster than enblend, but no seam optimisation, so moving objects can ghost.
- PTGui's built-in blender: closed source; the vendor claims optimum seam placement.
- OpenCV `cv2.detail` (exposure compensator, graph-cut seam finder, multi-band blender): this was the planned first choice. But `cv2.detail.MultiBandBlender` only takes 8-bit or int16 images, which would drop a bit from 16-bit raw renders, so `opax_stitch.py` has its own small float32 pyramid blend instead.
- Optical-flow seam warping: compute flow across the overlap and warp each side part of the way, then blend. This is how Insta360's "optical flow stitching" handles near and far objects at once. Samsung's `CorrectSphereWarpData` is probably a coarser mesh version of the same idea (inferred). `--flow` does this with OpenCV DIS flow.
- The closest open-source reference is insv-stitch (github.com/BenjaminHenriksson/insv-stitch, MIT, Python, for Insta360 X5 `.insv`). It has a factory lens model with per-lens extrinsics, a coverage-weighted blend, a seam gain correction and an optional DIS optical-flow pass, which is close to our design. Its README says the flow pass "helps but does not match" Insta360's learned model on repetitive patterns.
- Deep stitching (UDIS++) is built for planar image pairs with unknown geometry and doesn't fit a calibrated 360 seam.

The notebook has no recorded test result for `--flow` yet.

## Route 2: PTGui

PTGui opens the DNGs from `tools/raw2dng.py` directly.

`templates/charuco_pooled.pts` is a PTGui project for our unit, built by `tools/charuco_to_pts.py` from ChArUco corner matches pooled over many shots (see below). Both images in it point at `360_0384.dng`; each DNG is the whole dual-fisheye frame and the crop centre picks the lens. Use it as a template for any raw. The calibration shots were all at 5 ft, so the template is exact for that distance, and nearer objects will show some seam parallax.

For a bracket, `tools/make_hdr_pts.py` builds a PTGui HDR project from the template. It adds every bracket frame to both image groups (one per lens), so each group is one bracketed stack, and keeps the lens, lens-2 rotation, crops and settings. It reads exposure time, aperture and ISO for each frame from the DNG's EXIF with exiftool, so exiftool must be installed. The DNGs must all be in one folder and `--out` goes in the same folder:

```
python3 tools/make_hdr_pts.py brackets/360_039[1-5].dng --template templates/charuco_pooled.pts --out "brackets/360_0391 HDR.pts"
```

The exposure time in the DNG is the camera's requested value, and requests longer than about 1/6 s aren't what the sensor got; see [exposure.md](exposure.md).

### PTGui lens numbers

- Our 2021 PTGui template: circular fisheye, HFOV 189.95, crop circle `C9,2879,17,2887` on 2896 halves, image 2 at yaw 179.01 / roll 0.196 / pitch −0.344.
- EXIF says 1.2 mm, 35 mm equivalent 6 mm (crop factor 5.0). The physical 1/2.6" sensor has a 6.83 mm diagonal (crop ≈ 6.3).
- From the OPAX lens model, rho/θ (px per radian) runs from 756 at the centre to ~880 near 85° and 862 at the circle edge (95.7°), so the lens isn't purely equidistant. At 1.34 µm/px that's ≈1.0 mm at the centre and ≈1.15–1.2 mm overall (this assumes no resampling into the 2912 halves; unverified).
- PTGui converts mm and crop factor using the loaded image width, so 1.2 mm needs crop factor ≈4.44 for the 5824-wide DNG, ≈8.93 for a 2896 half and ≈4.47 for the 5792 JPEG. The EXIF 5.0 fits none of them. The simplest fix is to enter HFOV ≈190° and let the optimiser refine it.

## Calibrating your own unit

`--rot -0.14 -0.12 0.16` and `templates/charuco_pooled.pts` are for our camera. Another unit should shoot its own ChArUco set and pool it again.

### Why ordinary scenes don't work

`opax_stitch.py solve` on 54 old indoor JPEGs gave two clusters for the same room: yaw +2.5 / pitch +1.2 and yaw −2.75 / pitch +0.85. Those are dominated by parallax from objects 0.3–1 m away. Roll was consistent at ≈ +0.25°, since parallax moves points across the seam, not along it. So yaw and pitch need a target at a known distance.

### Line grids: unreliable

The first target was a projected line grid (`utils/make_grid.sh`, magenta vertices A1..O8 and green A9..O16, 1920×1080, needs ImageMagick's `convert`). On shots 360_0375–0379 the automatic choice of lattice offset between the two lenses was off by one cell on two shots, which hand-placed PTGui points proved. Don't rely on the grid method.

### ChArUco boards

A ChArUco board is a chessboard whose white squares each hold a unique ArUco marker, so every inner corner has an ID and the two lenses' views match by ID with no offset ambiguity.

- Generate one with `utils/make_charuco.py` (defaults: 1920×1080 screen, 16×9 squares of 120 px, markers 70% of a square, DICT_4X4_250). `--square 96` gives 20×11. It writes a white-on-black and a green-on-black PNG plus a JSON board definition. Ready-made 20×11 and 16×9 boards are in `utils/`.

```
python3 utils/make_charuco.py --out-dir utils --square 96 --self-test
```

- We displayed them on a projector screen at the seam, with the camera at 5 ft, and shot a pair rotated 180° so each seam sees the same board. Both board sizes detected well.
- Detect and solve with `tools/grid_solve.py --charuco BOARD.json` on the camera JPEGs. It renders both lenses into a shared perspective view with the OPAX model, runs OpenCV's ChArUco detector on the green channel, and matches corners by ID. Detections are cached in `--out` as `obs_charuco_<shot>.npz` (`--redetect` to redo); `--detect-only` reports counts without solving.

```
python3 tools/grid_solve.py shots/360_03*.JPG --out charuco_out --charuco utils/charuco_1920x1080_20x11.json
```

Our results:

- A rotation-only fit on the shared corners gave ~0.06–0.10° median residual per shot.
- The mean of the 180° pair gives the lens-2 correction ≈ `--rot -0.14 -0.12 0.16` (yaw, pitch, roll, degrees). Half the difference is ≈ 2.76°, a symmetric seam term that this correction doesn't remove.
- The full screen-plane solve (rotation + lens-2 centre + planes, the default without `--no-translation`) is degenerate: it gave an impossible +9 cm lens offset. Don't use it as-is. `--no-translation` fits rotation only.
- The lens separation, measured front element to front element, is 44.38 mm (45.18 mm minus two 0.4 mm lens cloths). The entrance pupils sit inside, so the true baseline is ≤ 44.38 mm, which caps parallax at ~1.67° at 5 ft. So at least ~1.1° of the 2.76° seam term isn't parallax. It's likely the fisheye model near 90° off-axis, but that's unverified. A second 180° pair at a different distance would separate the two.

Other `grid_solve.py` options: `--swap`, `--robust` (soft-L1 scale, degrees, default 0.1), `--distance` (camera-to-screen distance in metres, sets the scale), `--fixed-distance SHOT,SHOT` with `--distance-sigma` (default 0.1 m), and `--offset SHOT=DU,DV` to force a line-grid shot's lattice offset.

`grid_solve.py` is CPU-heavy. It caps its threads at half the cores by default, because the machine it was written on hard-reset under full load. Set `GRID_SOLVE_THREADS` to change it, e.g. single-threaded:

```
GRID_SOLVE_THREADS=1 python3 tools/grid_solve.py shots/360_03*.JPG --out charuco_out --charuco utils/charuco_1920x1080_20x11.json
```

### Pooling into a PTGui project

`tools/charuco_to_pts.py` takes the `obs_charuco_<shot>.npz` caches and turns every corner seen by both lenses in any shot into one control point. The relation between the lenses is the same in every shot, so all the pairs go on a single image pair, and PTGui fits one lens model and one lens-2 rotation to all of them. Each corner is mapped back to DNG pixels (raw layout, 5824×2896) with the same lens model that produced it, so the model cancels out.

It needs an existing PTGui project for this camera as `--template` (its lens, layout and settings are kept; its control points are replaced and it's marked not optimised). `--image` is the DNG both images point at, relative to `--out`'s folder:

```
python3 tools/charuco_to_pts.py 360_0383 360_0384 360_0385 --cache-dir charuco_out --template "existing.pts" --image 360_0384.dng --out charuco_pooled.pts
```

`--decimals` (default 0) sets the control-point precision. PTGui 12 rejects fractional pixels ("not a number"), and rounding costs ≤ 0.5 px (~0.03° at the seam). `--swap` swaps the halves as elsewhere. Open the result in PTGui and optimise it, then save it as your template.

### Checking a rotation against PTGui points

`tools/ptgui_check.py` maps a PTGui project's control points to rays with the OPAX lens model (so PTGui's own lens fit plays no part) and reports the seam error for the nominal 180° rotation, the best rotation for those points alone, PTGui's own image-2 yaw/pitch/roll under each sign convention, and any `--rot NAME YAW PITCH ROLL` candidates you pass. All results are printed in `opax_stitch --rot` terms. `--layout` defaults to `raw`.

```
python3 tools/ptgui_check.py "my_project.pts" --rot charuco -0.14 -0.12 0.16
```

Source: [Stitching from the decoded lens model: first tests](lab-notebook.md#stitching-from-the-decoded-lens-model-first-tests-2026-10-11), [Seam blending options, researched](lab-notebook.md#seam-blending-options-researched-2026-10-11), [Lens shading (vignetting): Samsung's correction decoded](lab-notebook.md#lens-shading-vignetting-samsungs-correction-decoded-2026-10-11), [Power RAW retest, web UI sizes and preview, grid shots, PTGui lens numbers](lab-notebook.md#power-raw-retest-web-ui-sizes-and-preview-grid-shots-ptgui-lens-numbers-2026-10-11)
