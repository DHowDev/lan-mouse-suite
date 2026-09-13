#!/usr/bin/env bash
# Launch only the existing suite GUI; never activate services or restart OBS.
set -euo pipefail
VENV="$HOME/.local/share/lanmouse-suite/venv"
[ -x "$VENV/bin/python" ] || { printf 'Run bash install-macos.sh first (without --activate).\n'; exit 2; }
"$VENV/bin/python" -c 'import tkinter' || { printf 'Install a Python with Tk support before using the GUI.\n'; exit 2; }
"$VENV/bin/python" -m pip install 'obsws-python>=1.7,<2'
printf 'OBS: Tools → WebSocket Server Settings → enable server and authentication, port 4455.\nNo OBS settings or recording state are changed by this launcher.\n'
if [ -z "${LANBRIDGE_OBS_PASSWORD:-}" ]; then
  read -r -s -p 'OBS WebSocket password (not saved): ' LANBRIDGE_OBS_PASSWORD
  printf '\n'
fi
export LANBRIDGE_OBS_PASSWORD
exec "$VENV/bin/lanmouse-suite-gui"
