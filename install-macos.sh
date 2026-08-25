#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV="$HOME/.local/share/lanmouse-suite/venv"
CONFIG_DIR="$HOME/Library/Application Support/LanMouseSuite"
LOG_DIR="$HOME/Library/Logs/LanMouseSuite"
SERVICE_PLIST="$HOME/Library/LaunchAgents/io.nous.lanmouse-suite.service.plist"
STATUS_PLIST="$HOME/Library/LaunchAgents/io.nous.lanmouse-suite.status.plist"
APP="$HOME/Applications/Lan Mouse Suite.app"
ACTIVATE=0
UPSTREAM_URL=""
UPSTREAM_SHA256=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --activate) ACTIVATE=1 ;;
    --upstream-url) [ "$#" -ge 2 ] || { printf '%s\n' '--upstream-url requires a value' >&2; exit 2; }; UPSTREAM_URL="$2"; shift ;;
    --upstream-sha256) [ "$#" -ge 2 ] || { printf '%s\n' '--upstream-sha256 requires a value' >&2; exit 2; }; UPSTREAM_SHA256="$2"; shift ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
if [ -n "$UPSTREAM_URL" ] || [ -n "$UPSTREAM_SHA256" ]; then
  printf 'Explicit upstream download is raw Linux-only. Install a signed macOS app/bundle separately; ZIP bytes will never be written as an executable.\n' >&2
  exit 2
fi
PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || { printf 'Python 3.9+ is required (Apple Python 3.9 is supported).\n' >&2; exit 2; }
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' || { printf 'Python 3.9+ is required.\n' >&2; exit 2; }
"$PYTHON" -m venv "$VENV" || { printf 'Could not create a private venv. Install a local Python 3.9+ package, then retry.\n' >&2; exit 2; }
"$VENV/bin/python" "$ROOT/scripts/install-local.py"
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents" "$HOME/Applications"
NEW_CONFIG=0
if [ ! -f "$CONFIG_DIR/config.json" ]; then
  cp "$ROOT/examples/config.example.json" "$CONFIG_DIR/config.json"
  chmod 600 "$CONFIG_DIR/config.json"
  NEW_CONFIG=1
fi
CONFIGURE=("$VENV/bin/python" "$ROOT/scripts/configure-new-config.py" --config "$CONFIG_DIR/config.json")
if [ "$NEW_CONFIG" -eq 1 ]; then CONFIGURE+=(--new-config); fi
"${CONFIGURE[@]}"
if [ "$NEW_CONFIG" -eq 1 ]; then "$VENV/bin/lanmouse-suite" --config "$CONFIG_DIR/config.json" off >/dev/null; fi
"$VENV/bin/python" -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]).read_text().replace("@CLI@",sys.argv[3]).replace("@LOG_DIR@",sys.argv[4]); Path(sys.argv[2]).write_text(p)' \
  "$ROOT/templates/launchd/io.nous.lanmouse-suite.service.plist" "$SERVICE_PLIST" "$VENV/bin/lanmouse-suite" "$LOG_DIR"
if command -v xcrun >/dev/null 2>&1; then
  "$ROOT/apps/macos/build-app.sh" "$APP"
else
  printf 'Swift/xcrun unavailable; native status app was not built.\n' >&2
fi
"$VENV/bin/python" -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]).read_text().replace("@APP_EXECUTABLE@",sys.argv[3]).replace("@CLI@",sys.argv[4]); Path(sys.argv[2]).write_text(p)' \
  "$ROOT/templates/launchd/io.nous.lanmouse-suite.status.plist" "$STATUS_PLIST" "$APP/Contents/MacOS/LanMouseSuiteStatus" "$VENV/bin/lanmouse-suite"
if [ "$ACTIVATE" -eq 1 ]; then
  [ -x "$APP/Contents/MacOS/LanMouseSuiteStatus" ] || { printf 'Activation refused: Swift-built status app is unavailable.\n' >&2; exit 2; }
  "$VENV/bin/lanmouse-suite" --config "$CONFIG_DIR/config.json" config validate
  DOCTOR_JSON="$($VENV/bin/lanmouse-suite --config "$CONFIG_DIR/config.json" doctor --json)"
  "$VENV/bin/python" -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d["checks"]["executable"]["status"]=="ok" else 1)' "$DOCTOR_JSON" || { printf 'Activation refused: doctor executable check is not OK.\n%s\n' "$DOCTOR_JSON" >&2; exit 2; }
  DOMAIN="gui/$(id -u)"
  launchctl bootout "$DOMAIN/io.nous.lanmouse-suite.service" >/dev/null 2>&1 || true
  launchctl bootout "$DOMAIN/io.nous.lanmouse-suite.status" >/dev/null 2>&1 || true
  launchctl bootstrap "$DOMAIN" "$SERVICE_PLIST"
  launchctl bootstrap "$DOMAIN" "$STATUS_PLIST"
  launchctl kickstart -k "$DOMAIN/io.nous.lanmouse-suite.service"
  launchctl kickstart -k "$DOMAIN/io.nous.lanmouse-suite.status"
  launchctl print "$DOMAIN/io.nous.lanmouse-suite.service" >/dev/null
  launchctl print "$DOMAIN/io.nous.lanmouse-suite.status" >/dev/null
  if ! "$VENV/bin/python" -c 'import os,subprocess,sys,time; target=os.path.realpath(sys.argv[1]); time.sleep(1); out=subprocess.check_output(["/bin/ps","-axo","pid=,comm="],text=True); rows=[line.strip().split(None,1) for line in out.splitlines() if line.strip()]; hits=[r for r in rows if len(r)==2 and os.path.realpath(r[1])==target]; raise SystemExit(0 if len(hits)==1 else 1)' "$APP/Contents/MacOS/LanMouseSuiteStatus"; then
    launchctl bootout "$DOMAIN/io.nous.lanmouse-suite.status" >/dev/null 2>&1 || true
    launchctl bootout "$DOMAIN/io.nous.lanmouse-suite.service" >/dev/null 2>&1 || true
    printf 'Activation verification failed; both LaunchAgents were booted out.\n' >&2
    exit 2
  fi
  printf 'Activated and verified: service/status LaunchAgents loaded; exactly one status process path.\n'
else
  printf 'Staged only: files, LaunchAgent templates, config, and status app (when buildable) installed; no launchctl activation command was run.\n'
fi
printf 'Installed. Edit %s and run %s doctor --json. Grant Accessibility and Input Monitoring to upstream Lan Mouse.\n' "$CONFIG_DIR/config.json" "$VENV/bin/lanmouse-suite"
