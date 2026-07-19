#!/usr/bin/env python3
"""Build a ZX Spectrum .tap: BASIC program with two REM lines holding machine
code (opcode MULL via ED C3, and software shift-add MULL), plus a driver that
POKEs operands, USR-calls each, and PRINTs the results."""
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "mulldemo.tap"

# --- machine code (verified on ZEsarUX). Position-independent: only relative
#     jumps + absolute DATA addresses (operands 60000, result 60004). ---
OPCODE = [0x2A,0x60,0xEA, 0xED,0x5B,0x62,0xEA, 0xED,0xC3, 0x22,0x64,0xEA,
          0xED,0x53,0x66,0xEA, 0xC9]                       # 17 bytes
SOFT   = [0xED,0x4B,0x60,0xEA, 0xED,0x5B,0x62,0xEA, 0x21,0x00,0x00, 0x3E,0x10,
          0x29, 0xCB,0x13, 0xCB,0x12, 0x30,0x04, 0x09, 0x30,0x01, 0x13,
          0x3D, 0x20,0xF2, 0x22,0x64,0xEA, 0xED,0x53,0x66,0xEA, 0xC9]   # 35 bytes

PROG = 23755                                    # 48K BASIC program start
USR_OPCODE = PROG + 5                            # code after line 1's REM token
line1_len = 4 + 1 + len(OPCODE) + 1             # hdr(4)+REM(1)+code+0D(1)
USR_SOFT = PROG + line1_len + 5                  # code after line 2's REM token

TOK = {'REM':0xEA,'POKE':0xF4,'RANDOMIZE':0xF9,'USR':0xC0,'LET':0xF1,'PRINT':0xF5,'PEEK':0xBE}
def num(n): return list(str(n).encode()) + [0x0E,0x00,0x00,n & 0xFF,(n >> 8) & 0xFF,0x00]
def s(txt): return list(txt.encode())
def peek_le32(base):   # PEEK base+256*(PEEK b+1+256*(PEEK b+2+256*PEEK b+3))
    return ([TOK['PEEK']] + num(base) + s('+') + num(256) + s('*(')
            + [TOK['PEEK']] + num(base+1) + s('+') + num(256) + s('*(')
            + [TOK['PEEK']] + num(base+2) + s('+') + num(256) + s('*')
            + [TOK['PEEK']] + num(base+3) + s('))'))

def line(n, body):
    data = body + [0x0D]
    return [(n >> 8) & 0xFF, n & 0xFF, len(data) & 0xFF, (len(data) >> 8) & 0xFF] + data

prog = []
prog += line(1, [TOK['REM']] + OPCODE)
prog += line(2, [TOK['REM']] + SOFT)
prog += line(10, [TOK['POKE']] + num(60000) + s(',') + num(225) + s(':')
                 + [TOK['POKE']] + num(60001) + s(',') + num(16) + s(':')
                 + [TOK['POKE']] + num(60002) + s(',') + num(210) + s(':')
                 + [TOK['POKE']] + num(60003) + s(',') + num(4))
prog += line(20, [TOK['RANDOMIZE'], TOK['USR']] + num(USR_OPCODE))
prog += line(30, [TOK['LET']] + s('r=') + peek_le32(60004))
prog += line(40, [TOK['PRINT']] + s('"MULL 4321*1234 (opcode)   = ";') + s('r'))
prog += line(50, [TOK['RANDOMIZE'], TOK['USR']] + num(USR_SOFT))
prog += line(60, [TOK['LET']] + s('r=') + peek_le32(60004))
prog += line(70, [TOK['PRINT']] + s('"MULL 4321*1234 (software) = ";') + s('r'))

def block(flag, data):
    body = [flag] + data
    chk = 0
    for b in body: chk ^= b
    body.append(chk)
    return [len(body) & 0xFF, (len(body) >> 8) & 0xFF] + body

name = b"MULLDEMO  "[:10].ljust(10)
plen = len(prog)
autostart = 10
header = [0x00] + list(name) + [plen & 0xFF, plen >> 8,
                                autostart & 0xFF, autostart >> 8, plen & 0xFF, plen >> 8]
tap = block(0x00, header) + block(0xFF, prog)
open(OUT, "wb").write(bytes(tap))
print(f"wrote {OUT}: {len(tap)} bytes; program {plen} bytes; "
      f"USR opcode={USR_OPCODE}, USR software={USR_SOFT}")
