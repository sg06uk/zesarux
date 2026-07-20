#!/usr/bin/env python3
"""Build euler4.tap: Project Euler #4 -- the largest palindrome that is the
product of two 3-digit numbers (answer 906609 = 913 x 993) -- solved two ways
and timed.

  opcode   : TWO opcodes per candidate -- mull (ED C3) for the 16x16->32 product
             and ispal (ED CA) for the decimal-palindrome test (Carry = yes).
  software : the identical search with a shift-and-add 16x16->32 multiply and a
             hand-written decimal palindrome (repeated 32-bit /10 to extract the
             digits, then compare ends inwards).

Both walk the same pruned search (a from 999 down, b from 999 down to a, break
the inner loop as soon as a*b <= best), so the race is like-for-like.

    python3 make-euler4-tap.py [out.tap]        (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "euler4.tap")

# 60004 best(4) | 60008 a(2) | 60010 b(2) | 60012 p(4) | 60016 temp(4)
# 60020 digits(8) | 60032 rem(2)  [div10 scratch -- must NOT overlap digits]
_HEAD = """        org 0
        ld hl,0
        ld (60004),hl
        ld (60006),hl
        ld hl,999
        ld (60008),hl
aloop:  ld hl,(60008)
        ld de,100
        or a
        sbc hl,de
        jp c,adone
        ld hl,999
        ld (60010),hl
bloop:  ld hl,(60010)
        ld de,(60008)
        or a
        sbc hl,de
        jp c,nexta
"""
_MID = """        ld hl,(60004)
        ld de,(60012)
        or a
        sbc hl,de
        ld hl,(60006)
        ld de,(60014)
        sbc hl,de
        jp nc,nexta
"""
_TAIL = """        jp nc,bnext
        ld hl,(60012)
        ld (60004),hl
        ld hl,(60014)
        ld (60006),hl
bnext:  ld hl,(60010)
        dec hl
        ld (60010),hl
        jp bloop
nexta:  ld hl,(60008)
        dec hl
        ld (60008),hl
        jp aloop
adone:  ret
"""

MUL_OP = """        ld hl,(60008)
        ld de,(60010)
        defb 0xED,0xC3
        ld (60012),hl
        ld (60014),de
"""
PAL_OP = """        ld hl,(60012)
        ld de,(60014)
        defb 0xED,0xCA
"""
MUL_SW = """        ld bc,(60008)
        ld de,(60010)
        ld hl,0
        ld a,16
mlp:    add hl,hl
        rl e
        rl d
        jr nc,mna
        add hl,bc
        jr nc,mna
        inc de
mna:    dec a
        jr nz,mlp
        ld (60012),hl
        ld (60014),de
"""
PAL_SW = """        call spal
"""
_SPAL = """
spal:   ld hl,(60012)
        ld (60016),hl
        ld hl,(60014)
        ld (60018),hl
        ld c,0
sdig:   call div10
        push af
        ld a,c
        ld e,a
        ld d,0
        ld hl,60020
        add hl,de
        pop af
        ld (hl),a
        inc c
        ld hl,(60016)
        ld a,h
        or l
        ld b,a
        ld hl,(60018)
        ld a,h
        or l
        or b
        jr nz,sdig
        ld hl,60020
        push hl
        ld a,c
        dec a
        ld e,a
        ld d,0
        add hl,de
        ex de,hl
        pop hl
        ld a,c
        srl a
        jr z,syes
        ld b,a
scmp:   ld a,(de)
        cp (hl)
        jr nz,sno
        inc hl
        dec de
        djnz scmp
syes:   scf
        ret
sno:    or a
        ret

div10:  ld hl,0
        ld (60032),hl
        ld b,32
d10l:   ld hl,60016
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,(60032)
        adc hl,hl
        ld de,10
        or a
        sbc hl,de
        jr c,d10n
        ld (60032),hl
        ld a,(60016)
        or 1
        ld (60016),a
        jr d10x
d10n:   add hl,de
        ld (60032),hl
d10x:   djnz d10l
        ld a,(60032)
        ret
"""

ASM_OP = _HEAD + MUL_OP + _MID + PAL_OP + _TAIL
ASM_SW = _HEAD + MUL_SW + _MID + PAL_SW + _TAIL + _SPAL

def assemble(src, org=0):
    src = src.replace("        org 0\n", "        org %d\n" % org, 1)
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "r.asm"), "w").write(src)
        r = subprocess.run(["z80asm", "-b", "-or.bin", "r.asm"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"z80asm failed:\n{r.stdout}{r.stderr}")
        b = list(open(os.path.join(d, "r.bin"), "rb").read())
        return b[org:] if len(b) > org > 0 else b

PROG = 23755
_l1, _l2 = len(assemble(ASM_OP)), len(assemble(ASM_SW))
USR_OPCODE = PROG + 5
USR_SOFT = PROG + (4 + 1 + _l1 + 1) + 5
OPCODE, SOFT = assemble(ASM_OP, USR_OPCODE), assemble(ASM_SW, USR_SOFT)
assert len(OPCODE) == _l1 and len(SOFT) == _l2, "size shifted between passes"

TOK = {'REM':0xEA,'RANDOMIZE':0xF9,'USR':0xC0,'LET':0xF1,'PEEK':0xBE,'PRINT':0xF5,'INT':0xBA}
def K(*n): return [TOK[x] for x in n]
def num(v): return list(str(v).encode()) + [0x0E,0x00,0x00,v & 0xFF,(v >> 8) & 0xFF,0x00]
def s(t): return list(t.encode())
def peek32(b):
    return (K('PEEK')+num(b)+s('+')+num(256)+s('*(')+K('PEEK')+num(b+1)+s('+')+num(256)+s('*(')
            +K('PEEK')+num(b+2)+s('+')+num(256)+s('*')+K('PEEK')+num(b+3)+s('))'))
def frames():
    return (K('PEEK')+num(23672)+s('+')+num(256)+s('*(')+K('PEEK')+num(23673)+s('+')
            +num(256)+s('*')+K('PEEK')+num(23674)+s(')'))
def line(n, body):
    d = body + [0x0D]
    return [(n>>8)&0xFF, n&0xFF, len(d)&0xFF, (len(d)>>8)&0xFF] + d

prog = []
prog += line(1, K('REM') + OPCODE)
prog += line(2, K('REM') + SOFT)
prog += line(10, K('PRINT')+s('"largest palindrome from"'))
prog += line(20, K('PRINT')+s('"two 3-digit numbers"'))
prog += line(30, K('LET')+s('f=')+frames())
prog += line(40, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(50, K('LET')+s('o=')+frames()+s('-f'))
prog += line(60, K('LET')+s('a=')+peek32(60004))
prog += line(70, K('PRINT')+s('"answer = ";a'))
prog += line(80, K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"'))
prog += line(90, K('LET')+s('f=')+frames())
prog += line(100, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(110, K('LET')+s('w=')+frames()+s('-f'))
prog += line(120, K('LET')+s('b=')+peek32(60004))
prog += line(130, K('PRINT')+s('"software: ";w/')+num(50)+s(';" s (";b;")"'))
prog += line(140, K('PRINT')+s('"opcode ";')+K('INT')+s('(w/o);"x faster"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

plen = len(prog)
header = [0x00] + list(b"EULER4    ") + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
