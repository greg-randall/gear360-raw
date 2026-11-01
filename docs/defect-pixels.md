# Defect pixels (hot and dead pixels)

The raw dump is taken before the camera's defect-pixel correction, so hot pixels that the camera hides in its JPEGs show up in our raws and DNGs. Each camera carries a factory list of its bad pixels, and this page covers how to read it.

## What we saw

A single red hot pixel shows up in the raw of 360_0417 at x 5387, y 2014 (full dump coordinates, top-left origin; right-hand lens, column 2475). It is not in the camera's JPEG of the same shot. Across our 35 raw dumps it is bright in 34.

Our raws carry many more. A pixel that stands out from its eight same-colour neighbours by more than 480 (16-bit units) in at least half of the 35 raws counts as persistently hot. There are 3,460 of those: 1,776 in the left half and 1,684 in the right, 1,264 red, 1,605 green and 591 blue. Only one persistent dead pixel turned up, but that test is weak.

## The factory tables

`st util dump` writes `/mnt/mmc/dump.tgz` (see [commands.md](commands.md)). Inside it, `tmp/adj_dpc.bin` (5,246,976 bytes on our camera) is the factory `adj_dpc` partition. The factory process log (`dfmstool -l`) lists a `SCAM_DEFECT_PIXEL` step. The file holds 16 tables:

| Table | Defects on our unit | Frame |
|---|---|---|
| FRONT_LV1 / LV2 / LV3 | 6,653 / 82,867 / 285,216 | left half of the raw dump |
| REAR_LV1 / LV2 / LV3 | 6,838 / 87,301 / 265,133 | right half of the raw dump |
| UD_LENS1 / UD_LENS2, QHD, FHD, FPS120, FRONT_CROP_LENS1 / LENS2, REAR_CROP_LENS1 / LENS2 | 1,361 to 39,422 each | video and crop modes (per lens) |

The six still tables use each lens's own 2912×2896 grid, top-left origin, with no offset or flip: a FRONT entry at column c is dump x = c, a REAR entry is dump x = 2912 + c. The REAR = right-half mapping is verified by the hot pixel above, which is in REAR_LV1, LV2 and LV3 at (2475, 2014) and in no FRONT table. FRONT = left half rests on the match below. The firmware's table writer (`AdjustDefectPixelEachMode` 0x803a6c5c) defines exactly 15 modes (2..16): 6 still tables, 2 4K UHD ("ud") tables, 3 video modes (QHD, FHD, 120fps), and 4 per-lens crop tables ("frontCrop 1/2", "RearCrop 1/2"). On our camera the file has 16 table headers: the 12th and 13th decode to identical coordinate lists (3,750 each), so one is a duplicate copy; `dpc_decode.py` labels it `FRONT_CROP_LENS2_DUP`.

### Format

Found by disassembling the camera's own table writer in the A7 firmware (`chunk-05.bin`, loaded at 0x80000000): the defect search at 0x803f0598 and the bit packer at 0x803efc50. It is confirmed by the decoded tables themselves: every still table gives rows 0–2895 and columns 0–2911, columns strictly increase within each row, and the lists match the hot pixels we measured.

- Header (80 bytes): magic `0x10654321`, a word `0x02000d0d` whose two 0x0d bytes are the column and row field widths (13 bits), and the defect count N twice.
- Payload: starts 0x48 bytes after the `0x02000d0d` word. It is uint32 little-endian words read MSB first (bit 31 of the first word first).
- Entries are sorted by row, then column. A 0 bit starts a new row: 13-bit row, then 13-bit column. A 1 bit means same row as the entry before: 13-bit column only. The stream ends with a run of 1 bits.
- An index at 0x200 holds (80 + 16·N, N) pairs per table, i.e. the table's size in the camera's memory (16 bytes per defect there) and its count.

Not understood, and not needed for decoding: the leading count words in each header (990, 1010, 270, 534, …), and two 0 bits inside the end padding of some tables.

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

LV2 is a subset of LV3, but about half of LV1 is not in LV2. Two places in the A7 firmware (`chunk-05.bin`) explain where the levels come from and how the camera uses them.

**Factory test exposures.** The factory routine `AdjustDefectPixelEachMode` (0x803a6c5c) sets the exposure and then runs the defect search, once per level, all at ISO 1600 and f/2.2:

| Level | Requested exposure (APEX Tv) |
|---|---|
| LV1 | 1/8 s (Tv 0x30) |
| LV2 | about 0.35 s (Tv 0x18) |
| LV3 | 1 s (Tv 0) |

A longer exposure lets weaker hot pixels build up enough charge to be caught, which fits the counts growing from LV1 to LV3. Two things don't fit neatly yet. The firmware's own sensor driver caps every still exposure at about 1/6 s ([exposure.md](exposure.md)), so the LV2 and LV3 factory shots may not have run as long as requested; whether the factory line used another path is unknown. And why half of LV1 is missing from LV2 isn't explained: the detection rules themselves (0x803ef2dc, 0x803ef9d0) aren't decoded.

**Runtime selection.** For each still, `CPP_Capture::set_info_DPC` (0x80395950) picks a level through the selector at 0x803d0e84 from the shot's ISO and shutter speed (APEX Sv and Tv; reading those two inputs as ISO and shutter is inferred from how they are used):

| ISO | 1/16 s or faster | slower than 1/16 s, up to 1 s | longer than 1 s |
|---|---|---|---|
| up to 400 | LV1 | LV2 | LV3 |
| 400 to 1600 | LV2 | LV3 | LV3 |
| above 1600 | LV3 | LV3 | LV3 |

Sensor temperature is not an input. When an unidentified mode setting (settings id 0x6f) equals 7, the selector ignores the shutter speed and uses ISO only (LV1 up to ISO 400, LV2 below ISO 6400, LV3 above).

**Dark frames.** A series of 16 dark frames (lenses covered, 1/8000 s to 1/6 s, ISO 100 to 6400) agrees with this:
- At 1/8000 s and 1/60 s, ISO 100, there are about 110-130 persistent outliers, and 85-90% of them are in LV1, including every strong one.
- At 1/6 s, ISO 100, the outliers grow about fivefold to 627, and LV2 holds 87% of them. That matches the camera switching from LV1 to LV2 at 1/16 s.
- The confirmed hot pixel at (5387, 2014) rises with ISO, from about 2,000 above black at ISO 100 to about 28,000 at ISO 1600, and is gone in the camera's JPEGs.

## Using it

`raw2dng.py` corrects defects by default (`--dpc auto`). It reads the shot's ISO and shutter speed from the camera JPEG next to the raw, picks the level with the table above (LV2 if the JPEG or its tags are missing), and replaces each listed pixel with the median of its 8 same-colour neighbours before writing the DNG. Fixing the data itself, not adding a DNG bad-pixel opcode, means every converter sees clean data, including dcraw and libraw, which ignore DNG opcodes.

It needs your camera's own `adj_dpc.bin` (from `st util dump`; the tables are per unit). Put it next to the raws or in the working directory, or pass it:

```
python3 tools/raw2dng.py 360_NNNN.raw --dpc-tables path/to/adj_dpc.bin   # auto level
python3 tools/raw2dng.py 360_NNNN.raw --dpc lv3                          # force a level
python3 tools/raw2dng.py 360_NNNN.raw --dpc none                         # leave the data untouched
```

Without the file it prints a warning and writes the DNG uncorrected.

Checked on our raws: with `--dpc none` the DNG data is identical to the dump; with `--dpc auto` only pixels on the chosen list change. The hot pixel above goes from 6,464 to 4,320 against a neighbour median of 4,288, and on a 1/6 s dark frame (LV2) the listed pixels drop from 37 above black on average to 0, against 0.9 for unlisted pixels.

Source: firmware disassembly and dark-frame tests, October 2026; the notebook's [`st util dump` section](lab-notebook.md#st-util-dump-pref--lens-eeprom-dump-2026-10-10).
