#!/usr/bin/env python3
"""Explore the Gear 360 A7 / T-Kernel RTOS image (firmware/bin/unpacked/chunk-05.bin) without symbols.

The image is plain ARM code + data loaded at 0x80000000 (found by matching literal-pool words against string
offsets: 0x80000000 was the clear peak; the file starts with an ARM vector table). There are no symbols, so
functions are found heuristically (nearest preceding `push {..., lr}`) and labelled by the first
`Class::method`-looking string they reference.

Commands:
  refs TEXT|0xADDR   code that references a string (exact match of a NUL-terminated string containing TEXT)
                     or an address, via ARM `ldr rX, [pc, #n]` literal pools or movw/movt pairs
  func 0xADDR        disassemble the function containing ADDR, annotating literals, strings and bl targets
  imm VALUE          instructions that load VALUE as an immediate (mov / movw / cmp), e.g. imm 0x702
  callers 0xADDR     ARM bl/blx call sites to the function at ADDR

Examples:
  python3 tools/a7disasm.py refs capExposure
  python3 tools/a7disasm.py func 0x80123456
  python3 tools/a7disasm.py imm 0x702
"""
import argparse
import re
import struct
import sys

import capstone
import numpy as np

IMAGE = 'firmware/bin/unpacked/chunk-05.bin'
BASE = 0x80000000


class Image:
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        n = len(self.data) // 4 * 4
        self.words = np.frombuffer(self.data[:n], '<u4')
        self.addrs = BASE + np.arange(len(self.words), dtype=np.int64) * 4
        self.md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        self.md.detail = True
        self._labels = {}

    def word(self, addr):
        off = addr - BASE
        if 0 <= off <= len(self.data) - 4:
            return struct.unpack_from('<I', self.data, off)[0]
        return None

    def cstring(self, addr):
        off = addr - BASE
        if not 0 <= off < len(self.data):
            return None
        end = self.data.find(b'\0', off, off + 300)
        if end <= off:
            return None
        s = self.data[off:end]
        if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10, 13) for c in s):
            return s.decode()
        return None

    def find_strings(self, text):
        """Addresses of NUL-terminated strings containing text."""
        out = []
        for m in re.finditer(re.escape(text.encode()), self.data):
            start = self.data.rfind(b'\0', 0, m.start()) + 1
            if start + BASE not in out:
                out.append(start + BASE)
        return out

    def ldr_literal_targets(self):
        """For every ARM `ldr rX, [pc, #+-imm12]` word: (instruction address, literal address)."""
        w = self.words
        m = (w & 0x0F7F0000) == 0x051F0000
        idx = np.nonzero(m)[0]
        imm = (w[idx] & 0xFFF).astype(np.int64)
        up = (w[idx] >> 23) & 1
        lit = self.addrs[idx] + 8 + np.where(up == 1, imm, -imm)
        return self.addrs[idx], lit

    def refs_to(self, target):
        """Instruction addresses that load `target` (literal pool or movw/movt pair)."""
        ins, lit = self.ldr_literal_targets()
        ok = (lit >= BASE) & (lit < BASE + len(self.words) * 4)
        ins, lit = ins[ok], lit[ok]
        vals = self.words[((lit - BASE) // 4).astype(np.int64)]
        hits = list(ins[vals == target])
        # movw rD, #lo ... movt rD, #hi within a few instructions
        w = self.words
        lo, hi = target & 0xFFFF, target >> 16
        movw = np.nonzero(((w & 0x0FF00000) == 0x03000000) & ((((w >> 4) & 0xF000) | (w & 0xFFF)) == lo))[0]
        for i in movw:
            rd = (w[i] >> 12) & 0xF
            for j in range(i + 1, min(i + 8, len(w))):
                x = w[j]
                if (x & 0x0FF00000) == 0x03400000 and ((x >> 12) & 0xF) == rd \
                        and ((((x >> 4) & 0xF000) | (x & 0xFFF)) == hi):
                    hits.append(int(self.addrs[i]))
                    break
        return sorted(int(h) for h in hits)

    def func_start(self, addr, limit=0x4000):
        """Nearest preceding ARM push {..., lr} (stmdb sp!, {...lr})."""
        a = addr & ~3
        while a >= BASE and addr - a < limit:
            x = self.word(a)
            if x is not None and (x & 0xFFFF4000) == 0xE92D4000:
                return a
            a -= 4
        return None

    def label(self, start):
        """First Class::method-like string referenced in the first 0x400 bytes of a function."""
        if start in self._labels:
            return self._labels[start]
        name = None
        movw = {}
        for ins in self.md.disasm(self.data[start - BASE:start - BASE + 0x400], start):
            if ins.mnemonic.startswith('pop') and 'pc' in ins.op_str:
                break
            ops = ins.operands
            if ins.mnemonic == 'movw' and len(ops) == 2:
                movw[ops[0].reg] = ops[1].imm & 0xFFFF
            elif ins.mnemonic == 'movt' and len(ops) == 2 and ops[0].reg in movw:
                s = self.cstring(((ops[1].imm & 0xFFFF) << 16) | movw.pop(ops[0].reg))
                if s and re.search(r'\w+::~?\w+', s):
                    name = re.search(r'[\w:~<>]+::~?\w+', s).group(0)
                    break
                if s and name is None and re.fullmatch(r'[A-Za-z_]\w{3,}', s):
                    name = s   # bare function-name string (__FUNCTION__ passed to a logger)
            if ins.mnemonic == 'ldr' and len(ops) == 2 and ops[1].type == capstone.arm.ARM_OP_MEM \
                    and ops[1].mem.base == capstone.arm.ARM_REG_PC:
                v = self.word(ins.address + 8 + ops[1].mem.disp)
                s = self.cstring(v) if v else None
                if s and re.search(r'\w+::~?\w+', s):
                    name = re.search(r'[\w:~<>]+::~?\w+', s).group(0)
                    break
        self._labels[start] = name
        return name

    def annotate(self, ins):
        ops = ins.operands
        note = ''
        if ins.mnemonic in ('bl', 'blx', 'b') and ins.op_str.startswith('#'):
            tgt = int(ins.op_str[1:], 16)
            if ins.mnemonic != 'b':
                st = self.func_start(tgt + 4, 8) if self.word(tgt) and (self.word(tgt) & 0xFFFF4000) == 0xE92D4000 \
                    else None
                lab = self.label(st) if st else None
                note = f'  ; -> {lab}' if lab else ''
        if ins.mnemonic.startswith(('ldr', 'vldr')) and len(ops) == 2 and ops[1].type == capstone.arm.ARM_OP_MEM \
                and ops[1].mem.base == capstone.arm.ARM_REG_PC:
            lit = ins.address + 8 + ops[1].mem.disp
            v = self.word(lit)
            if v is not None:
                note = f'  ; =0x{v:08x} ({v})'
                s = self.cstring(v)
                if s:
                    note += f' "{s}"'
        return note

    def disasm_func(self, addr, max_len=0x2000):
        start = self.func_start(addr) or (addr & ~3)
        print(f'=== function @0x{start:08x}  label: {self.label(start)}')
        off = start - BASE
        end_seen = 0
        movw = {}   # register -> low half from a pending movw, to resolve movw/movt address pairs
        for ins in self.md.disasm(self.data[off:off + max_len], start):
            note = self.annotate(ins)
            ops = ins.operands
            if ins.mnemonic == 'movw' and len(ops) == 2:
                movw[ops[0].reg] = ops[1].imm & 0xFFFF
            elif ins.mnemonic == 'movt' and len(ops) == 2 and ops[0].reg in movw:
                v = ((ops[1].imm & 0xFFFF) << 16) | movw.pop(ops[0].reg)
                s = self.cstring(v)
                note = f'  ; =0x{v:08x}' + (f' "{s}"' if s else '')
            print(f'  {ins.address:08x}:  {ins.mnemonic:8s} {ins.op_str}{note}')
            if ins.mnemonic.startswith('pop') and 'pc' in ins.op_str or ins.op_str == 'lr' and ins.mnemonic == 'bx':
                end_seen = ins.address
            # stop at the next prologue after a return
            x = self.word(ins.address + 4)
            if end_seen and ins.address >= addr and x is not None and (x & 0xFFFF4000) == 0xE92D4000:
                break

    def callers(self, target):
        w = self.words
        bl = ((w >> 24) & 0x0F) == 0x0B
        off = (w & 0xFFFFFF).astype(np.int64)
        off = np.where(off & 0x800000, off - 0x1000000, off) * 4
        tgt = self.addrs + 8 + off
        return [int(a) for a in self.addrs[bl & (tgt == target)]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['refs', 'func', 'imm', 'callers'])
    ap.add_argument('arg')
    ap.add_argument('--image', default=IMAGE)
    args = ap.parse_args()
    img = Image(args.image)
    if args.cmd == 'refs':
        if args.arg.startswith('0x'):
            targets = [int(args.arg, 16)]
        else:
            targets = img.find_strings(args.arg)
            if not targets:
                sys.exit(f'no string containing {args.arg!r}')
        for t in targets:
            s = img.cstring(t)
            hits = img.refs_to(t)
            print(f'0x{t:08x} {s!r}: {len(hits)} refs')
            for h in hits:
                st = img.func_start(h)
                lab = img.label(st) if st else None
                print(f'    0x{h:08x}  in func 0x{st or 0:08x} {lab or ""}')
    elif args.cmd == 'func':
        img.disasm_func(int(args.arg, 16))
    elif args.cmd == 'callers':
        t = int(args.arg, 16)
        for a in img.callers(t):
            st = img.func_start(a)
            print(f'0x{a:08x}  in func 0x{st or 0:08x} {img.label(st) if st else ""}')
    else:
        v = int(args.arg, 0)
        w = img.words
        imm16 = ((w >> 4) & 0xF000) | (w & 0xFFF)
        movw = ((w & 0x0FF00000) == 0x03000000) & (imm16 == v)
        # data-processing immediate (mov/cmp/add/orr...): rotated 8-bit immediate
        dp = (w & 0x0E000000) == 0x02000000
        rot = ((w >> 8) & 0xF) * 2
        val8 = (w & 0xFF).astype(np.uint64)
        rimm = ((val8 >> rot.astype(np.uint64)) | (val8 << (32 - rot).astype(np.uint64))) & 0xFFFFFFFF
        dpm = dp & (rimm == v)
        for i in np.nonzero(movw | dpm)[0]:
            a = int(img.addrs[i])
            ins = next(img.md.disasm(img.data[a - BASE:a - BASE + 4], a), None)
            if ins is None:
                continue
            st = img.func_start(a)
            print(f'0x{a:08x}  {ins.mnemonic} {ins.op_str:28s} func 0x{st or 0:08x} {img.label(st) if st else ""}')


if __name__ == '__main__':
    main()
