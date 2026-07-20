#!/usr/bin/env python3
"""Build a Spectrum .tap from the z80-fpga-bench's OWN Euler exercise sources.

    python3 make-euler-tap.py <n>          # n = 6,7,8,9,10  -> eulerN.tap

The bench already carries an opcode build and an all-software twin for each
puzzle, written and RTL-profiled there. This takes those .asm files verbatim,
runs them through the bench's own preprocess.py (so the custom mnemonics expand
exactly as the bench expands them), and wraps them so BASIC can USR them:

  * `org 0`      -> the address the REM statement actually lands on
  * entry        -> save BASIC's SP, then jp start
  * `done: halt` -> restore SP, then ret

Nothing inside the algorithm is touched, so the tape races the SAME code the
bench profiles and the timings are directly comparable to its cycle tables.
BASIC does a CLEAR first so the interpreter stays below the exercise's data.
"""
import sys, os, re, subprocess, tempfile

BENCH = "/home/sg06uk/z80-fpga-bench"
sys.path.insert(0, BENCH)
from harness.preprocess import preprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SAVESP = 0xFFFC
REPCNT = 0xFFF8

EX = {
    6:  dict(rep=2000, d="euler6",  op="euler6_mull.asm",      sw="euler6_nomul.asm",
             answer=None, nbytes=4, clear=32767,
             title=["sum-square difference", "for 1 to 100"]),
    7:  dict(rep=20, d="euler7",  op="euler7_sieve_op.asm",  sw="euler7_sieve.asm",
             answer=None, nbytes=4, clear=32767,
             title=["the 10001st prime"]),
    8:  dict(rep=200, d="euler8",  op="euler8_op.asm",        sw="euler8_vanilla.asm",
             answer=None, nbytes=8, clear=32767,
             title=["largest product of 13", "adjacent digits"]),
    9:  dict(rep=200, d="euler9",  op="euler9_euclid_op.asm", sw="euler9_euclid_sw.asm",
             answer=0xF020, nbytes=4, clear=59999,
             title=["Pythagorean triplet", "with a+b+c=1000"]),
    # euler10's sources are TEMPLATES built by its own profile.py (build_op_src /
    # build_sw_src). Its software leg at the full 2,000,000 limit is impractical on
    # a Spectrum -- the bench only sanity-checks sw at 50,000 -- so the tape uses
    # that same reduced limit for BOTH legs, keeping the race like-for-like.
    10: dict(rep=1, d="euler10", srcmod=True, limit=50000,
             answer=0xF020, nbytes=6, clear=32767,
             title=["sum of all primes", "below 50,000"]),
}

def answer_addr(cfg):
    """ANSWER_ADDR from the exercise's own profile.py unless pinned above."""
    if cfg["answer"] is not None:
        return cfg["answer"]
    p = open(os.path.join(BENCH, "exercises", cfg["d"], "profile.py")).read()
    m = re.search(r"^ANSWER_ADDR\s*=\s*(0x[0-9A-Fa-f]+|\d+)", p, re.M)
    if not m:
        sys.exit(f"could not find ANSWER_ADDR in {cfg['d']}/profile.py")
    return int(m.group(1), 0)

def adapt(src, org, rep):
    """org -> real address; strip the exercise's own `ld sp`, wrap the body in a
    CALL-based repeat loop, and turn `done: halt` into `ret` so BASIC can USR it.
    The algorithm itself is untouched."""
    src = preprocess(src)
    if not re.search(r"^\s*org\s", src, re.M):
        src = "        org 0\n" + src
    src = re.sub(r"^\s*org\s+\S+\s*$", "        org %d" % org, src, count=1, flags=re.M)
    # the exercise sets its own stack; the stub owns SP instead so CALL/RET work
    src = re.sub(r"^\s*ld\s+sp\s*,\s*0x[0-9A-Fa-f]+\s*$", "", src, flags=re.M)
    stub = ("\n        ld (%d),sp\n        ld sp,0xFFF0\n        ld hl,%d\n"
            "        ld (%d),hl\n__rep:  call start\n        ld hl,(%d)\n        dec hl\n"
            "        ld (%d),hl\n        ld a,h\n        or l\n        jp nz,__rep\n"
            "        ld sp,(%d)\n        ret") % (SAVESP, rep, REPCNT, REPCNT, REPCNT, SAVESP)
    src = re.sub(r"(^\s*org\s+\d+\s*$)", r"\1" + stub.replace("\\", "\\\\"), src, count=1, flags=re.M)
    src, n = re.subn(r"(^done:\s*$\n)\s*halt\s*$", r"\1        ret", src, count=1, flags=re.M)
    if not n:
        src, n = re.subn(r"^(done:)\s*\n?\s*halt\s*$", r"\1\n        ret", src, count=1, flags=re.M)
    if not n:
        sys.exit("could not find the 'done: halt' terminator")
    return src

def assemble(src, org):
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "r.asm"), "w").write(src)
        r = subprocess.run(["z80asm", "-b", "-or.bin", "r.asm"], cwd=d, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"z80asm failed:\n{r.stdout}{r.stderr}")
        b = list(open(os.path.join(d, "r.bin"), "rb").read())
        return b[org:] if len(b) > org > 0 else b

TOK = {'REM':0xEA,'RANDOMIZE':0xF9,'USR':0xC0,'LET':0xF1,'PEEK':0xBE,'PRINT':0xF5,
       'INT':0xBA,'CLEAR':0xFD}
def K(*n): return [TOK[x] for x in n]
def num(v): return list(str(v).encode()) + [0x0E,0x00,0x00,v & 0xFF,(v >> 8) & 0xFF,0x00]
def s(t): return list(t.encode())
def peekn(b, n):
    """b + 256*(b+1 + 256*(...)) -- Horner, so no literal exceeds 65535."""
    out = K('PEEK') + num(b + n - 1)
    for i in range(n - 2, -1, -1):
        out = K('PEEK') + num(b + i) + s('+') + num(256) + s('*(') + out + s(')')
    return out
def frames():
    return (K('PEEK')+num(23672)+s('+')+num(256)+s('*(')+K('PEEK')+num(23673)+s('+')
            +num(256)+s('*')+K('PEEK')+num(23674)+s(')'))
def line(n, body):
    d = body + [0x0D]
    return [(n>>8)&0xFF, n&0xFF, len(d)&0xFF, (len(d)>>8)&0xFF] + d
def block(flag, data):
    body = [flag] + data
    c = 0
    for x in body: c ^= x
    return [len(body+[c]) & 0xFF, (len(body+[c]) >> 8) & 0xFF] + body + [c]

def build(n):
    cfg = EX[n]
    if cfg.get("srcmod"):
        import importlib.util
        mp = os.path.join(BENCH, "exercises", cfg["d"], "profile.py")
        spec = importlib.util.spec_from_file_location("ex_%s" % cfg["d"], mp)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        op_src = mod.build_op_src(cfg["limit"])
        sw_src = mod.build_sw_src(cfg["limit"])
    else:
        zdir = os.path.join(BENCH, "exercises", cfg["d"], "z80")
        op_src = open(os.path.join(zdir, cfg["op"])).read()
        sw_src = open(os.path.join(zdir, cfg["sw"])).read()
    addr, nb = answer_addr(cfg), cfg["nbytes"]

    PROG = 23755
    rep = cfg["rep"]
    l1 = len(assemble(adapt(op_src, 0, rep), 0))          # pass 1: size only
    usr_op = PROG + 5
    usr_sw = PROG + (4 + 1 + l1 + 1) + 5
    OPB = assemble(adapt(op_src, usr_op, rep), usr_op)    # pass 2: real orgs
    SWB = assemble(adapt(sw_src, usr_sw, rep), usr_sw)
    assert len(OPB) == l1, "size shifted between passes"

    prog = []
    prog += line(1, K('REM') + OPB)
    prog += line(2, K('REM') + SWB)
    prog += line(5, K('CLEAR') + num(cfg["clear"]))
    ln = 10
    for t in cfg["title"]:
        prog += line(ln, K('PRINT') + s('"%s"' % t)); ln += 10
    prog += line(ln,    K('LET')+s('f=')+frames());                      ln += 10
    prog += line(ln,    K('RANDOMIZE','USR')+num(usr_op));               ln += 10
    prog += line(ln,    K('LET')+s('o=')+frames()+s('-f'));              ln += 10
    prog += line(ln,    K('LET')+s('a=')+peekn(addr, nb));               ln += 10
    prog += line(ln,    K('PRINT')+s('"answer = ";a'));                  ln += 10
    prog += line(ln,    K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"')); ln += 10
    prog += line(ln,    K('LET')+s('f=')+frames());                      ln += 10
    prog += line(ln,    K('RANDOMIZE','USR')+num(usr_sw));               ln += 10
    prog += line(ln,    K('LET')+s('w=')+frames()+s('-f'));              ln += 10
    prog += line(ln,    K('LET')+s('b=')+peekn(addr, nb));               ln += 10
    prog += line(ln,    K('PRINT')+s('"software: ";w/')+num(50)+s(';" s (";b;")"')); ln += 10
    prog += line(ln,    K('PRINT')+num(rep)+s(';" runs; opcode ";')+K('INT')+s('(w/o);"x"'))

    plen = len(prog)
    name = ("EULER%-5d" % n)[:10].encode()
    header = [0x00] + list(name) + [plen & 0xFF, plen >> 8, 5, 0, plen & 0xFF, plen >> 8]
    out = os.path.join(HERE, "euler%d.tap" % n)
    open(out, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
    print(f"wrote {out}: program {plen}B; op {len(OPB)}B @ {usr_op}, sw {len(SWB)}B @ {usr_sw}; "
          f"answer@{addr:#06x} x{nb}B")

if __name__ == "__main__":
    build(int(sys.argv[1]))
