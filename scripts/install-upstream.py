#!/usr/bin/env python3
"""Explicit checksum-required raw Linux upstream downloader."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tempfile
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="explicit HTTPS raw Linux binary URL")
    parser.add_argument("--sha256", required=True, help="publisher-verified SHA-256")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--platform", required=True)
    args = parser.parse_args()
    if args.platform != "Linux":
        parser.error("explicit upstream download supports raw Linux binaries only; ZIP/app bundles require a platform-native verified installer")
    if not args.url.startswith("https://"):
        parser.error("only explicit HTTPS URLs are accepted")
    expected = args.sha256.lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        parser.error("--sha256 must be exactly 64 hex characters")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="lan-mouse-download-")
    os.close(fd)
    try:
        with urllib.request.urlopen(args.url, timeout=60) as response, open(temporary, "wb") as output:
            shutil.copyfileobj(response, output)
        path = Path(temporary)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit("checksum mismatch: expected %s, got %s" % (expected, actual))
        prefix = path.read_bytes()[:4]
        if prefix.startswith(b"PK\x03\x04"):
            raise SystemExit("refusing ZIP archive: raw Linux executable required")
        if prefix != b"\x7fELF":
            raise SystemExit("refusing non-ELF asset: explicit download is raw Linux-only")
        mode = os.stat(temporary).st_mode
        os.chmod(temporary, mode | stat.S_IXUSR)
        os.replace(temporary, args.output)
        print("installed verified raw Linux binary: %s" % args.output)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
