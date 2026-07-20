#!/usr/bin/env python3
"""Build euler1.tap: Project Euler #1 -- the sum of all multiples of 3 or 5 below
n -- solved two ways and timed. The opcode version uses `div` (ED C6), which
returns the remainder in A directly; the software version does the identical loop
with a hand-written 16/8 shift-subtract modulo. Prints the answer and the time
each took (via the 50Hz FRAMES counter).

    python3 make-euler1-tap.py [out.tap]        (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "euler1.tap")

# n@60000, sum(32)@60004, i@60008
ASM_OP = r"""        org 0
        ld hl,0
        ld (60004),hl
        ld (60006),hl
        ld hl,1
        ld (60008),hl
eloop:  ld hl,(60008)
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,edone
        jr z,edone
        ld hl,(60008)
        ld a,3
        defb 0xED,0xC6
        or a
        jr z,eadd
        ld hl,(60008)
        ld a,5
        defb 0xED,0xC6
        or a
        jr nz,enext
eadd:   ld hl,(60004)
        ld de,(60008)
        add hl,de
        ld (60004),hl
        jr nc,enext
        ld hl,(60006)
        inc hl
        ld (60006),hl
enext:  ld hl,(60008)
        inc hl
        ld (60008),hl
        jr eloop
edone:  ret
"""

ASM_SW = r"""        org 0
        ld hl,0
        ld (60004),hl
        ld (60006),hl
        ld hl,1
        ld (60008),hl
sloop:  ld hl,(60008)
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,sdone
        jr z,sdone
        ld hl,(60008)
        ld c,3
        xor a
        ld b,16
sm1:    add hl,hl
        rla
        cp c
        jr c,sm2
        sub c
sm2:    djnz sm1
        or a
        jr z,sadd
        ld hl,(60008)
        ld c,5
        xor a
        ld b,16
sm3:    add hl,hl
        rla
        cp c
        jr c,sm4
        sub c
sm4:    djnz sm3
        or a
        jr nz,snext
sadd:   ld hl,(60004)
        ld de,(60008)
        add hl,de
        ld (60004),hl
        jr nc,snext
        ld hl,(60006)
        inc hl
        ld (60006),hl
snext:  ld hl,(60008)
        inc hl
        ld (60008),hl
        jr sloop
sdone:  ret
"""

def assemble(src):
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "r.asm"), "w").write(src)
        r = subprocess.run(["z80asm", "-b", "-or.bin", "r.asm"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"z80asm failed:\n{r.stdout}{r.stderr}")
        return list(open(os.path.join(d, "r.bin"), "rb").read())

OPCODE, SOFT = assemble(ASM_OP), assemble(ASM_SW)
PROG = 23755
USR_OPCODE = PROG + 5
USR_SOFT = PROG + (4 + 1 + len(OPCODE) + 1) + 5

TOK = {'REM':0xEA,'INPUT':0xEE,'POKE':0xF4,'INT':0xBA,'RANDOMIZE':0xF9,
       'USR':0xC0,'LET':0xF1,'PEEK':0xBE,'PRINT':0xF5}
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
prog += line(10, K('INPUT') + s('"Multiples of 3 or 5 below: ";n'))
prog += line(20, K('POKE')+num(60000)+s(',n-')+num(256)+s('*')+K('INT')+s('(n/')+num(256)+s('):')
                 +K('POKE')+num(60001)+s(',')+K('INT')+s('(n/')+num(256)+s(')'))
prog += line(30, K('LET')+s('f=')+frames())
prog += line(40, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(50, K('LET')+s('o=')+frames()+s('-f'))
prog += line(60, K('LET')+s('s=')+peek32(60004))
prog += line(70, K('PRINT')+s('"answer = ";s'))
prog += line(80, K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"'))
prog += line(90, K('LET')+s('f=')+frames())
prog += line(100, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(110, K('LET')+s('w=')+frames()+s('-f'))
prog += line(120, K('PRINT')+s('"software: ";w/')+num(50)+s(';" s"'))
prog += line(130, K('PRINT')+s('"opcode ~";')+K('INT')+s('(w/o);"x faster"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

plen = len(prog)
header = [0x00] + list(b"EULER1    ") + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
