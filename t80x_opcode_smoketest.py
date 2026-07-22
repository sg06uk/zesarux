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
    def opt(s, *bytes_):
        """Like op(), but returns the instruction's t-state cost. The counter is
        reset AFTER the register/memory setup so only the cpu-step is measured."""
        s.wmem(CODE, bytes_); s.setr("PC", CODE)
        s.cmd("reset-tstates-partial"); s.cmd("cpu-step")
        m = re.search(r"\d+", s.cmd("get-tstates-partial"))
        return int(m.group(0)) if m else -1

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

# factor (ED C9): HL=&n(len-byte LE), A=len, BC=&out, DE=cap -> factors, HL=count, F=status
NADDR, FOUT = 0x9300, 0x9400
def _isp(m):
    if m < 2: return False
    i = 2
    while i*i <= m:
        if m % i == 0: return False
        i += 1
    return True
def nextp(x):
    while not _isp(x): x += 1
    return x
p = nextp(200000); q = nextp(p+1)
for n, ln, cap in [(12,2,8),(7919,2,8),(1,2,8),(60,2,2),(4294967291,4,8),(p*q,6,8)]:
    z.wmem(NADDR, n.to_bytes(ln, "little")); z.wmem(FOUT, bytes(80))
    z.setr("HL", NADDR); z.setr("AF", ln << 8); z.setr("BC", FOUT); z.setr("DE", cap)
    z.op(0xED, 0xC9); r = z.regs()
    ef, ec, eF = O.factor_all(n, cap)
    gc = r["HL"]; gF = r["AF"] & 0xFF
    raw = z.rmem(FOUT, gc*ln) if gc else b""
    gf = [int.from_bytes(raw[i*ln:(i+1)*ln], "little") for i in range(gc)]
    ck(f"factor {n} cap={cap}", gf == ef and gc == ec and gF == eF,
       f"f={gf}/{ef} cnt={gc}/{ec} F={gF:#x}/{eF:#x}")

# ---------------------------------------------------------------------------
# dec2bin (ED CF) / bin2dec (ED D0) -- radix conversion, added for euler16.
#
# These two also get their CYCLE cost checked, which nothing above does. The
# euler16 tape is a timing race, so a wrong t-state model would leave every
# value check passing while the headline speedup silently lied. Both opcodes
# share one RTL model -- x10 and /10 cost identical silicon; only the software
# differs -- and it is exact on all 19 bench vectors.
# ---------------------------------------------------------------------------
RACC, RDIG = 0x9500, 0xA000
FRAME_T = 69888                      # 48K: 312 scanlines x 224 T
def rtl_cycles(n, w):
    return 13 + 3*n + 6*n*w
def cycles_ok(t, exp):
    """ZEsarUX cannot report a single instruction longer than one frame: the
    end-of-frame handler subtracts screen_testados_total ONCE, so the partial
    counter comes back exactly one frame short. (Worse, the screen clock only
    advances one scanline per instruction whatever t_estados did -- which is why
    FRAMES-based timing under-counts every t80x opcode over ~224 T.) The handler
    is right; the emulator's timebase cannot represent the value. So only assert
    the cycle cost where it fits in a frame, and check the modular remainder
    beyond that rather than pretending we measured it."""
    return t == exp if exp < FRAME_T else t == exp - FRAME_T

# dec2bin: HL=&digits (MSD first), BC=&acc, DE=width, A=ndigits
#          -> acc = value in place; HL/BC one-past-last; C=overflow
for v, w in [(0, 4), (7, 1), (255, 1), (256, 1), (12345, 4), (65535, 2),
             (4294967295, 4), (99999999999999999999, 9),
             (37107287533902102798797998220837590246510135740250, 21)]:
    digits = [int(c) for c in str(v)]
    z.wmem(RDIG, bytes(digits))
    z.wmem(RACC, bytes([0xFF] * w))          # garbage: it must NOT need pre-zeroing
    z.setr("HL", RDIG); z.setr("BC", RACC); z.setr("DE", w)
    z.setr("AF", len(digits) << 8)
    t = z.opt(0xED, 0xCF); r = z.regs()
    got = int.from_bytes(z.rmem(RACC, w), "little")
    exp = O.BANK_ORACLES["dec2bin"](v, w)
    exp_c = 1 if v >= (1 << (8 * w)) else 0
    exp_t = rtl_cycles(len(digits), w)
    ck(f"dec2bin {str(v)[:14]} w={w}",
       got == exp and r["HL"] == (RDIG + len(digits)) & 0xFFFF
       and r["BC"] == (RACC + w) & 0xFFFF and (r["AF"] & 1) == exp_c and cycles_ok(t, exp_t),
       f"acc={got}/{exp} HL={r['HL']:#x}/{(RDIG+len(digits)):#x} "
       f"BC={r['BC']:#x}/{(RACC+w):#x} C={r['AF']&1}/{exp_c} T={t}/{exp_t}")

# bin2dec: HL=&acc (CONSUMED), BC=&out, DE=capacity, A=width
#          -> HL=digit count, BC=one-past-last, C=overflow; digits LSD first
for v, cap in [(0, 64), (7, 64), (255, 64), (12345, 64), (4294967295, 64),
               (99999999999999999999, 64),
               (5537376230390876637302048746832985971773659831892672, 64),
               (123456, 3)]:
    w = max(1, (v.bit_length() + 7) // 8)
    z.wmem(RACC, v.to_bytes(w, "little")); z.wmem(RDIG, bytes(cap + 2))
    z.setr("HL", RACC); z.setr("BC", RDIG); z.setr("DE", cap); z.setr("AF", w << 8)
    t = z.opt(0xED, 0xD0); r = z.regs()
    cnt = r["HL"]
    got = "".join(str(d) for d in z.rmem(RDIG, cnt)[::-1]) if cnt else ""
    exp = O.BANK_ORACLES["bin2dec"](v, cap)
    exp_c = 1 if len(str(v)) > cap else 0
    exp_t = rtl_cycles(cnt, w)
    ck(f"bin2dec {str(v)[:14]} cap={cap}",
       got == exp and cnt == len(exp) and r["BC"] == (RDIG + cnt) & 0xFFFF
       and (r["AF"] & 1) == exp_c and cycles_ok(t, exp_t),
       f"got={got[:20]}/{exp[:20]} n={cnt}/{len(exp)} "
       f"BC={r['BC']:#x}/{(RDIG+cnt):#x} C={r['AF']&1}/{exp_c} T={t}/{exp_t}")

# The euler16 workload itself, end to end: 2^1000 -> 302 digits, one instruction.
# This is the exact call the tape makes, so it is the check that matters most.
BIG = 2 ** 1000
z.wmem(RACC, BIG.to_bytes(126, "little")); z.wmem(RDIG, bytes(320))
z.setr("HL", RACC); z.setr("BC", RDIG); z.setr("DE", 320); z.setr("AF", 126 << 8)
t = z.opt(0xED, 0xD0); r = z.regs()
cnt = r["HL"]
got = "".join(str(d) for d in z.rmem(RDIG, cnt)[::-1]) if cnt else ""
dsum = sum(int(c) for c in got) if got else -1
exp_t = rtl_cycles(302, 126)
ck("bin2dec 2^1000 -> 302 digits, digit sum 1366 (euler16)",
   got == str(BIG) and cnt == 302 and dsum == 1366 and (r["AF"] & 1) == 0 and cycles_ok(t, exp_t),
   f"n={cnt}/302 digitsum={dsum}/1366 C={r['AF']&1}/0 T={t}/{exp_t}")

z.cmd("exit")
print(f"\n==== {sum(res)}/{len(res)} checks PASS ====")
sys.exit(0 if all(res) else 1)
