#!/usr/bin/env python3
"""OpenSSH authorized_keys forced-command allowlist for suite endpoints."""
from __future__ import annotations

import argparse
import os
import shlex
from typing import List, Optional


def allowed_arguments(original: str, cli: str, peer_id: str) -> Optional[List[str]]:
    try:
        values = shlex.split(original, posix=True)
    except ValueError:
        return None
    if not values or values[0] != cli:
        return None
    arguments = values[1:]
    if arguments in (["clipboard", "read"], ["clipboard", "write"], ["screenshot", "export", "--request-stdin"]):
        return arguments
    if len(arguments) == 3 and arguments[:2] in (["endpoint", "status"], ["endpoint", "on"], ["endpoint", "off"]) and arguments[2] == peer_id:
        return arguments
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True)
    parser.add_argument("--peer-id", required=True)
    args = parser.parse_args()
    original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    allowed = allowed_arguments(original, args.cli, args.peer_id)
    if allowed is None:
        print("lanmouse-suite forced command: refused", file=__import__("sys").stderr)
        return 126
    os.execv(args.cli, [args.cli] + allowed)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
