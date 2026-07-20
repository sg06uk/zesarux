#!/usr/bin/env python3
"""Build euler2.tap: Project Euler #2 -- sum the even Fibonacci terms not
exceeding 4,000,000 (answer 4613732) -- solved two ways and timed.

Even terms have their own recurrence E(n) = 4*E(n-1) + E(n-2), so we generate
them directly (no parity test). Everything is 32-bit in memory. The two versions
differ in ONE place, the *4:
    opcode   : mul1 (ED CD) -- acc[4] *= 4 in a single instruction
    software : two 32-bit left shifts (sla/rl through 4 bytes, twice)
Everything else (the adds, the copies, the compare) is identical, so the race
isolates exactly what the coprocessor can and cannot help with here.

Each routine repeats the whole solve N times internally (one solve is only a few
thousand cycles -- far below one 50Hz frame), so BASIC pays a single USR call and
only machine code is timed.

    python3 make-euler2-tap.py [out.tap]        (needs z80asm on PATH)
"""
import sys, os, subprocess, tempfile

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "euler2.tap")

# 60000 repeats-in, 60004 sum, 60008 a, 60012 b, 60016 next, 60020 counter
_COMMON_HEAD = """        org 0
        ld hl,(60000)
        ld (60020),hl
rep:    ld hl,2
        ld (60008),hl
        ld hl,0
        ld (60010),hl
        ld hl,8
        ld (60012),hl
        ld hl,0
        ld (60014),hl
        ld hl,10
        ld (60004),hl
        ld hl,0
        ld (60006),hl
fib:    ld hl,(60012)
        ld (60016),hl
        ld hl,(60014)
        ld (60018),hl
"""
_COMMON_TAIL = """        ld hl,(60016)
        ld de,(60008)
        add hl,de
        ld (60016),hl
        ld hl,(60018)
        ld de,(60010)
        adc hl,de
        ld (60018),hl
        ld hl,0x0900
        ld de,(60016)
        or a
        sbc hl,de
        ld hl,0x003D
        ld de,(60018)
        sbc hl,de
        jr c,fibdone
        ld hl,(60004)
        ld de,(60016)
        add hl,de
        ld (60004),hl
        ld hl,(60006)
        ld de,(60018)
        adc hl,de
        ld (60006),hl
        ld hl,(60012)
        ld (60008),hl
        ld hl,(60014)
        ld (60010),hl
        ld hl,(60016)
        ld (60012),hl
        ld hl,(60018)
        ld (60014),hl
        jp fib
fibdone:
        ld hl,(60020)
        dec hl
        ld (60020),hl
        ld a,h
        or l
        jp nz,rep
        ret
"""
MUL4_OPCODE = """        ld hl,60016
        ld a,4
        ld bc,4
        defb 0xED,0xCD
"""
MUL4_SOFT = """        ld hl,60016
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,60016
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
"""
ASM_OP = _COMMON_HEAD + MUL4_OPCODE + _COMMON_TAIL
ASM_SW = _COMMON_HEAD + MUL4_SOFT + _COMMON_TAIL

def assemble(src, org=0):
    """Assemble at `org`. The loop-back jump must be `jp` (the body exceeds jr's
    +/-127), so the code is NOT position-independent -- we assemble each routine
    at the exact address its REM will land on. Two passes: sizes first (jp is a
    fixed 3 bytes, so lengths don't shift), then the real orgs."""
    src = src.replace("        org 0\n", "        org %d\n" % org, 1)
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "r.asm"), "w").write(src)
        r = subprocess.run(["z80asm", "-b", "-or.bin", "r.asm"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"z80asm failed:\n{r.stdout}{r.stderr}")
        b = list(open(os.path.join(d, "r.bin"), "rb").read())
        return b[org:] if len(b) > org > 0 else b

PROG = 23755
_l1, _l2 = len(assemble(ASM_OP)), len(assemble(ASM_SW))     # pass 1: sizes
USR_OPCODE = PROG + 5
USR_SOFT = PROG + (4 + 1 + _l1 + 1) + 5
OPCODE = assemble(ASM_OP, USR_OPCODE)                        # pass 2: real orgs
SOFT = assemble(ASM_SW, USR_SOFT)
assert len(OPCODE) == _l1 and len(SOFT) == _l2, "size shifted between passes"

TOK = {'REM':0xEA,'POKE':0xF4,'INT':0xBA,'RANDOMIZE':0xF9,'USR':0xC0,
       'LET':0xF1,'PEEK':0xBE,'PRINT':0xF5}
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
prog += line(10, K('LET')+s('n=')+num(1000))
prog += line(20, K('POKE')+num(60000)+s(',n-')+num(256)+s('*')+K('INT')+s('(n/')+num(256)+s('):')
                 +K('POKE')+num(60001)+s(',')+K('INT')+s('(n/')+num(256)+s(')'))
prog += line(30, K('LET')+s('f=')+frames())
prog += line(40, K('RANDOMIZE','USR')+num(USR_OPCODE))
prog += line(50, K('LET')+s('o=')+frames()+s('-f'))
prog += line(60, K('LET')+s('s=')+peek32(60004))
prog += line(70, K('PRINT')+s('"even fib sum = ";s'))
prog += line(80, K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"'))
prog += line(90, K('LET')+s('f=')+frames())
prog += line(100, K('RANDOMIZE','USR')+num(USR_SOFT))
prog += line(110, K('LET')+s('w=')+frames()+s('-f'))
prog += line(120, K('PRINT')+s('"software: ";w/')+num(50)+s(';" s"'))
prog += line(130, K('PRINT')+[ord('n')]+s(';" solves; opcode ";')+K('INT')+s('(w/o*')+num(100)
                  +s(')/')+num(100)+s(';"x (no hotspot)"'))

def block(flag, data):
    body = [flag] + data
    c = 0
    for b in body: c ^= b
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

plen = len(prog)
header = [0x00] + list(b"EULER2    ") + [plen & 0xFF, plen >> 8, 10, 0, plen & 0xFF, plen >> 8]
open(OUT, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
print(f"wrote {OUT}: program {plen} bytes; opcode {len(OPCODE)}B @ {USR_OPCODE}, software {len(SOFT)}B @ {USR_SOFT}")
