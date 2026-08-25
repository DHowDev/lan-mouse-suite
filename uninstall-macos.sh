#!/usr/bin/env bash
set -euo pipefail
PURGE=0
[ "${1:-}" = "--purge-config" ] && PURGE=1
CLI="$HOME/.local/share/lanmouse-suite/venv/bin/lanmouse-suite"
CONFIG="$HOME/Library/Application Support/LanMouseSuite/config.json"
if [ -x "$CLI" ] && [ -f "$CONFIG" ]; then
  "$CLI" --config "$CONFIG" all-off >/dev/null || { printf 'Refusing uninstall: owned-process/remote OFF verification failed; state was preserved.\n' >&2; exit 2; }
fi
DOMAIN="gui/$(id -u)"
for LABEL in io.nous.lanmouse-suite.service io.nous.lanmouse-suite.status; do
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
done
rm -rf "$HOME/.local/share/lanmouse-suite" "$HOME/Library/Application Support/LanMouseSuite/State" "$HOME/Library/Logs/LanMouseSuite" "$HOME/Applications/Lan Mouse Suite.app"
if [ "$PURGE" -eq 1 ]; then rm -rf "$HOME/Library/Application Support/LanMouseSuite"; fi
printf 'Lan Mouse Suite removed. Upstream Lan Mouse, its config, PEM identity, and authorizations were not touched.\n'
