#!/usr/bin/env bash
#
# run-demo.sh -- launch this ZEsarUX fork, load a t80x demo onto it, and run it
# to completion on the real emulator.
#
#   ./run-demo.sh                    GUI: sieve (prime constellation)
#   ./run-demo.sh firstlight         GUI: arithmetic demo (mull/gcd -> text)
#   ./run-demo.sh sieve --headless   no window; golden-check + exit
#   PORT=10123 ./run-demo.sh ...     use a different ZRCP port (default 10099)
#
# Needs: the built binary (src/zesarux), python3, and the bench repo the demo
# reassembles from (~/z80-fpga-bench with z80asm on PATH).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/src"
RUNNER="$HERE/t80x_demo.py"
PORT="${PORT:-10099}"

DEMO="sieve"; HEADLESS=0; PYARGS=()
for a in "$@"; do
  case "$a" in
    sieve|firstlight) DEMO="$a" ;;
    --headless) HEADLESS=1 ;;
    *) PYARGS+=("$a") ;;
  esac
done
LOG="/tmp/zesarux-run-$PORT.log"

if [ "$HEADLESS" = 0 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  echo "No display detected -> running headless."
  HEADLESS=1
fi
VO=(); [ "$HEADLESS" = 1 ] && VO=(--vo null --ao null)

[ -x "$SRC/zesarux" ] || { echo "zesarux is not built: (cd '$SRC' && ./configure && make)"; exit 1; }
[ -f "$RUNNER" ] || { echo "runner not found: $RUNNER"; exit 1; }

echo "Launching ZEsarUX (ZRCP port $PORT$([ "$HEADLESS" = 1 ] && echo ', headless')); demo=$DEMO"
# skip every startup gate: splash, welcome, the first-start wizard, and first-aid popups
"$SRC/zesarux" --noconfigfile --nosplash --nowelcomemessage \
  --disable-first-start-wizard --disable-all-first-aid "${VO[@]}" \
  --enable-remoteprotocol --remoteprotocol-port "$PORT" </dev/null >"$LOG" 2>&1 &
ZPID=$!
cleanup() { kill "$ZPID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

for _ in $(seq 1 20); do
  (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$PORT" && break
  kill -0 "$ZPID" 2>/dev/null || { echo "emulator exited early; log:"; tail -n 8 "$LOG"; exit 1; }
  sleep 1
done

rc=0
python3 "$RUNNER" "$DEMO" "$PORT" "${PYARGS[@]}" || rc=$?

if [ "$HEADLESS" = 1 ]; then
  echo "Done (headless), exit=$rc."
  exit "$rc"
fi
echo
echo "$DEMO loaded and run (exit=$rc). The ZEsarUX window shows the result."
echo "Press Ctrl-C here to close the emulator."
wait "$ZPID"
