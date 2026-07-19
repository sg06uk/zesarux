#!/usr/bin/env python3
"""Load the sieve demo into ZEsarUX (relocated to RAM), run to HALT on the real
emulator, dump the screen, and render + golden-check vs the RTL's fingerprint."""
import socket, re, sys, os

FL_DIR = "/home/sg06uk/z80-fpga-bench/exercises/firstlight"
sys.path.insert(0, FL_DIR)
import profile as fl
import sieve as S

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 10099
ORG = 0x8000
DISP_ADDR, DISP_LEN = 0x4000, 6912

# relocate org 0 -> 0x8000 so code lives in RAM (0x0000-0x3FFF is ROM on a 48K)
src = re.sub(r'(?m)^\s*org\s+0\s*$', f'        org 0x{ORG:04X}', S.build_src())
amap = fl.assemble("sieve_reloc", src)
BIN = os.path.join(fl.BUILD, "sieve_reloc.bin")
prog = open(BIN, "rb").read()
if len(prog) > ORG:                      # binary padded from 0 -> slice to the org
    prog = prog[ORG:]
start, done = amap["start"], amap["done"]
print(f"reassembled at 0x{ORG:04X}: {len(prog)} bytes; start=0x{start:04X} done(halt)=0x{done:04X}")

class Z:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(30); self._read()
    def _read(self):
        buf = b""
        while not buf.rstrip().endswith(b">"):
            try: c = self.s.recv(65536)
            except socket.timeout: break
            if not c: break
            buf += c
        return buf.decode(errors="replace")
    def cmd(self, c):
        self.s.sendall((c + "\n").encode()); return self._read()
    def setr(self, r, v): self.cmd(f"set-register {r}={v:04X}H")
    def wmem(self, addr, data):
        for i in range(0, len(data), 256):
            self.cmd(f"write-memory-raw {addr+i:04X}H " + "".join(f"{b:02X}" for b in data[i:i+256]))
    def rmem(self, addr, n):
        out = self.cmd(f"read-memory {addr:04X}H {n}")
        m = re.match(r"\s*([0-9A-Fa-f]+)", out); h = m.group(1) if m else ""
        return bytes(int(h[i:i+2], 16) for i in range(0, min(len(h), 2*n), 2))

z = Z(PORT)
z.cmd("enter-cpu-step")
z.wmem(ORG, prog)
back = z.rmem(ORG, 4)
print(f"loaded @0x{ORG:04X}, first 4 bytes: {back.hex()} (expect {prog[:4].hex()}) -> {'OK' if back==prog[:4] else 'MISMATCH'}")
# ZEsarUX boots its ROM (IM1, IFF=1) before we attach, so the 50Hz interrupt
# would wake the final HALT and run past it into data. Enter via a DI trampoline
# so interrupts are off: HALT parks forever and drawing is uninterrupted.
TRAMP = 0x7F00
z.wmem(TRAMP, [0xF3, 0xC3, start & 0xFF, start >> 8])   # DI ; JP start
z.setr("PC", TRAMP)
z.cmd(f"set-breakpoint 1 PC={done:04X}H")
z.cmd("enable-breakpoints")
print("running to HALT...")
z.cmd("run")
regs = z.cmd("get-registers")
pc = int(re.search(r"PC=([0-9A-Fa-f]{4})", regs).group(1), 16)
print(f"stopped at PC=0x{pc:04X} (halt=0x{done:04X}) -> {'OK' if pc==done else 'UNEXPECTED'}")

disp = z.rmem(DISP_ADDR, DISP_LEN)
print(f"screen dumped: {len(disp)} bytes")
z.cmd("exit")

png = "/tmp/claude-1000/-home-sg06uk/052e8c75-9e94-48b7-9a6d-f63303822dc2/scratchpad/zesarux_sieve.png"
fl.render_png(disp, png)
print(f"\nPNG: {png}\n")
print(fl.render_braille(disp))
ok, msg = fl.check_golden(disp, os.path.join(FL_DIR, "sieve.sha256"))
print(f"\n>>> GOLDEN: {msg}")
sys.exit(0 if ok else 1)
