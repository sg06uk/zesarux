#!/usr/bin/env bash
#
# run-sieve.sh -- launch this ZEsarUX fork, load the t80x prime-constellation
# sieve demo onto it, and run it to completion on the real emulator.
#
#   ./run-sieve.sh              GUI: opens the ZEsarUX window and draws the sieve
#   ./run-sieve.sh --headless   no window; renders a PNG + golden-checks it
#   PORT=10123 ./run-sieve.sh   use a different ZRCP port (default 10099)
#
# Needs: the built binary (src/zesarux), python3, and the bench repo the demo
# reassembles from (~/z80-fpga-bench with z80asm on PATH).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/src"
DEMO="$HERE/t80x_sieve_demo.py"
PORT="${PORT:-10099}"
LOG="/tmp/zesarux-run-$PORT.log"

HEADLESS=0
[ "${1:-}" = "--headless" ] && HEADLESS=1
# no display -> headless whether asked or not
if [ "$HEADLESS" = 0 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  echo "No display detected (DISPLAY/WAYLAND_DISPLAY unset) -> running headless."
  HEADLESS=1
fi

VO=()
[ "$HEADLESS" = 1 ] && VO=(--vo null --ao null)

[ -x "$SRC/zesarux" ] || {
  echo "zesarux is not built. Build it with:"
  echo "  (cd '$SRC' && ./configure && make)"
  exit 1
}
[ -f "$DEMO" ] || { echo "demo not found: $DEMO"; exit 1; }

echo "Launching ZEsarUX (ZRCP port $PORT$([ "$HEADLESS" = 1 ] && echo ', headless'))..."
"$SRC/zesarux" --noconfigfile --nosplash --nowelcomemessage "${VO[@]}" \
  --enable-remoteprotocol --remoteprotocol-port "$PORT" </dev/null >"$LOG" 2>&1 &
ZPID=$!
cleanup() { kill "$ZPID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# wait for the remote-protocol port to come up
for _ in $(seq 1 20); do
  (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$PORT" && break
  kill -0 "$ZPID" 2>/dev/null || { echo "emulator exited early; log:"; tail -n 8 "$LOG"; exit 1; }
  sleep 1
done

rc=0
python3 "$DEMO" "$PORT" || rc=$?

if [ "$HEADLESS" = 1 ]; then
  echo "Done (headless), exit=$rc."
  exit "$rc"
fi

echo
echo "Sieve loaded and run (exit=$rc). The ZEsarUX window shows PRIMES=5051 + the constellation."
echo "Press Ctrl-C here to close the emulator."
wait "$ZPID"
