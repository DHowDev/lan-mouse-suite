from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import CommandRunner
from .clipboard import digest, ssh_base_command
from .state import read_json, write_json


def _run(argv: List[str], data: Optional[bytes] = None, timeout: float = 8.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False, shell=False)


def _platform_name(system: str) -> str:
    return "Darwin" if system in {"Darwin", "MacOS"} else system


def read_local(system: str, max_bytes: int) -> Optional[bytes]:
    system = _platform_name(system)
    if system == "Linux":
        result = _run(["wl-paste", "--type", "image/png"], timeout=5)
        return result.stdout if result.returncode == 0 and 0 < len(result.stdout) <= max_bytes else None
    if system == "Darwin":
        with tempfile.NamedTemporaryFile(prefix="lanmouse-image-", suffix=".png", delete=False) as handle:
            path = handle.name
        try:
            script = (
                "on run argv\n"
                "set f to POSIX file (item 1 of argv)\n"
                "set d to (the clipboard as «class PNGf»)\n"
                "set h to open for access f with write permission\n"
                "write d to h\nclose access h\nend run"
            )
            result = _run(["/usr/bin/osascript", "-", path], data=script.encode("utf-8"), timeout=5)
            payload = Path(path).read_bytes() if result.returncode == 0 else b""
            return payload if 0 < len(payload) <= max_bytes else None
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    return None


def write_local(system: str, data: bytes, max_bytes: int) -> bool:
    system = _platform_name(system)
    if not data or len(data) > max_bytes:
        return False
    if system == "Linux":
        return _run(["wl-copy", "--type", "image/png"], data=data, timeout=5).returncode == 0
    if system == "Darwin":
        with tempfile.NamedTemporaryFile(prefix="lanmouse-image-", suffix=".png", delete=False) as handle:
            handle.write(data)
            path = handle.name
        try:
            script = (
                "on run argv\n"
                "set f to POSIX file (item 1 of argv)\n"
                "set d to read f as «class PNGf»\n"
                "set the clipboard to {«class PNGf»:d}\nend run"
            )
            return _run(["/usr/bin/osascript", "-", path], data=script.encode("utf-8"), timeout=5).returncode == 0
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    return False


def remote_image_command(peer: Dict[str, Any], action: str, ssh_binary: str = "ssh") -> List[str]:
    if action not in {"read", "write"}:
        raise ValueError("invalid image clipboard action")
    remote_cli = peer.get("ssh", {}).get("remote_cli", "lanmouse-suite")
    return ssh_base_command(peer, ssh_binary) + [remote_cli, "clipboard", "image-" + action]


class RemoteImageClipboard:
    def __init__(self, peer: Dict[str, Any], runner: Optional[CommandRunner] = None, ssh_binary: str = "ssh") -> None:
        self.peer = peer
        self.runner = runner or CommandRunner()
        self.ssh_binary = ssh_binary

    def read(self, max_bytes: int) -> Optional[bytes]:
        result = self.runner.run_bounded(remote_image_command(self.peer, "read", self.ssh_binary), max_bytes, timeout=10)
        return result.stdout if result.returncode == 0 and result.stdout else None

    def write(self, data: bytes, max_bytes: int) -> bool:
        if len(data) > max_bytes:
            return False
        result = self.runner.run_bounded(remote_image_command(self.peer, "write", self.ssh_binary), max_bytes, data=data, timeout=10)
        return result.returncode == 0


class ImageClipboardSynchronizer:
    def __init__(self, peer_id: str, system: str, peer: Dict[str, Any], state_path: Path, max_bytes: int, winner: str, logger: Any) -> None:
        self.peer_id = peer_id
        self.system = system
        self.remote = RemoteImageClipboard(peer)
        self.state_path = state_path
        self.max_bytes = max_bytes
        self.winner = winner
        self.logger = logger

    def _state(self) -> Dict[str, Any]:
        value = read_json(self.state_path).get("peers", {})
        return value.get(self.peer_id, {}) if isinstance(value, dict) and isinstance(value.get(self.peer_id, {}), dict) else {}

    def _save(self, local_hash: str, remote_hash: str) -> None:
        state = read_json(self.state_path)
        state.setdefault("peers", {})[self.peer_id] = {"local_hash": local_hash, "remote_hash": remote_hash}
        write_json(self.state_path, state)

    def sync_once(self) -> str:
        local = read_local(self.system, self.max_bytes)
        remote = self.remote.read(self.max_bytes)
        if local is None or remote is None:
            return "unavailable"
        lh, rh = digest(local), digest(remote)
        previous = self._state()
        pl, pr = previous.get("local_hash"), previous.get("remote_hash")
        if lh == rh:
            self._save(lh, rh)
            return "equal"
        if pl is None and pr is None:
            changed = remote if self.winner == "remote" else local
            ok = write_local(self.system, changed, self.max_bytes) if self.winner == "remote" else self.remote.write(changed, self.max_bytes)
            if ok:
                h = digest(changed); self._save(h, h)
                return "remote-to-local" if self.winner == "remote" else "local-to-remote"
            return "delivery-failed"
        local_changed, remote_changed = lh != pl, rh != pr
        if local_changed and (not remote_changed or self.winner == "local"):
            if self.remote.write(local, self.max_bytes): self._save(lh, lh); return "local-to-remote"
            return "delivery-failed"
        if remote_changed:
            if write_local(self.system, remote, self.max_bytes): self._save(rh, rh); return "remote-to-local"
            return "delivery-failed"
        return "unchanged"
