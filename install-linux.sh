#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/lanmouse-suite/venv"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/lanmouse-suite"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/lanmouse-suite"
SYSTEM_DEPS=0
ACTIVATE=0
UPSTREAM_URL=""
UPSTREAM_SHA256=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --system-deps) SYSTEM_DEPS=1 ;;
    --activate) ACTIVATE=1 ;;
    --upstream-url) [ "$#" -ge 2 ] || { printf '%s\n' '--upstream-url requires a value' >&2; exit 2; }; UPSTREAM_URL="$2"; shift ;;
    --upstream-sha256) [ "$#" -ge 2 ] || { printf '%s\n' '--upstream-sha256 requires a value' >&2; exit 2; }; UPSTREAM_SHA256="$2"; shift ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$SYSTEM_DEPS" -eq 1 ]; then
  if command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed python python-pip tk wl-clipboard openssh lan-mouse
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip python3-tk wl-clipboard openssh-client
  else
    printf 'Unsupported package manager; install Python 3.9+, Tk, wl-clipboard, and OpenSSH.\n' >&2
    exit 2
  fi
fi
PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || { printf 'Python 3 is required.\n' >&2; exit 2; }
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' || { printf 'Python 3.9+ is required.\n' >&2; exit 2; }
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" "$ROOT/scripts/install-local.py"
mkdir -p "$CONFIG_DIR" "$DATA_DIR/templates" "$HOME/.config/systemd/user"
NEW_CONFIG=0
if [ ! -f "$CONFIG_DIR/config.json" ]; then
  cp "$ROOT/examples/config.example.json" "$CONFIG_DIR/config.json"
  chmod 600 "$CONFIG_DIR/config.json"
  NEW_CONFIG=1
fi
UPSTREAM_CANDIDATE=""
if [ -n "$UPSTREAM_URL" ] || [ -n "$UPSTREAM_SHA256" ]; then
  [ -n "$UPSTREAM_URL" ] && [ -n "$UPSTREAM_SHA256" ] || { printf 'Both upstream URL and SHA-256 are required.\n' >&2; exit 2; }
  UPSTREAM_CANDIDATE="$HOME/.local/bin/lan-mouse"
  "$VENV/bin/python" "$ROOT/scripts/install-upstream.py" --platform Linux --url "$UPSTREAM_URL" --sha256 "$UPSTREAM_SHA256" --output "$UPSTREAM_CANDIDATE"
fi
CONFIGURE=("$VENV/bin/python" "$ROOT/scripts/configure-new-config.py" --config "$CONFIG_DIR/config.json")
if [ "$NEW_CONFIG" -eq 1 ]; then CONFIGURE+=(--new-config); fi
if [ -n "$UPSTREAM_CANDIDATE" ]; then CONFIGURE+=(--candidate "$UPSTREAM_CANDIDATE"); fi
"${CONFIGURE[@]}"
if [ "$NEW_CONFIG" -eq 1 ]; then "$VENV/bin/lanmouse-suite" --config "$CONFIG_DIR/config.json" off >/dev/null; fi
"$VENV/bin/python" -c 'from pathlib import Path; import sys; Path(sys.argv[2]).write_text(Path(sys.argv[1]).read_text().replace("@CLI@", sys.argv[3]))' \
  "$ROOT/templates/systemd/lanmouse-suite.service" "$HOME/.config/systemd/user/lanmouse-suite.service" "$VENV/bin/lanmouse-suite"
"$VENV/bin/python" -c 'from pathlib import Path; import sys; Path(sys.argv[2]).write_text(Path(sys.argv[1]).read_text().replace("@GUI@", sys.argv[3]))' \
  "$ROOT/templates/autostart/lanmouse-suite.desktop" "$DATA_DIR/templates/lanmouse-suite.desktop" "$VENV/bin/lanmouse-suite-gui"
if [ "$ACTIVATE" -eq 1 ]; then
  "$VENV/bin/lanmouse-suite" --config "$CONFIG_DIR/config.json" config validate
  DOCTOR_JSON="$($VENV/bin/lanmouse-suite --config "$CONFIG_DIR/config.json" doctor --json)"
  "$VENV/bin/python" -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d["checks"]["executable"]["status"]=="ok" else 1)' "$DOCTOR_JSON" || { printf 'Activation refused: doctor executable check is not OK.\n%s\n' "$DOCTOR_JSON" >&2; exit 2; }
  mkdir -p "$HOME/.config/autostart"
  cp "$DATA_DIR/templates/lanmouse-suite.desktop" "$HOME/.config/autostart/lanmouse-suite.desktop"
  systemctl --user daemon-reload
  systemctl --user enable --now lanmouse-suite.service
  ENABLED="$(systemctl --user is-enabled lanmouse-suite.service)"
  ACTIVE="$(systemctl --user is-active lanmouse-suite.service)"
  if [ "$ENABLED" != "enabled" ] || [ "$ACTIVE" != "active" ]; then
    systemctl --user disable --now lanmouse-suite.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/autostart/lanmouse-suite.desktop"
    printf 'Activation verification failed; service was disabled/stopped (enabled=%s active=%s).\n' "$ENABLED" "$ACTIVE" >&2
    exit 2
  fi
  printf 'Activated and verified: lanmouse-suite.service enabled/active.\n'
else
  printf 'Staged only: files and templates installed; no service/status activation command was run. Rerun with --activate after doctor review.\n'
fi
printf 'Installed. Edit %s, then run %s doctor --json.\n' "$CONFIG_DIR/config.json" "$VENV/bin/lanmouse-suite"
