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

KNOWN LIMITATION -- FRAMES CANNOT TIME A LONG OPCODE
----------------------------------------------------
These tapes time with the FRAMES system variable, which counts the 50 Hz
maskable interrupt. A wide t80x opcode breaks that: a Z80 only samples INT at an
instruction boundary, so an opcode longer than the interrupt period (or a chain
of them) makes the CPU miss interrupts it should have taken, and FRAMES counts
fewer than really elapsed. This is backlog NX-018, and it is NOT an emulator
artefact -- real hardware drops exactly the same interrupts. Measured on the
shipped euler16 tape: the opcode leg reads 0.04 s (true cost ~0.27 s by cycles),
inflating the printed speedup from 133x to 881x.

This bites every opcode wide enough to straddle the interrupt period, so it is
NOT specific to euler16:

    bstride  ~450k T      factor    ~30k T      bin2dec/dec2bin  up to 229k T
    memset   >75 bytes    mul1      >37 limbs   isprime          >12 trials

Exercises whose opcode leg contains such an instruction set `truex` (the bench's
cycle-accurate ratio) so the tape prints that instead of a FRAMES figure this
timebase cannot produce.

Do NOT confuse this with the separate scanline-clock bug (core_spectrum.c
cpu_core_loop was `if`, now `while`), which made the SCREEN clock advance only
one scanline per instruction. That fix, 2026-07-22, corrected rendering and
get-tstates-partial for wide opcodes but left this FRAMES number unchanged (the
tape still reads 881x) -- proving the under-count is interrupt-driven, not
scanline-driven. `truex` stays necessary regardless.
"""
import sys, os, re, subprocess, tempfile

BENCH = "/home/sg06uk/z80-fpga-bench"
sys.path.insert(0, BENCH)
from harness.preprocess import preprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SAVESP = 0xFFFC
REPCNT = 0xFFF8

EX = {
    6:  dict(rep=1500, d="euler6",  op="euler6_mull.asm",      sw="euler6_nomul.asm",
             answer=None, nbytes=4, clear=32767,
             title=["sum-square difference", "for 1 to 100"]),
    7:  dict(rep=1, d="euler7",  op="euler7_sieve_op.asm",  sw="euler7_sieve.asm",
             answer=None, nbytes=4, clear=32767,
             title=["the 10001st prime"]),
    # euler8's .asm carry a `; @@DIGITS@@` placeholder that its profile.py fills
    # with the 1000-digit number via defb_block(); without it the program
    # multiplies whatever happens to be in RAM.
    8:  dict(rep=1, d="euler8",  op="euler8_op.asm",        sw="euler8_vanilla.asm",
             fixups=[("; @@DIGITS@@", "defb_block")],
             answer=None, nbytes=6, clear=32767,
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
    # euler16 races variant 3 (one `bin2dec`) against variant 1 (pure software).
    # Its data lives at 0x8000-0x833F, so CLEAR must keep BASIC below that.
    # rep=3 balances the two legs: ~28 s of software against ~10 frames of
    # opcode, which is enough resolution for the ratio without a long wait.
    #
    # The opcode leg is `euler16_chunk.asm`, NOT the bench's variant 3, and the
    # reason is worth recording because it breaks this builder's usual promise.
    #
    # Variant 3 converts 2^1000 in ONE `bin2dec` lasting 229,231 T = 3.28 frames.
    # A Z80 only samples INT at an instruction boundary, so the machine takes one
    # interrupt where it should take three and loses the rest -- FRAMES then
    # under-counts the opcode leg and this tape reported 587x against a true
    # 133x. That is backlog NX-018 with a number on it, and it is NOT an emulator
    # artefact: real hardware drops the same interrupts.
    #
    # `euler16_chunk.asm` is variant 3 calling `bin2dec` in 32-digit slices, which
    # bounds each instruction to 24,301 T = 0.35 frames. Measured on the RTL it
    # costs +0.61% (230,679 vs 229,284) and needs no silicon change. So the tape
    # races interrupt-SAFE code, and its ratio is trustworthy; the bench keeps the
    # single-shot version as the clean cycle measurement.
    16: dict(rep=3, d="euler16", op="euler16_chunk.asm", sw="euler16.asm",
             answer=None, nbytes=2, clear=32767, truex="133",
             title=["sum of the digits", "of 2^1000"]),
    # euler25 races variant 3 (`mpn_add_n`) against variant 1 (pure software) --
    # ~4,780 wide adds of a value growing to 415 bytes. Its `; @@KDATA@@` slot is
    # filled with 10^999 (the 1000-digit threshold) via profile.py's kdata(),
    # exactly like euler8's digit table.
    #
    # `truex` IS needed, and the reason corrects a tempting mis-analysis. The
    # threshold for the FRAMES under-count is NOT the frame period (69,888 T) --
    # it is the maskable interrupt PULSE WIDTH (~32 T). The Z80 samples INT only
    # at an instruction boundary, so any instruction much longer than the pulse
    # can be executing across the whole pulse and miss it. The widest `mpn_add_n`
    # is 12+9*415 = 3,747 T >> 32 T, and the opcode leg is ~99% `mpn_add_n` by
    # cycles, so most interrupt pulses land mid-opcode and are lost: measured, the
    # tape reads the opcode leg as 0.4 s (true ~2.9 s), inflating 4.91x to ~43x.
    # This is NX-018 and it is faithful to hardware -- a real Spectrum drops the
    # same interrupts. So we print the bench's cycle-accurate 4.9x, like euler16.
    # (The comparison that matters is opcode-vs-pulse, not opcode-vs-frame.)
    25: dict(rep=1, d="euler25", op="euler25_op.asm", sw="euler25.asm",
             fixups=[("; @@KDATA@@", "kdata")],
             answer=None, nbytes=2, clear=32767, truex="4.9",
             title=["first Fibonacci with", "1000 digits"]),
}

def answer_addr(cfg, op_src=None):
    """The exercise declares its own `defc answer = ADDR`; prefer that. Fall back
    to ANSWER_ADDR in profile.py (used by the template-built exercises)."""
    if cfg["answer"] is not None:
        return cfg["answer"]
    if op_src:
        m = re.search(r"^\s*defc\s+answer\s*=\s*(0x[0-9A-Fa-f]+|\d+)", op_src, re.M)
        if m:
            return int(m.group(1), 0)
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
       'INT':0xBA,'CLEAR':0xFD,'POKE':0xF4}
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
        for ph, fn in cfg.get("fixups", []):
            import importlib.util
            mp = os.path.join(BENCH, "exercises", cfg["d"], "profile.py")
            spec = importlib.util.spec_from_file_location("ex_%s" % cfg["d"], mp)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            filled = getattr(mod, fn)()
            op_src = op_src.replace(ph, filled)
            sw_src = sw_src.replace(ph, filled)
    # never ship a source with an unfilled template slot -- it assembles fine and
    # then silently computes nonsense (this bit euler8's digit table)
    for nm, src in (("op", op_src), ("sw", sw_src)):
        if "@@" in src:
            sys.exit("euler%d %s source still has an unfilled placeholder: %s"
                     % (n, nm, re.findall(r"@@[A-Z_]+@@", src)[:3]))
    addr, nb = answer_addr(cfg, op_src), cfg["nbytes"]

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
    for i in range(nb):
        prog += line(ln, K('POKE')+num(addr+i)+s(',')+num(0)); ln += 10
    prog += line(ln,    K('LET')+s('f=')+frames());                      ln += 10
    prog += line(ln,    K('RANDOMIZE','USR')+num(usr_op));               ln += 10
    prog += line(ln,    K('LET')+s('o=')+frames()+s('-f'));              ln += 10
    prog += line(ln,    K('LET')+s('o=o+(o=')+num(0)+s(')'));            ln += 10
    prog += line(ln,    K('LET')+s('a=')+peekn(addr, nb));               ln += 10
    prog += line(ln,    K('PRINT')+s('"answer = ";a'));                  ln += 10
    prog += line(ln,    K('PRINT')+s('"opcode:   ";o/')+num(50)+s(';" s"')); ln += 10
    for i in range(nb):
        prog += line(ln, K('POKE')+num(addr+i)+s(',')+num(0)); ln += 10
    prog += line(ln,    K('LET')+s('f=')+frames());                      ln += 10
    prog += line(ln,    K('RANDOMIZE','USR')+num(usr_sw));               ln += 10
    prog += line(ln,    K('LET')+s('w=')+frames()+s('-f'));              ln += 10
    prog += line(ln,    K('LET')+s('b=')+peekn(addr, nb));               ln += 10
    prog += line(ln,    K('PRINT')+s('"software: ";w/')+num(50)+s(';" s (";b;")"')); ln += 10
    # A FRAMES-derived ratio is only trustworthy when the opcode leg takes an
    # interrupt every frame like ordinary code does. The maskable INT is asserted
    # for only a short PULSE (~32 T); the Z80 samples INT at an instruction
    # boundary, so any opcode much longer than that pulse can execute clean across
    # it and miss it (NX-018; real hardware drops the same interrupts). The
    # threshold is opcode-vs-PULSE, NOT opcode-vs-frame: bin2dec (229k T) exceeds
    # a whole frame, but even mpn_add_n (up to 3,747 T, well under a frame) loses
    # most interrupts because 3,747 T >> 32 T. An exercise whose opcode leg
    # contains such an instruction sets `truex` and we print the bench's cycle-
    # accurate figure instead of a number this timebase cannot produce.
    if cfg.get("truex"):
        prog += line(ln, K('PRINT')+s('"opcode %sx (bench cycles)"' % cfg["truex"]));   ln += 10
        prog += line(ln, K('PRINT')+s('"the timer above under-"'));                     ln += 10
        prog += line(ln, K('PRINT')+s('"counts: a wide opcode"'));                       ln += 10
        prog += line(ln, K('PRINT')+s('"misses the 50Hz int"'))
    else:
        prog += line(ln, K('PRINT')+num(rep)+s(';" runs; opcode ";')+K('INT')
                         +s('(w/o*')+num(100)+s(')/')+num(100)+s(';"x"'))

    plen = len(prog)
    name = ("EULER%-5d" % n)[:10].encode()
    header = [0x00] + list(name) + [plen & 0xFF, plen >> 8, 5, 0, plen & 0xFF, plen >> 8]
    out = os.path.join(HERE, "euler%d.tap" % n)
    open(out, "wb").write(bytes(block(0x00, header) + block(0xFF, prog)))
    print(f"wrote {out}: program {plen}B; op {len(OPB)}B @ {usr_op}, sw {len(SWB)}B @ {usr_sw}; "
          f"answer@{addr:#06x} x{nb}B")

if __name__ == "__main__":
    build(int(sys.argv[1]))
