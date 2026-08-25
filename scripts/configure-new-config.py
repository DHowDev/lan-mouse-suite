#!/usr/bin/env python3
"""Choose and persist an existing upstream executable for a new config only."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


def candidates(explicit: List[str]) -> List[Path]:
    values = [Path(value).expanduser() for value in explicit if value]
    found = shutil.which("lan-mouse")
    if found:
        values.append(Path(found))
    home = Path.home()
    if platform.system() == "Darwin":
        values.extend([
            home / "Applications/Lan Mouse.app/Contents/MacOS/lan-mouse",
            Path("/Applications/Lan Mouse.app/Contents/MacOS/lan-mouse"),
            Path("/opt/homebrew/bin/lan-mouse"),
            Path("/usr/local/bin/lan-mouse"),
        ])
    elif platform.system() == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
        values.extend([local / "LanMouse/lan-mouse.exe", local / "Programs/Lan Mouse/lan-mouse.exe"])
    else:
        values.extend([home / ".local/bin/lan-mouse", Path("/usr/bin/lan-mouse"), Path("/usr/local/bin/lan-mouse")])
    return values


def select(explicit: List[str]) -> Optional[Path]:
    seen = set()
    for candidate in candidates(explicit):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if str(resolved) in seen or not resolved.is_file() or not os.access(str(resolved), os.X_OK):
            continue
        seen.add(str(resolved))
        try:
            probe = subprocess.run([str(resolved), "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return resolved
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--new-config", action="store_true")
    parser.add_argument("--candidate", action="append", default=[])
    args = parser.parse_args()
    if not args.new_config:
        print("existing config preserved")
        return 0
    chosen = select(args.candidate)
    if chosen is None:
        print("no verified upstream executable found")
        return 0
    value = json.loads(args.config.read_text(encoding="utf-8"))
    value.setdefault("upstream", {})["binary"] = str(chosen)
    temporary = args.config.with_name(args.config.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, args.config)
    print("selected upstream executable: %s" % chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
