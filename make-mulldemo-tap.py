#!/usr/bin/env python3
"""Build mulldemo.tap: a ZX Spectrum program that multiplies two user-entered
numbers two ways -- the coprocessor opcode (ED C3, line-1 REM) and a software
shift-and-add (line-2 REM) -- prints both results, then TIMES the pure machine
code (each routine loops N times internally, so only one USR call per method is
timed) and derives T-states from the 50Hz FRAMES counter.

Regenerate:  python3 make-mulldemo-tap.py [out.tap]
Needs z80asm (z88dk) on PATH to assemble the two routines.
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "mulldemo.tap")

# --- the two routines, looped COUNT (60008) times; operands 60000/60002, result 60004 ---
ASM_OP = """        org 0
        ld hl,(60008)
        ld (60010),hl
oloop:  ld hl,(60000)
        ld de,(60002)
        defb 0xED,0xC3
        ld (60004),hl
        ld (60006),de
        ld hl,(60010)
        dec hl
        ld (60010),hl
        ld a,h
        or l
        jr nz,oloop
        ret
"""
ASM_SW = """        org 0
        ld hl,(60008)
        ld (60010),hl
sloop:  ld bc,(60000)
        ld de,(60002)
        ld hl,0
        ld a,16
mloop:  add hl,hl
        rl e
        rl d
        jr nc,noadd
        add hl,bc
        jr nc,noadd
        inc de
noadd:  dec a
        jr nz,mloop
        ld (60004),hl
        ld (60006),de
        ld hl,(60010)
        dec hl
        ld (60010),hl
        ld a,h
        or l
        jr nz,sloop
        ret
"""

def assemble(src):
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "r.asm"), "w").write(src)
        r = subprocess.run(["z80asm", "-b", "-or.bin", "r.asm"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"z80asm failed:\n{r.stdout}{r.stderr}")
        return list(open(os.path.join(d, "r.bin"), "rb").read())

OPCODE = assemble(ASM_OP)
SOFT = assemble(ASM_SW)

PROG = 23755
USR_OPCODE = PROG + 5
line1_len = 4 + 1 + len(OPCODE) + 1
USR_SOFT = PROG + line1_len + 5

TOK = {'REM':0xEA,'INPUT':0xEE,'POKE':0xF4,'INT':0xBA,'RANDOMIZE':0xF9,
       'USR':0xC0,'LET':0xF1,'PEEK':0xBE,'PRINT':0xF5}
def K(*names): return [TOK[n] for n in names]
def num(n): return list(str(n).encode()) + [0x0E,0x00,0x00,n & 0xFF,(n >> 8) & 0xFF,0x00]
def s(t): return list(t.encode())
def peek32(b):   # PEEK b + 256*(PEEK b+1 + 256*(PEEK b+2 + 256*PEEK b+3))  -- Horner, no >65535 literal
    return (K('PEEK')+num(b)+s('+')+num(256)+s('*(')+K('PEEK')+num(b+1)+s('+')+num(256)+s('*(')
            +K('PEEK')+num(b+2)+s('+')+num(256)+s('*')+K('PEEK')+num(b+3)+s('))'))
def frames():    # PEEK 23672 + 256*(PEEK 23673 + 256*PEEK 23674)
    return (K('PEEK')+num(23672)+s('+')+num(256)+s('*(')+K('PEEK')+num(23673)+s('+')
            +num(256)+s('*')+K('PEEK')+num(23674)+s(')'))
def poke16(addr, var):   # POKE addr, var-256*INT (var/256): POKE addr+1, INT (var/256)
    lo = K('POKE')+num(addr)+s(',')+[ord(var)]+s('-')+num(256)+s('*')+K('INT')+s('('+var+'/')+num(256)+s(')')
    hi = K('POKE')+num(addr+1)+s(',')+K('INT')+s('('+var+'/')+num(256)+s(')')
    return lo+s(':')+hi

def line(n, body):
    data = body + [0x0D]
    return [(n>>8)&0xFF, n&0xFF, len(data)&0xFF, (len(data)>>8)&0xFF] + data

prog = []
prog += line(1, K('REM') + OPCODE)
prog += line(2, K('REM') + SOFT)
prog += line(10, K('INPUT') + s('"First number: ";a'))
prog += line(20, K('INPUT') + s('"Second number: ";b'))
prog += line(30, poke16(60000, 'a'))
prog += line(40, poke16(60002, 'b'))
prog += line(50, K('POKE')+num(60008)+s(',')+num(1)+s(':')+K('POKE')+num(60009)+s(',')+num(0))
prog += line(60, K('RANDOMIZE','USR')+num(USR_OPCODE)+s(':')+K('LET')+s('p=')+peek32(60004))
prog += line(70, K('RANDOMIZE','USR')+num(USR_SOFT)+s(':')+K('LET')+s('q=')+peek32(60004))
prog += line(80, K('PRINT')+[ord('a')]+s(';" * ";')+[ord('b')]+s(';" = ";')+[ord('p')])
prog += line(90, K('LET')+s('n=')+num(5000))
prog += line(100, K('POKE')+num(60008)+s(',n-')+num(256)+s('*')+K('INT')+s('(n/')+num(256)+s('):')
                  +K('POKE')+num(60009)+s(',')+K('INT')+s('(n/')+num(256)+s(')'))
prog += line(110, K('LET')+s('f=')+frames())
prog += line(120, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(130, K('LET')+s('o=')+frames()+s('-f'))
prog += line(140, K('LET')+s('f=')+frames())
prog += line(150, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(160, K('LET')+s('w=')+frames()+s('-f'))
prog += line(170, K('PRINT')+s('n;" opcode  : ";o;" frame ~";')+K('INT')+s('(o*')+num(273)+s('*')+num(256)+s('/n);" T"'))
prog += line(180, K('PRINT')+s('n;" softwre : ";w;" frame ~";')+K('INT')+s('(w*')+num(273)+s('*')+num(256)+s('/n);" T"'))
prog += line(190, K('PRINT')+s('"opcode ~";')+K('INT')+s('(w/o);"x faster"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

name = b"MULLDEMO  "
plen = len(prog)
header = [0x00] + list(name) + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode routine {len(OPCODE)}B @ {USR_OPCODE}, "
      f"software {len(SOFT)}B @ {USR_SOFT}")
