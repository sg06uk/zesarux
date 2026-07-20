#!/usr/bin/env bash
# run-emu.sh -- launch this ZEsarUX fork clean: no splash, no welcome message, no
# first-start wizard, no first-aid popups. Just the emulator (with the t80x
# coprocessor built in) straight to a Spectrum. Extra args pass through, e.g.
#   ./run-emu.sh                       # clean boot
#   ./run-emu.sh --machine 128k        # pick a machine
#   ./run-emu.sh --enable-remoteprotocol --remoteprotocol-port 10099
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Fail loudly on a tape/snapshot that isn't there -- ZEsarUX silently ignores a
# missing file, which just looks like "the emulator did nothing".
for a in "$@"; do
  case "$a" in
    -*) ;;
    *.tap|*.tzx|*.sna|*.z80|*.szx)
        [ -f "$a" ] || [ -f "$HERE/$a" ] || {
          echo "run-emu.sh: no such file: $a" >&2
          echo "available in $HERE:" >&2
          ls -1 "$HERE"/*.tap 2>/dev/null | sed 's|.*/|  |' >&2
          exit 1; } ;;
  esac
done
exec "$HERE/src/zesarux" \
  --nosplash --nowelcomemessage --disable-first-start-wizard --disable-all-first-aid "$@"
