#!/usr/bin/env python3
"""Load a t80x demo into ZEsarUX, run it to completion on the real emulator, and
golden-check the resulting screen against the RTL's fingerprint. In GUI mode the
picture appears in the ZEsarUX window.

    t80x_demo.py [sieve|firstlight] [PORT] [--verbose] [--png PATH]

Both demos are bare-metal `org 0` programs written for the bench's all-RAM SoC;
this loader adapts them to a real Spectrum (ROM at 0x0000-0x3FFF) by reassembling
the code into RAM (0x8000) -- and, for firstlight, relocating its itoa scratch
buffers out of the ROM region too. The PNG is only a diagnostic view of the bytes
read back; the emulator itself computes the screen.
"""
import socket, re, sys, os

FL_DIR = "/home/sg06uk/z80-fpga-bench/exercises/firstlight"
sys.path.insert(0, FL_DIR)
import profile as fl
import sieve as S

argv = sys.argv[1:]
VERBOSE = "--verbose" in argv
PNG = argv[argv.index("--png") + 1] if "--png" in argv else None
words = [a for a in argv if not a.startswith("-")]
DEMO = next((w for w in words if not w.isdigit()), "sieve")
_ports = [w for w in words if w.isdigit()]
PORT = int(_ports[0]) if _ports else 10099
if DEMO not in ("sieve", "firstlight"):
    sys.exit(f"unknown demo {DEMO!r}; use 'sieve' or 'firstlight'")
ORG = 0x8000

def vprint(*a):
    if VERBOSE: print(*a)

if DEMO == "sieve":
    src, golden, zero_bitmap = S.build_src(), "sieve.sha256", False
else:
    src, golden, zero_bitmap = fl.build_src(), "screen.sha256", True
    # firstlight's itoa buffers sit at 0x3F00-0x3F30 = ROM on a real Spectrum;
    # relocate them into free RAM so the writes land (bench SoC is all-RAM).
    for a, b in [("0x3F00","0x6000"),("0x3F02","0x6002"),("0x3F10","0x6010"),("0x3F30","0x6030")]:
        src = src.replace(a, b)
src = re.sub(r'(?m)^\s*org\s+0\s*$', f'        org 0x{ORG:04X}', src)
amap = fl.assemble(DEMO + "_reloc", src)
prog = open(os.path.join(fl.BUILD, DEMO + "_reloc.bin"), "rb").read()
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
if zero_bitmap:
    z.wmem(0x4000, bytes(6144))       # firstlight skips CLS; blank the bitmap (bench zero-inits RAM)
z.wmem(ORG, prog)
if z.rmem(ORG, 4) != prog[:4]:
    sys.exit("error: program did not load into RAM")
# ZEsarUX boots its ROM (interrupts on) before we attach; enter via a DI
# trampoline so the final HALT parks instead of running past into data.
z.wmem(0x7F00, [0xF3, 0xC3, start & 0xFF, start >> 8])   # DI ; JP start
z.setr("PC", 0x7F00)
z.cmd(f"set-breakpoint 1 PC={done:04X}H")
z.cmd("enable-breakpoints")
vprint(f"{DEMO}: loaded at 0x{ORG:04X}; running to HALT (0x{done:04X})...")
z.cmd("run")
regs = z.cmd("get-registers")         # drain run's trailing output + resync before the big read
vprint("stopped at PC=0x%04X" % int(re.search(r"PC=([0-9A-Fa-f]{4})", regs).group(1), 16))
disp = z.rmem(0x4000, 6912)
# leave step mode so the GUI closes the debugger/menu and shows the drawn screen.
# (entering step mode opened the menu; disable the breakpoint first so resuming at
# the HALT doesn't immediately re-break. The DI trampoline keeps the CPU parked.)
z.cmd("disable-breakpoints")
z.cmd("exit-cpu-step")
z.cmd("exit")

if PNG or VERBOSE:
    PNG = PNG or f"/tmp/zesarux_{DEMO}.png"
    fl.render_png(disp, PNG)
    vprint(f"screen PNG: {PNG}")
if VERBOSE:
    print(fl.render_braille(disp))

ok, msg = fl.check_golden(disp, os.path.join(FL_DIR, golden))
print(f"{DEMO} ran on ZEsarUX -> {msg}")
sys.exit(0 if ok else 1)
