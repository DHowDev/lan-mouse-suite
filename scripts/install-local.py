#!/usr/bin/env python3
"""Install the local source tree into the active Python environment.

This deliberately uses only the standard library so platform installers do not
need setuptools, wheel, network access, or build isolation just to install a
checked-out copy. Release wheels remain supported through normal pip tooling.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
import sysconfig
from pathlib import Path


def _write_unix_launcher(path: Path, module: str) -> None:
    content = "#!%s\nfrom %s import main\nraise SystemExit(main())\n" % (sys.executable, module)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_windows_launcher(path: Path, module: str, gui: bool = False) -> None:
    executable = Path(sys.executable)
    if gui:
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    value = '@echo off\r\n"%s" -m %s %%*\r\n' % (executable, module)
    path.write_text(value, encoding="utf-8", newline="")


def main() -> int:
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        print("install-local.py must run with the suite private virtualenv Python", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    source = root / "src" / "lanmouse_suite"
    if not (source / "__init__.py").is_file():
        print("lanmouse_suite source package is missing", file=sys.stderr)
        return 2
    purelib = Path(sysconfig.get_paths()["purelib"])
    scripts = Path(sysconfig.get_paths()["scripts"])
    destination = purelib / "lanmouse_suite"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    scripts.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        _write_windows_launcher(scripts / "lanmouse-suite.cmd", "lanmouse_suite.cli")
        _write_windows_launcher(scripts / "lanmouse-suite-gui.cmd", "lanmouse_suite.gui", gui=True)
    else:
        _write_unix_launcher(scripts / "lanmouse-suite", "lanmouse_suite.cli")
        _write_unix_launcher(scripts / "lanmouse-suite-gui", "lanmouse_suite.gui")
    print("installed lanmouse_suite into %s" % purelib)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
