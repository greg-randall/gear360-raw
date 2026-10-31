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
| UD_LV1 / LV2, QHD, FHD, FPS120, FRONT_CROP_LV1 / LV2, a fourth crop table, REAR_CROP_LV1 / LV2 | 1,361 to 39,422 each | video and crop modes, not mapped |

The six still tables use each lens's own 2912×2896 grid, top-left origin, with no offset or flip: a FRONT entry at column c is dump x = c, a REAR entry is dump x = 2912 + c. The REAR = right-half mapping is verified by the hot pixel above, which is in REAR_LV1, LV2 and LV3 at (2475, 2014) and in no FRONT table. FRONT = left half rests on the match below. The names of the ten other tables come from their order in the file and are partly guessed; their coordinates are in video or crop frames we haven't mapped.

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

LV2 is a subset of LV3, but about half of LV1 is not in LV2. LV1 is small and holds most of the strongly hot pixels; LV2 and LV3 are large and mostly hold pixels too weak for us to see. What the levels mean is not known yet. Two explanations fit:

- They come from different factory tests: LV1 from a dark frame (where hot pixels stand out), LV2 and LV3 from a lit flat field at two thresholds. That would explain why LV1 doesn't nest inside LV2.
- The camera picks a level by shooting conditions, correcting more pixels at higher gain, longer exposure or higher temperature. This is common in camera processors, but a plain ladder of thresholds would normally nest.

Which level the camera applies to its own JPEGs, and when, is open. The code that reads the tables would show it, and a dark-frame series (lenses covered, ISO 100 to maximum, raw and JPEG) would show it on the camera.

## Using it

Today raw2dng does not use the tables. A DNG can carry a bad-pixel list (the `FixBadPixelsList` opcode) that raw converters apply, or the pixels can be filled in before the DNG is written. LV2 covers about 92% of the hot pixels we measured, so it looks like the sensible default; that choice is ours, not the camera's.

Source: decoding and validation from 2026-10-30, after the notebook's [`st util dump` section](lab-notebook.md#st-util-dump-pref--lens-eeprom-dump-2026-10-10).
