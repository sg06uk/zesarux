#!/usr/bin/env python3
"""Drive ZEsarUX over ZRCP: execute each t80x opcode and check vs the bench oracle."""
import socket, re, sys, time, math

sys.path.insert(0, "/home/sg06uk/z80-fpga-bench")
from harness import oracle as O   # ground truth

HOST, PORT = "127.0.0.1", 10088

class Z:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=5)
        self.s.settimeout(3)
        self._read_until_prompt()          # swallow banner
    def _read_until_prompt(self):
        buf = b""
        while not buf.rstrip().endswith(b">"):   # "command> " or "command@cpu-step> "
            try: c = self.s.recv(4096)
            except socket.timeout: break
            if not c: break
            buf += c
        return buf.decode(errors="replace")
    def cmd(self, c):
        self.s.sendall((c + "\n").encode())
        return self._read_until_prompt()
    def regs(self):
        out = self.cmd("get-registers")
        d = {}
        for m in re.finditer(r"([A-Z]{1,3}[\']?)=([0-9A-Fa-f]{2,4})", out):
            d[m.group(1)] = int(m.group(2), 16)
        return d
    def setr(self, r, v): self.cmd(f"set-register {r}={v:04X}H")
    def wmem(self, addr, bytes_):
        # write-memory-raw: concatenated hex (each token starting with a letter
        # would be parsed as a LABEL by write-memory, so raw is the safe path)
        self.cmd(f"write-memory-raw {addr:04X}H " + "".join(f"{b:02X}" for b in bytes_))
    def rmem(self, addr, n):
        # read-memory emits continuous hex (%02X...) then the prompt on a new line
        out = self.cmd(f"read-memory {addr:04X}H {n}")
        m = re.match(r"\s*([0-9A-Fa-f]+)", out)
        h = m.group(1) if m else ""
        return [int(h[i:i+2], 16) for i in range(0, min(len(h), 2 * n), 2)]
    def step(self): self.cmd("cpu-step")

def hi(v): return (v >> 16) & 0xFFFF
def lo(v): return v & 0xFFFF

CODE = 0x8000
z = Z()
z.cmd("enter-cpu-step")
results = []

def check(name, ok, detail):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

# ---- mull ED C3: HL*DE -> DE:HL ----
for HLv, DEv in [(1000, 1000), (65535, 65535), (12345, 6789)]:
    z.wmem(CODE, [0xED, 0xC3])
    z.setr("PC", CODE); z.setr("HL", HLv); z.setr("DE", DEv)
    z.step(); r = z.regs()
    exp = O.BANK_ORACLES["mull"](HLv, DEv)
    got = (r.get("DE", 0) << 16) | r.get("HL", 0)
    check(f"mull {HLv}*{DEv}", got == exp, f"got={got} exp={exp}")

# ---- divl ED C4: (DE:HL)/BC -> HL quot(sat), DE rem ----
for num, div in [(1008800, 20), (100000, 7), (5000, 0), (0xFFFFFFFF, 3)]:
    z.wmem(CODE, [0xED, 0xC4])
    z.setr("PC", CODE); z.setr("HL", lo(num)); z.setr("DE", hi(num)); z.setr("BC", div)
    z.step(); r = z.regs()
    packed = O._divl(num, div)
    exp_q, exp_r = lo(packed), hi(packed)
    check(f"divl {num}/{div}", r.get("HL") == exp_q and r.get("DE") == exp_r,
          f"q got={r.get('HL')} exp={exp_q}; r got={r.get('DE')} exp={exp_r}")

# ---- gcd ED C5: gcd(DE:HL, BC) -> HL ----
for num, bc in [(1008800, 48), (0xFFFFFFFF, 12345), (100, 0)]:
    z.wmem(CODE, [0xED, 0xC5])
    z.setr("PC", CODE); z.setr("HL", lo(num)); z.setr("DE", hi(num)); z.setr("BC", bc)
    z.step(); r = z.regs()
    exp = O._gcd(num, bc) & 0xFFFF
    check(f"gcd({num},{bc})", r.get("HL") == exp, f"got={r.get('HL')} exp={exp}")

# ---- bstride ED C8: desc{base,nbits}, BC=start, DE=stride -> mark bits, HL=count ----
DESC, BM = 0x9000, 0x9100
for nbits, start, stride in [(64, 3, 3), (49, 0, 2), (40, 5, 7)]:
    z.wmem(BM, [0] * ((nbits + 7) // 8 + 2))                       # clear bitmap
    z.wmem(DESC, [lo(BM) & 0xFF, (BM >> 8) & 0xFF, nbits & 0xFF, (nbits >> 8) & 0xFF])
    z.wmem(CODE, [0xED, 0xC8])
    z.setr("PC", CODE); z.setr("HL", DESC); z.setr("BC", start); z.setr("DE", stride)
    z.step(); r = z.regs()
    marks = O._bstride_marks(nbits, start, stride)
    exp_bm = bytearray((nbits + 7) // 8)
    for b in marks: exp_bm[b >> 3] |= 1 << (b & 7)
    got_bm = z.rmem(BM, len(exp_bm))
    check(f"bstride n={nbits} s={start} k={stride}",
          got_bm == list(exp_bm) and r.get("HL") == len(marks),
          f"count got={r.get('HL')} exp={len(marks)}; bitmap {'match' if got_bm==list(exp_bm) else f'DIFF got={got_bm} exp={list(exp_bm)}'}")

# ---- bsum ED CE: BC=&bitmap, HL=nbits, DE=&out, A=pol -> [idxSum:4][count:2] LE ----
OUT = 0x9200
patterns = [(bytes([0b10110101, 0b00101110]), 16, 1),
            (bytes([0xFF, 0x0F]), 12, 0),
            (bytes([0x03]), 8, 1)]
for raw, nbits, pol in patterns:
    z.wmem(BM, list(raw) + [0, 0])
    z.wmem(OUT, [0] * 6)
    z.wmem(CODE, [0xED, 0xCE])
    z.setr("PC", CODE); z.setr("BC", BM); z.setr("HL", nbits); z.setr("DE", OUT); z.setr("AF", pol << 8)
    z.step()
    bitmap_int = int.from_bytes(raw, "little")
    packed = O._bsum(bitmap_int, nbits, pol)
    exp = list(packed.to_bytes(6, "little"))
    got = z.rmem(OUT, 6)
    check(f"bsum n={nbits} pol={pol}", got == exp, f"got={got} exp={exp}")

z.cmd("exit")
npass = sum(1 for _, ok, _ in results if ok)
print(f"\n==== {npass}/{len(results)} opcode checks PASS ====")
sys.exit(0 if npass == len(results) else 1)
