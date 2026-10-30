#!/usr/bin/env python3
"""Disassemble named functions from an ARM ELF shared library (e.g. libdi-alg-imagestitch.so).

Uses pyelftools for symbols/sections and Capstone for ARM/Thumb disassembly. Annotates:
  - calls (bl/blx) with the target symbol name, including PLT stubs -> imported function names,
  - PC-relative literal loads (ldr rX, [pc, #n] / vldr) with the 32-bit word, float, and any string it points to,
  - the 64-bit value as a double for vldr d-registers.

Examples:
  python3 tools/disasm.py LIB GlobeStitcher::setDefaultOpax
  python3 tools/disasm.py LIB --grep OPAX            # list matching symbols
  python3 tools/disasm.py LIB --xref read_360_OPAX   # list ARM bl/blx call sites to a function (direct or via PLT)
"""
import argparse
import bisect
import struct
import sys

import capstone
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def load(path):
    f = open(path, 'rb')
    elf = ELFFile(f)
    data = open(path, 'rb').read()
    syms = {}
    for secname in ('.dynsym', '.symtab'):
        sec = elf.get_section_by_name(secname)
        if not sec:
            continue
        for s in sec.iter_symbols():
            if s['st_value'] and s['st_info']['type'] in ('STT_FUNC', 'STT_OBJECT'):
                syms[s.name] = (s['st_value'], s['st_size'], s['st_info']['type'])
    return elf, data, syms


def demangle_all(names):
    import subprocess
    out = subprocess.run(['c++filt'], input='\n'.join(names), capture_output=True, text=True).stdout.splitlines()
    return dict(zip(names, out)) if len(out) == len(names) else {n: n for n in names}


def vaddr_to_off(elf, addr):
    for seg in elf.iter_segments():
        if seg['p_type'] == 'PT_LOAD' and seg['p_vaddr'] <= addr < seg['p_vaddr'] + seg['p_filesz']:
            return addr - seg['p_vaddr'] + seg['p_offset']
    return None


def arm_imm(ops):
    """Immediate of an ARM data-processing op. Capstone gives rotated immediates as two operands (value, rotation)."""
    v = ops[2].imm & 0xffffffff
    if len(ops) == 4 and ops[3].type == capstone.arm.ARM_OP_IMM:
        r = ops[3].imm % 32
        v = ((v >> r) | (v << (32 - r))) & 0xffffffff
    return v


def plt_names(elf):
    """Map PLT stub addresses to imported symbol names.

    Stubs vary in length, so each stub is decoded (add ip, pc, #a / add ip, ip, #b / ldr pc, [ip, #c]!) to find
    the GOT slot it jumps through; that slot is matched to its .rel.plt relocation, which names the symbol.
    """
    names = {}
    plt = elf.get_section_by_name('.plt')
    relplt = elf.get_section_by_name('.rel.plt')
    if not plt or not isinstance(relplt, RelocationSection):
        return names
    dynsym = elf.get_section(relplt['sh_link'])
    got_to_name = {rel['r_offset']: dynsym.get_symbol(rel['r_info_sym']).name for rel in relplt.iter_relocations()}
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    md.detail = True
    stub_start = None
    ip = None
    for ins in md.disasm(plt.data(), plt['sh_addr']):
        ops = ins.operands
        if ins.mnemonic == 'add' and len(ops) >= 3 and ops[0].reg == capstone.arm.ARM_REG_IP \
                and ops[1].reg == capstone.arm.ARM_REG_PC and ops[2].type == capstone.arm.ARM_OP_IMM:
            stub_start = ins.address
            ip = ins.address + 8 + arm_imm(ops)
        elif ins.mnemonic == 'add' and ip is not None and len(ops) >= 3 and ops[0].reg == capstone.arm.ARM_REG_IP \
                and ops[2].type == capstone.arm.ARM_OP_IMM:
            ip += arm_imm(ops)
        elif ins.mnemonic == 'ldr' and ip is not None and ops[0].reg == capstone.arm.ARM_REG_PC \
                and ops[1].type == capstone.arm.ARM_OP_MEM:
            got = ip + ops[1].mem.disp
            if got in got_to_name:
                names[stub_start] = got_to_name[got]
            ip = None
    return names


def cstring(data, off):
    if off is None or off < 0 or off >= len(data):
        return None
    end = data.find(b'\0', off, off + 200)
    if end <= off:
        return None
    s = data[off:end]
    if all(32 <= c < 127 or c in (9, 10, 27) for c in s) and len(s) >= 3:
        return s.decode().replace("\x1b[32m", "").replace("\x1b[0m", "")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lib')
    ap.add_argument('names', nargs='*', help='demangled or mangled function names')
    ap.add_argument('--grep', help='list symbols whose demangled name contains this')
    ap.add_argument('--xref', help='list ARM-mode bl/blx call sites to this function (demangled-name prefix match)')
    args = ap.parse_args()

    elf, data, syms = load(args.lib)
    dm = demangle_all(list(syms))
    if args.grep:
        for mangled, (addr, size, typ) in sorted(syms.items(), key=lambda kv: kv[1][0]):
            if args.grep.lower() in dm[mangled].lower():
                print(f'0x{addr:08x} {size:6d} {typ:10s} {dm[mangled]}')
        return
    by_addr = sorted((v[0] & ~1, dm[k]) for k, v in syms.items())
    addrs = [a for a, _ in by_addr]
    plts = plt_names(elf)

    def name_at(a):
        if a in plts:
            return plts[a] + '@plt'
        i = bisect.bisect_right(addrs, a) - 1
        if i >= 0 and by_addr[i][0] == a:
            return by_addr[i][1]
        return None

    if args.xref:
        want = args.xref
        targets = {v[0] & ~1 for k, v in syms.items() if dm[k] == want or k == want or dm[k].startswith(want + '(')}
        targets |= {a for a, n in plts.items() if n in syms and (dm[n] == want or dm[n].startswith(want + '('))}
        if not targets:
            sys.exit(f'no symbol {want!r} (try --grep)')
        text = elf.get_section_by_name('.text')
        base, tdata = text['sh_addr'], text.data()
        print(f'targets: {", ".join(hex(t) for t in sorted(targets))}', file=sys.stderr)
        for i in range(0, len(tdata) - 3, 4):
            w = struct.unpack_from('<I', tdata, i)[0]
            # ARM BL (cond 1011) or BLX imm (1111 101H): 24-bit signed word offset from pc+8
            if (w >> 24) & 0x0f == 0x0b or (w >> 25) == 0x7d:
                off = (w & 0xffffff) << 2
                if off & 0x2000000:
                    off -= 0x4000000
                if (w >> 25) == 0x7d:
                    off += ((w >> 24) & 1) << 1
                tgt = (base + i + 8 + off) & 0xffffffff
                if tgt in targets:
                    a = base + i
                    j = bisect.bisect_right(addrs, a) - 1
                    caller = by_addr[j][1] if j >= 0 else '?'
                    print(f'0x{a:08x}  in {caller}+0x{a - by_addr[j][0]:x}')
        return

    for want in args.names:
        matches = [k for k in syms if dm[k] == want or k == want or dm[k].startswith(want + '(')]
        if not matches:
            sys.exit(f'no symbol {want!r} (try --grep)')
        for mangled in matches:
            addr, size, _ = syms[mangled]
            thumb = addr & 1
            start = addr & ~1
            off = vaddr_to_off(elf, start)
            code = data[off:off + size]
            md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB if thumb else capstone.CS_MODE_ARM)
            md.detail = True
            print(f'\n=== {dm[mangled]}  @0x{start:08x}  size {size}  ({"Thumb" if thumb else "ARM"})')
            lit_regs = {}   # register -> literal word loaded from the pool (for PIC 'add rX, pc, rX' resolution)
            for ins in md.disasm(code, start):
                note = ''
                if ins.mnemonic in ('bl', 'blx', 'b') and ins.op_str.startswith('#'):
                    tgt = int(ins.op_str[1:], 16)
                    n = name_at(tgt)
                    if n:
                        note = f'  ; -> {n}'
                ops = ins.operands
                is_mem = len(ops) == 2 and ops[1].type == capstone.arm.ARM_OP_MEM
                if ins.mnemonic.startswith(('ldr', 'vldr')) and is_mem and ops[1].mem.base == capstone.arm.ARM_REG_PC:
                    pc = (ins.address + (4 if thumb else 8)) & ~3
                    lit = pc + ops[1].mem.disp
                    loff = vaddr_to_off(elf, lit)
                    if loff is not None:
                        w = struct.unpack_from('<I', data, loff)[0]
                        fl = struct.unpack_from('<f', data, loff)[0]
                        note = f'  ; [0x{lit:x}] = 0x{w:08x} (float {fl:.6g})'
                        if ins.mnemonic.startswith('vldr') and ins.op_str.startswith('d'):
                            dv = struct.unpack_from('<d', data, loff)[0]
                            note = f'  ; [0x{lit:x}] double {dv:.9g}'
                        s = cstring(data, vaddr_to_off(elf, w))
                        if s:
                            note += f' -> "{s}"'
                        if ops[0].type == capstone.arm.ARM_OP_REG:
                            lit_regs[ops[0].reg] = w
                # PIC address: add rD, pc, rM  (rM holds a pool word) -> rD = word + pc
                if ins.mnemonic == 'add' and len(ops) == 3 and all(o.type == capstone.arm.ARM_OP_REG for o in ops):
                    regs = [o.reg for o in ops]
                    if capstone.arm.ARM_REG_PC in regs[1:]:
                        other = regs[2] if regs[1] == capstone.arm.ARM_REG_PC else regs[1]
                        if other in lit_regs:
                            target = (lit_regs[other] + ins.address + (4 if thumb else 8)) & 0xffffffff
                            s2 = cstring(data, vaddr_to_off(elf, target))
                            note = f'  ; = 0x{target:x}' + (f' -> "{s2}"' if s2 else '')
                print(f'  {ins.address:08x}:  {ins.mnemonic:8s} {ins.op_str}{note}')


if __name__ == '__main__':
    main()
