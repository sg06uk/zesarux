#!/usr/bin/env bash
# run-emu.sh -- launch this ZEsarUX fork clean: no splash, no welcome message, no
# first-start wizard, no first-aid popups. Just the emulator (with the t80x
# coprocessor built in) straight to a Spectrum. Extra args pass through, e.g.
#   ./run-emu.sh                       # clean boot
#   ./run-emu.sh --machine 128k        # pick a machine
#   ./run-emu.sh --enable-remoteprotocol --remoteprotocol-port 10099
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/src/zesarux" \
  --nosplash --nowelcomemessage --disable-first-start-wizard --disable-all-first-aid "$@"
