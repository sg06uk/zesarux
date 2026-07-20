#!/usr/bin/env python3
"""Build euler5.tap: Project Euler #5 -- the smallest number evenly divisible by
all of 1..20 (answer 232792560) -- solved two ways and timed.

Built up as a running LCM:  result = 1;  for k = 2..20:
    g = gcd(result, k)        m = k / g        result = result * m

  opcode   : THREE opcodes per step -- gcd (ED C5) on the 32-bit running value,
             div (ED C6) for k/g, and mul1 (ED CD) to scale the 32-bit accumulator.
  software : the identical recurrence with a 32-bit shift-subtract modulo feeding
             a byte-wise Euclid, repeated-subtraction division, and a 32-bit
             multiply by repeated addition.

One LCM pass is only ~19 steps -- far below a 50Hz frame -- so each routine
repeats the whole computation N times internally and BASIC times a single USR.

    python3 make-euler5-tap.py [out.tap]        (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "euler5.tap")
REPEATS = 500

# 60004 result(4) | 60008 k(2) | 60010 g(2) | 60012 m(2)
# 60016 tmp(4) | 60020 modval(4) | 60032 rem(2) | 60036 repeat(2)
_HEAD = """        org 0
        ld hl,%d
        ld (60036),hl
rep:    ld hl,1
        ld (60004),hl
        ld hl,0
        ld (60006),hl
        ld hl,2
        ld (60008),hl
kloop:  ld hl,20
        ld de,(60008)
        or a
        sbc hl,de
        jp c,kdone
""" % REPEATS

_TAIL = """        ld hl,(60008)
        inc hl
        ld (60008),hl
        jp kloop
kdone:  ld hl,(60036)
        dec hl
        ld (60036),hl
        ld a,h
        or l
        jp nz,rep
        ret
"""

STEP_OP = """        ld hl,(60004)
        ld de,(60006)
        ld bc,(60008)
        defb 0xED,0xC5
        ld (60010),hl
        ld hl,(60008)
        ld a,(60010)
        defb 0xED,0xC6
        ld (60012),hl
        ld hl,60004
        ld a,(60012)
        ld bc,4
        defb 0xED,0xCD
"""

STEP_SW = """        call smod
        ld a,(60032)
        ld d,a
        ld a,(60008)
        ld e,a
sg:     ld a,e
        or a
        jr z,sgd
        ld a,d
sgm:    cp e
        jr c,sgm2
        sub e
        jr sgm
sgm2:   ld d,e
        ld e,a
        jr sg
sgd:    ld a,d
        ld (60010),a
        xor a
        ld (60011),a
        ld a,(60008)
        ld c,a
        ld a,(60010)
        ld e,a
        ld b,0
        ld a,c
sdv:    cp e
        jr c,sdvd
        sub e
        inc b
        jr sdv
sdvd:   ld a,b
        ld (60012),a
        xor a
        ld (60013),a
        ld hl,(60004)
        ld (60016),hl
        ld hl,(60006)
        ld (60018),hl
        ld a,(60012)
        dec a
        jr z,smd
        ld b,a
smul:   ld hl,(60004)
        ld de,(60016)
        add hl,de
        ld (60004),hl
        ld hl,(60006)
        ld de,(60018)
        adc hl,de
        ld (60006),hl
        djnz smul
smd:
"""

_SMOD = """
smod:   ld hl,(60004)
        ld (60020),hl
        ld hl,(60006)
        ld (60022),hl
        ld hl,0
        ld (60032),hl
        ld b,32
sml:    ld hl,60020
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,(60032)
        adc hl,hl
        ld de,(60008)
        or a
        sbc hl,de
        jr nc,smk
        add hl,de
smk:    ld (60032),hl
        djnz sml
        ret
"""

ASM_OP = _HEAD + STEP_OP + _TAIL
ASM_SW = _HEAD + STEP_SW + _TAIL + _SMOD

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
prog += line(10, K('PRINT')+s('"smallest number divisible"'))
prog += line(20, K('PRINT')+s('"by all of 1 to 20"'))
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
prog += line(140, K('PRINT')+num(REPEATS)+s(';" runs; opcode ";')+K('INT')+s('(w/o);"x"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

plen = len(prog)
header = [0x00] + list(b"EULER5    ") + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
