# Defect pixels (hot and dead pixels)

The raw dump is taken before the camera's defect-pixel correction, so hot pixels that the camera hides in its JPEGs show up in our raws and DNGs. Each camera carries a factory list of its bad pixels, and this page covers how to read it.

## What we saw

A single red hot pixel shows up in the raw of 360_0417 at x 5387, y 2014 (full dump coordinates, top-left origin; right-hand lens, column 2475). It is not in the camera's JPEG of the same shot. Across our 35 raw dumps it is bright in 34.

Our raws carry many more. A pixel that stands out from its eight same-colour neighbours by more than 480 (16-bit units) in at least half of the 35 raws counts as persistently hot. There are 3,460 of those: 1,776 in the left half and 1,684 in the right, 1,264 red, 1,605 green and 591 blue. Only one persistent dead pixel turned up, but that test is weak.

## The factory tables

`st util dump` writes `/mnt/mmc/dump.tgz` (see [commands.md](commands.md)). Inside it, `tmp/adj_dpc.bin` (5,246,976 bytes on our camera) is the factory `adj_dpc` partition. The factory process log (`dfmstool -l`) lists a `SCAM_DEFECT_PIXEL` step. The file holds 16 tables:

| Table | Defects on our unit | Frame |
|---|---|---|
| FRONT_LV1 / LV2 / LV3 | 6,653 / 82,867 / 285,216 | left half of the raw dump (sensor A) |
| REAR_LV1 / LV2 / LV3 | 6,838 / 87,301 / 265,133 | right half of the raw dump (sensor B) |
| UD_LENS1 / UD_LENS2, QHD, FHD, FPS120, FRONT_CROP_LENS1 / LENS2, REAR_CROP_LENS1 / LENS2 | 1,361 to 39,422 each | video and crop modes (per lens) |

The six still tables use each lens's own 2912×2896 grid, top-left origin, with no offset or flip: a FRONT entry at column c is dump x = c, a REAR entry is dump x = 2912 + c. The REAR = right-half mapping is verified by the hot pixel above, which is in REAR_LV1, LV2 and LV3 at (2475, 2014) and in no FRONT table. FRONT = left half rests on the match below. The firmware's table writer (`AdjustDefectPixelEachMode` 0x803a6c5c) defines exactly 15 modes (2..16): 6 still tables, 2 4K UHD ("ud") tables, 3 video modes (QHD, FHD, 120fps), and 4 per-lens crop tables ("frontCrop 1/2", "RearCrop 1/2"). On our camera's flash partition, 16 table headers appear because an extra `FRONT_CROP_LENS1` header was copied before `FRONT_CROP_LENS2`.

### Format

Found by disassembling the camera's own table writer in the A7 firmware (`chunk-05.bin`, loaded at 0x80000000): the defect search at 0x803f0598 and the bit packer at 0x803efc50. It is confirmed by the decoded tables themselves: every still table gives rows 0–2895 and columns 0–2911, columns strictly increase within each row, and the lists match the hot pixels we measured.

- Header (80 bytes): magic `0x10654321`, a word `0x02000d0d` whose two 0x0d bytes are the column and row field widths (13 bits), and the defect count N twice.
- Payload: starts 0x48 bytes after the `0x02000d0d` word. It is uint32 little-endian words read MSB first (bit 31 of the first word first).
- Entries are sorted by row, then column. A 0 bit starts a new row: 13-bit row, then 13-bit column. A 1 bit means same row as the entry before: 13-bit column only. The stream ends with a run of 1 bits.
- An index at 0x200 holds (80 + 16·N, N) pairs per table, i.e. the table's size in the camera's memory (16 bytes per defect there) and its count.

Not understood, and not needed for decoding: the leading count words in each header (990, 1010, 270, 534, …), and two 0 bits inside the end padding of some tables. The two FRONT_CROP tables have the same count (3,750).

### Decoding

```
python3 tools/dpc_decode.py adj_dpc.bin                     # summary of every table
python3 tools/dpc_decode.py adj_dpc.bin --csv-dir defects   # also defects/defects_<TABLE>.csv
```

Each CSV has `x_in_table, y_in_table, x_full_dump, bayer`. The last two are only filled in for the six still tables.

## How well the tables match real hot pixels

Checked against the 3,460 persistently hot pixels from our 35 raws:

| Table level | Share of the hot pixels it contains |
|---|---|
| LV1 | 62.6% |
| LV2 | 91.6% |
| LV3 | 92.3% |

Of the strongly hot ones (more than 1,600 above their neighbours, 485 pixels), 91% are in LV1. A pixel that is hot in our raws is about 3,400 times more likely to be in LV1 than to be outside every table.

## The three levels
 
LV2 is a subset of LV3, but about half of LV1 is not in LV2. Firmware reverse engineering of `AdjustDefectPixelEachMode` (`0x803a6c5c`) and runtime selector `0x803d0e84` in `chunk-05.bin` explains both the origin of these tables and how the camera uses them:
 
1. **Factory test exposures**: All three levels were calibrated at **ISO 1600** ($Av = 0x24 = f/2.2$) at three increasing exposure durations:
   - **LV1**: $Tv = 0x30$ (3.0 EV = **1/8 s**)
   - **LV2**: $Tv = 0x18$ (1.5 EV = **~0.35 s**)
   - **LV3**: $Tv = 0$ (0.0 EV = **1.0 s**)
   
   Longer integration times reveal weaker hot pixels that leak dark current over time, causing the defect count to expand from ~6.7k (LV1) to ~85k (LV2) to ~275k (LV3).
 
2. **Runtime selection rule**: The camera selects the active table per still capture (`CPP_Capture::set_info_DPC` 0x80395950) dynamically based on the shot's ISO and shutter speed:
 
| ISO | Faster than 1/16 s ($Tv \ge 0x40$) | 1/16 s to 1 s ($0 \le Tv < 0x40$) | Longer than 1 s ($Tv < 0$) |
|---|---|---|---|
| Up to ISO 400 | **LV1** | **LV2** | **LV3** |
| ISO 400 to 1600 | **LV2** | **LV3** | **LV3** |
| Above ISO 1600 | **LV3** | **LV3** | **LV3** |
 
*(Sensor temperature is not read by the selector; an unknown mode setting 7 forces an ISO-only ladder).*
 
3. **Empirical dark-frame validation**:
   Tested on a series of 16 dark frames (1/8000 s to 1/6 s, ISO 100 to 6400):
   - At **1/8000 s and 1/60 s (ISO 100)**: Only ~110–130 persistent outliers exist, and **85%–90% are in LV1** (100% of severe outliers at $T=1600$ are in the factory tables).
   - At **1/6 s (ISO 100)**: Dark current integration increases outliers 5× to 627 pixels. **LV2 captures 87.1%** of them, directly validating the 1/16 s threshold where the camera switches from LV1 to LV2.
   - The reference hot pixel at $(5387, 2014)$ scales linearly with ISO gain (+1,984 DN at ISO 100 up to +28,000 DN at ISO 1600) and is completely suppressed (pixel value 0–2) in matching camera JPEGs, confirming that the camera's ISP DPC stage is active and effective on JPEGs.
 
## Using it
 
`raw2dng.py` uses this exact selection matrix: it reads the shot's ISO and shutter speed from EXIF, selects the matching level (LV1, LV2, or LV3) for that shot, and applies defect correction so that output DNGs match the clean camera JPEGs.
 
Source: firmware disassembly and dark-frame validation from October 2026.
