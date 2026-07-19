#!/usr/bin/env python3
"""Load the sieve demo into ZEsarUX (relocated to RAM), run it to completion on
the real emulator, and golden-check the resulting screen against the RTL's
fingerprint. In GUI mode the prime constellation appears in the ZEsarUX window.

    t80x_sieve_demo.py [PORT] [--verbose] [--png PATH]

--verbose prints step detail + an ASCII preview; --png PATH also writes the
rendered screen (both are diagnostics -- the emulator itself computes the
screen; the PNG is just our way of looking at the bytes we read back out).
"""
import socket, re, sys, os

FL_DIR = "/home/sg06uk/z80-fpga-bench/exercises/firstlight"
sys.path.insert(0, FL_DIR)
import profile as fl
import sieve as S

argv = sys.argv[1:]
VERBOSE = "--verbose" in argv
PNG = argv[argv.index("--png") + 1] if "--png" in argv else None
_ports = [a for a in argv if a.isdigit()]
PORT = int(_ports[0]) if _ports else 10099
ORG = 0x8000
DISP_ADDR, DISP_LEN = 0x4000, 6912

def vprint(*a):
    if VERBOSE: print(*a)

# relocate org 0 -> 0x8000 so code lives in RAM (0x0000-0x3FFF is ROM on a 48K)
src = re.sub(r'(?m)^\s*org\s+0\s*$', f'        org 0x{ORG:04X}', S.build_src())
amap = fl.assemble("sieve_reloc", src)
prog = open(os.path.join(fl.BUILD, "sieve_reloc.bin"), "rb").read()
if len(prog) > ORG: prog = prog[ORG:]
start, done = amap["start"], amap["done"]

class Z:
    def __init__(s, port):
        s.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.s.settimeout(30); s._read()
    def _read(s):
        buf = b""
        while not buf.rstrip().endswith(b">"):
            try: c = s.s.recv(65536)
            except socket.timeout: break
            if not c: break
            buf += c
        return buf.decode(errors="replace")
    def cmd(s, c): s.s.sendall((c + "\n").encode()); return s._read()
    def setr(s, r, v): s.cmd(f"set-register {r}={v:04X}H")
    def wmem(s, addr, data):
        for i in range(0, len(data), 256):
            s.cmd(f"write-memory-raw {addr+i:04X}H " + "".join(f"{b:02X}" for b in data[i:i+256]))
    def rmem(s, addr, n):
        o = s.cmd(f"read-memory {addr:04X}H {n}"); m = re.match(r"\s*([0-9A-Fa-f]+)", o)
        h = m.group(1) if m else ""
        return bytes(int(h[i:i+2], 16) for i in range(0, min(len(h), 2*n), 2))

z = Z(PORT)
z.cmd("enter-cpu-step")
z.wmem(ORG, prog)
if z.rmem(ORG, 4) != prog[:4]:
    sys.exit("error: program did not load into RAM")
# ZEsarUX boots its ROM (interrupts on) before we attach; enter via a DI
# trampoline so the final HALT parks instead of running past into data.
z.wmem(0x7F00, [0xF3, 0xC3, start & 0xFF, start >> 8])   # DI ; JP start
z.setr("PC", 0x7F00)
z.cmd(f"set-breakpoint 1 PC={done:04X}H")
z.cmd("enable-breakpoints")
vprint(f"loaded at 0x{ORG:04X}; running to HALT (0x{done:04X})...")
z.cmd("run")
regs = z.cmd("get-registers")   # drain run's trailing output + resync before the big read
pc = int(re.search(r"PC=([0-9A-Fa-f]{4})", regs).group(1), 16)
vprint(f"stopped at PC=0x{pc:04X}")
disp = z.rmem(DISP_ADDR, DISP_LEN)
z.cmd("exit")

if PNG or VERBOSE:
    PNG = PNG or "/tmp/zesarux_sieve.png"
    fl.render_png(disp, PNG)
    vprint(f"screen PNG: {PNG}")
if VERBOSE:
    print(fl.render_braille(disp))

ok, msg = fl.check_golden(disp, os.path.join(FL_DIR, "sieve.sha256"))
print(f"sieve ran on ZEsarUX -> {msg}")
sys.exit(0 if ok else 1)
