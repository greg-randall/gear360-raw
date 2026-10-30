#!/usr/bin/env python3
"""Disassemble functions of the Gear 360 camera app (di-camera-app, ARM ELF) by name, light-weight (capstone).

Resolves: PLT calls -> imported symbol names (from .rel.plt), direct calls -> names from the linker map
(res/di-camera-app.map), and literal-pool / movw+movt constants that point into .rodata -> the string there.
Function end = next symbol in the map.

Usage: python3 tools/appdisasm.py NAME_SUBSTRING [...] [--out DIR]
"""
import argparse
import bisect
import os
import re
import struct
import sys

import capstone
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ROOT = 'firmware/bin/unpacked/fs_rootfs/usr/apps/com.samsung.di-camera-app'
BIN, MAP = f'{ROOT}/bin/di-camera-app', f'{ROOT}/res/di-camera-app.map'


def load():
    elf = ELFFile(open(BIN, 'rb'))
    segs = [(s['p_vaddr'], s['p_offset'], s['p_filesz']) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    data = open(BIN, 'rb').read()

    def read(va, n):
        for v, o, sz in segs:
            if v <= va < v + sz:
                return data[o + va - v:o + va - v + n]
        return None
    plt = elf.get_section_by_name('.plt')
    relplt = elf.get_section_by_name('.rel.plt')
    dynsym = elf.get_section_by_name('.dynsym')
    imports = {}
    if isinstance(relplt, RelocationSection):
        # PLT: 20-byte header, then 12-byte entries in .rel.plt order
        for i, r in enumerate(relplt.iter_relocations()):
            imports[plt['sh_addr'] + 20 + 12 * i] = dynsym.get_symbol(r['r_info_sym']).name
    syms = []
    for line in open(MAP, errors='replace'):
        m = re.match(r'\s+0x([0-9a-f]{8,16})\s+(\S+)\s*$', line)
        if m and not m.group(2).startswith('0x'):
            syms.append((int(m.group(1), 16), m.group(2)))
    syms = sorted(set(syms))
    ro = elf.get_section_by_name('.rodata')
    return read, imports, syms, (ro['sh_addr'], ro['sh_addr'] + ro['sh_size'])


def cstr(read, va):
    b = read(va, 200)
    if not b:
        return None
    s = b.split(b'\0')[0]
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return s.decode()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='+')
    ap.add_argument('--out', default='calibration/app_disasm')
    args = ap.parse_args()
    read, imports, syms, (r0, r1) = load()
    addrs = [a for a, _ in syms]
    name_at = {}
    for a, n in syms:
        name_at.setdefault(a, n)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    os.makedirs(args.out, exist_ok=True)
    for want in args.names:
        hits = [(a, n) for a, n in syms if want in n]
        if not hits:
            print(f'{want}: not in map', file=sys.stderr)
            continue
        for a, n in hits:
            k = bisect.bisect_right(addrs, a)
            end = addrs[k] if k < len(addrs) else a + 0x400
            end = min(end, a + 0x2000)
            code = read(a, end - a)
            lines = [f'; {n} @ 0x{a:x} ({end - a} bytes)']
            movw = {}
            for ins in md.disasm(code, a):
                note = ''
                if ins.mnemonic in ('bl', 'b', 'blx') and ins.op_str.startswith('#'):
                    t = int(ins.op_str[1:], 16)
                    note = imports.get(t) or name_at.get(t) or ''
                elif ins.mnemonic == 'ldr' and '[pc, #' in ins.op_str:
                    off = int(re.search(r'#(-?0x[0-9a-f]+|-?\d+)', ins.op_str).group(1), 0)
                    lit = read(ins.address + 8 + off, 4)
                    if lit:
                        v = struct.unpack('<I', lit)[0]
                        s = cstr(read, v) if r0 <= v < r1 else None
                        note = f'=0x{v:x}' + (f' "{s}"' if s else '') + (f' {name_at[v]}' if v in name_at else '')
                elif ins.mnemonic == 'movw':
                    reg, val = ins.op_str.split(', #')
                    movw[reg] = int(val, 0)
                elif ins.mnemonic == 'movt':
                    reg, val = ins.op_str.split(', #')
                    if reg in movw:
                        v = (int(val, 0) << 16) | movw[reg]
                        s = cstr(read, v) if r0 <= v < r1 else None
                        note = f'=0x{v:x}' + (f' "{s}"' if s else '')
                lines.append(f'  {ins.address:08x}: {ins.mnemonic:8s} {ins.op_str:32s} {("; " + note) if note else ""}')
            path = os.path.join(args.out, re.sub(r'[^A-Za-z0-9_]', '_', n)[:120] + '.txt')
            open(path, 'w').write('\n'.join(lines) + '\n')
            print(f'{n}: {len(lines) - 1} instructions -> {path}')


if __name__ == '__main__':
    main()
