#!/usr/bin/env python3
"""Drive ZEsarUX over ZRCP: execute every implemented t80x opcode (all but factor)
and check registers/memory/flags against the bench oracle."""
import socket, re, sys
sys.path.insert(0, "/home/sg06uk/z80-fpga-bench")
from harness import oracle as O

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 10099
CODE, BM, OUT = 0x8000, 0x9100, 0x9200

class Z:
    def __init__(s, p):
        s.s = socket.create_connection(("127.0.0.1", p), timeout=5); s.s.settimeout(10); s._r()
    def _r(s):
        b = b""
        while not b.rstrip().endswith(b">"):
            try: c = s.s.recv(65536)
            except socket.timeout: break
            if not c: break
            b += c
        return b.decode(errors="replace")
    def cmd(s, c): s.s.sendall((c+"\n").encode()); return s._r()
    def regs(s):
        d = {}
        for m in re.finditer(r"([A-Z]{1,3}'?)=([0-9A-Fa-f]{2,4})", s.cmd("get-registers")):
            d[m.group(1)] = int(m.group(2), 16)
        return d
    def setr(s, r, v): s.cmd(f"set-register {r}={v:04X}H")
    def wmem(s, a, d): s.cmd(f"write-memory-raw {a:04X}H " + "".join(f"{b:02X}" for b in d))
    def rmem(s, a, n):
        o = s.cmd(f"read-memory {a:04X}H {n}"); m = re.match(r"\s*([0-9A-Fa-f]+)", o); h = m.group(1) if m else ""
        return bytes(int(h[i:i+2],16) for i in range(0, min(len(h),2*n), 2))
    def op(s, *bytes_): s.wmem(CODE, bytes_); s.setr("PC", CODE); s.cmd("cpu-step")

z = Z(PORT); z.cmd("enter-cpu-step")
res = []
def ck(name, ok, d=""):
    res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {name} {d if not ok else ''}")

lo, hi = lambda v: v & 0xFFFF, lambda v: (v >> 16) & 0xFFFF

# mul b,c / d,e / h,l  (ED C0/C1/C2): pair = high*low
for opb, pair, (h_, l_) in [(0xC0,"BC",(200,3)), (0xC1,"DE",(17,15)), (0xC2,"HL",(255,255))]:
    z.setr(pair, (h_ << 8) | l_); z.op(0xED, opb)
    got = z.regs()[pair]; ck(f"mul {pair.lower()} {h_}*{l_}", got == h_*l_, f"got={got} exp={h_*l_}")

# div (ED C6): HL/A -> HL quot, A rem
for hl, a in [(1000, 7), (65535, 255), (500, 0)]:
    z.setr("HL", hl); z.setr("AF", a << 8); z.op(0xED, 0xC6); r = z.regs()
    packed = O._div(hl, a); ck(f"div {hl}/{a}", r["HL"] == lo(packed) and (r["AF"] >> 8) == hi(packed),
                               f"q={r['HL']}/{lo(packed)} rem={r['AF']>>8}/{hi(packed)}")

# isprime (ED C7): HL -> smallest factor; ZF=1 iff prime
for n in [7919, 7917, 65521, 4, 1]:
    z.setr("HL", n); z.op(0xED, 0xC7); r = z.regs()
    exp = O._isprime(n); zf = (r["AF"] & 0x40) != 0
    ck(f"isprime {n}", r["HL"] == exp and zf == (exp == n), f"HL={r['HL']}/{exp} ZF={zf}")

# ispal (ED CA): DE:HL decimal palindrome -> C
for v in [12321, 12345, 0, 7, 1002001]:
    z.setr("HL", lo(v)); z.setr("DE", hi(v)); z.op(0xED, 0xCA); r = z.regs()
    cf = r["AF"] & 1; ck(f"ispal {v}", cf == O._ispal(v), f"C={cf} exp={O._ispal(v)}")

# bselect (ED CB): BC=&bitmap, DE=n, HL=nbits, A=pol -> HL=idx, C=shortfall
z.wmem(BM, bytes([0b10110101, 0b00101110, 0, 0]))
bmv = int.from_bytes(bytes([0b10110101, 0b00101110]), "little")
for n, nbits, pol in [(1,16,1),(3,16,1),(9,16,1),(0,16,1),(4,16,0)]:
    z.setr("BC", BM); z.setr("DE", n); z.setr("HL", nbits); z.setr("AF", pol << 8)
    z.op(0xED, 0xCB); r = z.regs()
    packed = O._bselect(bmv, nbits, n, pol); exp_hl, exp_c = lo(packed), hi(packed) & 1
    ck(f"bselect n={n} pol={pol}", r["HL"] == exp_hl and (r["AF"] & 1) == exp_c,
       f"HL={r['HL']}/{exp_hl} C={r['AF']&1}/{exp_c}")

# mul1 (ED CD): HL=&acc, A=mult, BC=width -> acc*=A in place; C=overflow
for acc, m, w in [(0x0102030405, 7, 6), ((1<<48)-1, 255, 6), (1000000, 3, 6)]:
    z.wmem(OUT, acc.to_bytes(w, "little"))
    z.setr("HL", OUT); z.setr("AF", m << 8); z.setr("BC", w); z.op(0xED, 0xCD); r = z.regs()
    packed = O.BANK_ORACLES["mul1"](acc, m)
    got = int.from_bytes(z.rmem(OUT, w), "little"); got |= ((r["AF"] & 1) << 48)
    ck(f"mul1 {acc}*{m}", got == packed, f"got={got:#x} exp={packed:#x}")

# memset (ED CC): HL=dst, BC=count, A=val -> fill; HL=one-past, BC=0
for count, val in [(5, 0xAB), (0, 0x11)]:
    z.wmem(OUT, bytes(8)); z.setr("HL", OUT); z.setr("BC", count); z.setr("AF", val << 8)
    z.op(0xED, 0xCC); r = z.regs(); mem = z.rmem(OUT, 8)
    want = bytes([val]*count + [0]*(8-count))
    ck(f"memset n={count}", mem == want and r["HL"] == (OUT+count) & 0xFFFF and r["BC"] == 0,
       f"mem={mem.hex()} HL={r['HL']:#x} BC={r['BC']}")

z.cmd("exit")
print(f"\n==== {sum(res)}/{len(res)} checks PASS ====")
sys.exit(0 if all(res) else 1)
