#!/usr/bin/env bash
set -euo pipefail
PURGE=0
[ "${1:-}" = "--purge-config" ] && PURGE=1
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/lanmouse-suite"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/lanmouse-suite/config.json"
if [ -x "$DATA/venv/bin/lanmouse-suite" ] && [ -f "$CONFIG" ]; then
  "$DATA/venv/bin/lanmouse-suite" --config "$CONFIG" all-off >/dev/null || { printf 'Refusing uninstall: owned-process/remote OFF verification failed; state was preserved.\n' >&2; exit 2; }
fi
systemctl --user disable --now lanmouse-suite.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/lanmouse-suite.service" "$HOME/.config/autostart/lanmouse-suite.desktop"
systemctl --user daemon-reload >/dev/null 2>&1 || true
rm -rf "$DATA" "${XDG_STATE_HOME:-$HOME/.local/state}/lanmouse-suite" "${XDG_CACHE_HOME:-$HOME/.cache}/lanmouse-suite"
if [ "$PURGE" -eq 1 ]; then rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/lanmouse-suite"; fi
printf 'Lan Mouse Suite removed. Upstream Lan Mouse and its config were not touched.\n'
