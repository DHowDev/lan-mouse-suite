#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUT="${1:-$ROOT/build/Lan Mouse Suite.app}"
STAGE="${OUT}.stage.$$"
BACKUP="${OUT}.previous.$$"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT HUP INT TERM
rm -rf "$STAGE" "$BACKUP"
mkdir -p "$STAGE/Contents/MacOS"
cp "$ROOT/Info.plist" "$STAGE/Contents/Info.plist"
xcrun swiftc -parse-as-library -framework AppKit -framework Foundation \
  "$ROOT/Sources/LanMouseSuiteStatus.swift" -o "$STAGE/Contents/MacOS/LanMouseSuiteStatus"
codesign --force --deep --sign - "$STAGE"
codesign --verify --deep --strict "$STAGE"
if [ -e "$OUT" ]; then mv "$OUT" "$BACKUP"; fi
if mv "$STAGE" "$OUT"; then
  rm -rf "$BACKUP"
else
  [ ! -e "$BACKUP" ] || mv "$BACKUP" "$OUT"
  exit 1
fi
printf 'Built and signed %s\n' "$OUT"
