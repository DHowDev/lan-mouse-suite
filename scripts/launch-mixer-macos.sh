#!/usr/bin/env bash
# Native-only entry; leaves legacy suite GUI and running services untouched.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VENV="${LANBRIDGE_MIXER_VENV:-$HOME/.local/share/lanmouse-suite/venv}"
APP="${LANBRIDGE_MIXER_APP:-$ROOT/apps/macos/build/Lan Mouse Suite.app}"
"$VENV/bin/python" -c 'import obsws_python; import lanmouse_suite.mixer_cli' || exit 2
[ -x "$APP/Contents/MacOS/LanMouseSuiteStatus" ] || { printf 'Build first: bash apps/macos/build-app.sh\n'; exit 2; }
printf 'Enable authenticated OBS WebSocket manually on loopback port 4455. No OBS settings are changed.\n'
if [ -z "${LANBRIDGE_OBS_PASSWORD:-}" ]; then
  read -r -s -p 'OBS WebSocket password (not saved): ' LANBRIDGE_OBS_PASSWORD
  printf '\n'
fi
export LANBRIDGE_OBS_PASSWORD
export LANBRIDGE_MIXER_PYTHON="$VENV/bin/python"
exec "$APP/Contents/MacOS/LanMouseSuiteStatus" --mixer-only
