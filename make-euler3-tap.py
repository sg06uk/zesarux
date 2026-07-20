#!/usr/bin/env python3
"""Build euler3.tap: Project Euler #3 -- the largest prime factor of
600851475143 (answer 6857) -- solved two ways and timed.

  opcode   : ONE `factor` instruction (ED C9) on the 40-bit operand; the whole
             factorisation streams out to a buffer and we take the last entry.
  software : trial division in pure Z80 -- a 40-bit/16-bit restoring divide per
             candidate, dividing the cofactor out whenever it divides.

The routines use CALL and long jumps, so they are assembled at the exact address
their REM lands on (two passes: sizes, then real orgs).

    python3 make-euler3-tap.py [out.tap]        (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "euler3.tap")
N = 600851475143
NB = [(N >> (8 * i)) & 0xFF for i in range(5)]

# 60004 largest(4) | 60008 N(8) | 60016 temp(8) | 60024 d(2) | 60026 rem(2) | 60040 out
_SETN = "".join("        ld a,%d\n        ld (%d),a\n" % (NB[i], 60008 + i) for i in range(5))

ASM_OP = """        org 0
""" + _SETN + """        ld hl,60008
        ld a,5
        ld bc,60040
        ld de,16
        defb 0xED,0xC9
        ld h,b
        ld l,c
        ld de,5
        or a
        sbc hl,de
        ld a,(hl)
        ld (60004),a
        inc hl
        ld a,(hl)
        ld (60005),a
        inc hl
        ld a,(hl)
        ld (60006),a
        inc hl
        ld a,(hl)
        ld (60007),a
        ret
"""

ASM_SW = """        org 0
""" + _SETN + """        ld hl,0
        ld (60004),hl
        ld (60006),hl
        ld hl,2
        ld (60024),hl
tloop:  ld a,(60008)
        ld hl,60009
        or (hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        jp z,tdone
        ld a,(60008)
        cp 1
        jr nz,tgo
        ld a,(60009)
        ld hl,60010
        or (hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        jp z,tdone
tgo:    ld hl,(60008)
        ld (60016),hl
        ld hl,(60010)
        ld (60018),hl
        ld a,(60012)
        ld (60020),a
        call sdiv
        ld hl,(60026)
        ld a,h
        or l
        jr nz,tnext
        ld hl,(60024)
        ld (60004),hl
        ld hl,0
        ld (60006),hl
        ld hl,(60016)
        ld (60008),hl
        ld hl,(60018)
        ld (60010),hl
        ld a,(60020)
        ld (60012),a
        jp tloop
tnext:  ld hl,(60024)
        ld a,l
        cp 2
        jr nz,todd
        inc hl
        jr tst
todd:   inc hl
        inc hl
tst:    ld (60024),hl
        ld a,h
        or l
        jp nz,tloop
tdone:  ld a,(60008)
        cp 1
        jr nz,tbig
        ld a,(60009)
        ld hl,60010
        or (hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        ret z
tbig:   ld hl,(60008)
        ld (60004),hl
        ld hl,(60010)
        ld (60006),hl
        ret

sdiv:   ld hl,0
        ld (60026),hl
        ld b,40
sdl:    ld hl,60016
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,(60026)
        adc hl,hl
        ld de,(60024)
        or a
        sbc hl,de
        jr c,sdno
        ld (60026),hl
        ld a,(60016)
        or 1
        ld (60016),a
        jr sdnx
sdno:   add hl,de
        ld (60026),hl
sdnx:   djnz sdl
        ret
"""

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
prog += line(10, K('PRINT')+s('"largest prime factor of"'))
prog += line(20, K('PRINT')+s('"600851475143"'))
prog += line(30, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(40, K('LET')+s('a=')+peek32(60004))
prog += line(50, K('PRINT')+s('"answer = ";a'))
prog += line(60, K('PRINT')+s('"opcode:   1 instruction"'))
prog += line(70, K('PRINT')+s('"  30337 T = ";')+num(30337)+s('/')+num(3500)+s('/')+num(1000)+s(';" s"'))
prog += line(80, K('LET')+s('f=')+frames())
prog += line(90, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(100, K('LET')+s('w=')+frames()+s('-f'))
prog += line(110, K('LET')+s('b=')+peek32(60004))
prog += line(120, K('PRINT')+s('"software: ";w/')+num(50)+s(';" s (";b;")"'))
prog += line(130, K('PRINT')+s('"opcode ";')+K('INT')+s('(w/')+num(50)+s('/(')+num(30337)
                  +s('/')+num(3500)+s('/')+num(1000)+s('));"x faster"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

plen = len(prog)
header = [0x00] + list(b"EULER3    ") + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
