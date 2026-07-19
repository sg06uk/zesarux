#!/usr/bin/env python3
"""Build primesum.tap: enter a limit n, and the program sums all primes <= n two
ways -- the coprocessor sieve (line-1 REM: bstride marks each prime's multiples,
bsum sums the surviving clear-bit indices = the primes, and counts them) and a
pure-software sieve (line-2 REM). Prints the count, the sum, and the time each
took (via the 50Hz FRAMES counter).

Regenerate:  python3 make-primesum-tap.py [out.tap]      (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "primesum.tap")

# routines embedded so the script is self-contained
ASM_OP = r"""        org 0
        ld hl,50000
        ld (60010),hl
        ld hl,(60000)
        inc hl
        ld (60012),hl
        ld hl,(60000)
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        inc hl
        inc hl
        ld b,h
        ld c,l
        ld hl,50000
clrl:   ld (hl),0
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,clrl
        ld a,3
        ld (50000),a
        ld hl,2
        ld (60014),hl
ploop:  ld hl,(60014)
        add hl,hl
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,pdone
        ld de,(60014)
        ld hl,(60014)
        add hl,hl
        ld b,h
        ld c,l
        ld hl,60010
        defb 0xED,0xC8
        ld hl,(60014)
        inc hl
        ld (60014),hl
        jr ploop
pdone:  ld bc,50000
        ld hl,(60000)
        inc hl
        ld de,60004
        xor a
        defb 0xED,0xCE
        ret
"""

ASM_SW = r"""        org 0
        ld hl,(60000)
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        inc hl
        inc hl
        ld b,h
        ld c,l
        ld hl,50000
clrl:   ld (hl),0
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,clrl
        ld a,3
        ld (50000),a
        ld hl,2
        ld (60014),hl
sploop: ld hl,(60014)
        add hl,hl
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,spdone
        ld hl,(60014)
        add hl,hl
        ld (60016),hl
smark:  ld hl,(60016)
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,smdone
        ld a,(60016)
        and 7
        ld b,a
        ld a,1
        inc b
mkm:    dec b
        jr z,mkd
        add a,a
        jr mkm
mkd:    ld c,a
        ld hl,(60016)
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,50000
        add hl,de
        ld a,(hl)
        or c
        ld (hl),a
        ld hl,(60016)
        ld de,(60014)
        add hl,de
        ld (60016),hl
        jr smark
smdone: ld hl,(60014)
        inc hl
        ld (60014),hl
        jr sploop
spdone: ld hl,0
        ld (60004),hl
        ld (60006),hl
        ld (60008),hl
        ld hl,0
        ld (60018),hl
ssum:   ld hl,(60018)
        ld de,(60000)
        ex de,hl
        or a
        sbc hl,de
        jr c,ssdone
        ld a,(60018)
        and 7
        ld b,a
        ld a,1
        inc b
mkm2:   dec b
        jr z,mkd2
        add a,a
        jr mkm2
mkd2:   ld c,a
        ld hl,(60018)
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,50000
        add hl,de
        ld a,(hl)
        and c
        jr nz,snp
        ld hl,(60004)
        ld de,(60018)
        add hl,de
        ld (60004),hl
        jr nc,noc
        ld hl,(60006)
        inc hl
        ld (60006),hl
noc:    ld hl,(60008)
        inc hl
        ld (60008),hl
snp:    ld hl,(60018)
        inc hl
        ld (60018),hl
        jr ssum
ssdone: ret
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
def peek32(b):
    return (K('PEEK')+num(b)+s('+')+num(256)+s('*(')+K('PEEK')+num(b+1)+s('+')+num(256)+s('*(')
            +K('PEEK')+num(b+2)+s('+')+num(256)+s('*')+K('PEEK')+num(b+3)+s('))'))
def frames():
    return (K('PEEK')+num(23672)+s('+')+num(256)+s('*(')+K('PEEK')+num(23673)+s('+')
            +num(256)+s('*')+K('PEEK')+num(23674)+s(')'))
def poke16(addr, var):
    return (K('POKE')+num(addr)+s(',')+[ord(var)]+s('-')+num(256)+s('*')+K('INT')+s('('+var+'/')+num(256)+s(')')
            +s(':')+K('POKE')+num(addr+1)+s(',')+K('INT')+s('('+var+'/')+num(256)+s(')'))

def line(n, body):
    data = body + [0x0D]
    return [(n>>8)&0xFF, n&0xFF, len(data)&0xFF, (len(data)>>8)&0xFF] + data

prog = []
prog += line(1, K('REM') + OPCODE)
prog += line(2, K('REM') + SOFT)
prog += line(10, K('INPUT') + s('"Sum primes up to: ";n'))
prog += line(20, poke16(60000, 'n'))
prog += line(30, K('LET')+s('f=')+frames())
prog += line(40, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(50, K('LET')+s('o=')+frames()+s('-f'))
prog += line(60, K('LET')+s('s=')+peek32(60004))
prog += line(70, K('LET')+s('c=')+K('PEEK')+num(60008)+s('+')+num(256)+s('*')+K('PEEK')+num(60009))
prog += line(80, K('PRINT')+[ord('c')]+s(';" primes up to ";')+[ord('n')])
prog += line(90, K('PRINT')+s('"sum of primes = ";s'))
prog += line(100, K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"'))
prog += line(110, K('LET')+s('f=')+frames())
prog += line(120, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(130, K('LET')+s('w=')+frames()+s('-f'))
prog += line(140, K('PRINT')+s('"software: ";w/')+num(50)+s(';" s"'))
prog += line(150, K('PRINT')+s('"opcode ~";')+K('INT')+s('(w/o);"x faster"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

name = b"PRIMESUM  "
plen = len(prog)
header = [0x00] + list(name) + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
