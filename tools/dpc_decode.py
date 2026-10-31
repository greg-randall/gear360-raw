#!/usr/bin/env python3
"""Decode the Gear 360's factory defect-pixel tables (adj_dpc.bin) into CSV lists of bad pixels.

The camera's `st util dump` writes /mnt/mmc/dump.tgz; inside it, tmp/adj_dpc.bin is the factory "adj_dpc" partition.
It holds 16 tables. Each is a bit-packed, sorted list of defect coordinates (format from the camera firmware's own
table writer, see docs/defect-pixels.md):
    header: magic 0x10654321, a 0x02000d0d word (13-bit column and row fields), the defect count N (twice)
    payload: starts 0x48 bytes after the 0x02000d0d word; uint32 little-endian words read MSB-first;
             per entry, bit 0 -> new row: 13-bit row then 13-bit column; bit 1 -> same row: 13-bit column.

The six still-capture tables (FRONT/REAR x LV1/LV2/LV3) use per-lens 2912x2896 coordinates, top-left origin, the same
grid as each half of the raw dump: FRONT = left half (dump x = col), REAR = right half (dump x = 2912 + col).
The names of the other ten tables come from their order and are partly guessed; their coordinate frames are unmapped.

Usage:
  python3 tools/dpc_decode.py adj_dpc.bin                     # summary of every table
  python3 tools/dpc_decode.py adj_dpc.bin --csv-dir defects   # also write defects/defects_<TABLE>.csv
"""
import argparse
import os
import re
import struct
import sys
import time

import numpy as np

# Table names from the A7 firmware (CPP_Preview::set_info_DPC 0x8031a424, AdjustDefectPixelEachMode 0x803a6c5c).
# Modes 2..7 are the 6 still tables; modes 8..16 are video/liveview and per-lens crop modes.
# Note: adj_dpc.bin has 16 FIELD_MARK headers on our unit because FRONT_CROP_LENS1 header is duplicated before LENS2.
NAMES = ['FRONT_LV1', 'FRONT_LV2', 'FRONT_LV3', 'REAR_LV1', 'REAR_LV2', 'REAR_LV3',
         'UD_LENS1', 'UD_LENS2', 'QHD', 'FHD', 'FPS120',
         'FRONT_CROP_LENS1', 'FRONT_CROP_LENS2_DUP', 'FRONT_CROP_LENS2', 'REAR_CROP_LENS1', 'REAR_CROP_LENS2']
STILL_X0 = {'FRONT': 0, 'REAR': 2912}       # dump x offset of each lens half, for the still tables
FIELD_MARK = b'\x0d\x0d\x00\x02' + b'\x00' * 8  # the 0x02000d0d word followed by 8 zero bytes
BAYER = 'GRBG'


def find_tables(data):
    """(payload offset, defect count) for every table, in file order."""
    out = []
    for m in re.finditer(re.escape(FIELD_MARK), data):
        o = m.start()
        n = struct.unpack('<I', data[o + 12:o + 16])[0]
        out.append((o + 0x48, n))
    return out


def decode(data, start, n):
    """Unpack n entries starting at byte offset start; returns rows, cols (int32 arrays)."""
    end = len(data) - (len(data) - start) % 4
    words = np.frombuffer(data[start:end], '<u4')
    bits = np.unpackbits(words.astype('>u4').view(np.uint8))    # MSB-first within each word
    rows = np.empty(n, np.int32)
    cols = np.empty(n, np.int32)
    p, row = 0, 0
    weights = 1 << np.arange(12, -1, -1)
    for i in range(n):
        new_row = bits[p] == 0
        p += 1
        if new_row:
            row = int(bits[p:p + 13] @ weights)
            p += 13
        rows[i] = row
        cols[i] = int(bits[p:p + 13] @ weights)
        p += 13
    return rows, cols


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('adj_dpc', help='adj_dpc.bin from st util dump')
    ap.add_argument('--csv-dir', help='write defects_<TABLE>.csv files into this directory')
    args = ap.parse_args()

    data = open(args.adj_dpc, 'rb').read()
    tables = find_tables(data)
    if len(tables) != len(NAMES):
        print(f'warning: found {len(tables)} tables, expected {len(NAMES)}; names may not line up', file=sys.stderr)
    if args.csv_dir:
        os.makedirs(args.csv_dir, exist_ok=True)
    t0 = time.time()
    for k, (start, n) in enumerate(tables, 1):
        name = NAMES[k - 1] if k <= len(NAMES) else f'TABLE_{k}'
        rows, cols = decode(data, start, n)
        ok = n == 0 or (np.all(np.diff(rows) >= 0) and rows.max() < 8192 and cols.max() < 8192)
        rng = f'rows {rows.min()}-{rows.max()}, cols {cols.min()}-{cols.max()}' if n else 'empty'
        print(f'[{k}/{len(tables)}] {name:15s} {n:7d} defects  {rng}  {"ok" if ok else "CHECK: not sorted by row"}',
              flush=True)
        if args.csv_dir:
            lens = name.split('_')[0]
            x0 = STILL_X0.get(lens) if name.endswith(('LV1', 'LV2', 'LV3')) and 'CROP' not in name else None
            path = os.path.join(args.csv_dir, f'defects_{name}.csv')
            with open(path, 'w') as fh:
                fh.write('x_in_table,y_in_table,x_full_dump,bayer\n')
                for r, c in zip(rows.tolist(), cols.tolist()):
                    xf = '' if x0 is None else x0 + c
                    bayer = '' if x0 is None else BAYER[(r % 2) * 2 + (x0 + c) % 2]
                    fh.write(f'{c},{r},{xf},{bayer}\n')
    print(f'done in {time.time() - t0:.1f}s' + (f'; CSVs in {args.csv_dir}' if args.csv_dir else ''))


if __name__ == '__main__':
    main()
