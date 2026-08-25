from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import CommandRunner, PlatformAdapter
from .state import read_json, write_json


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ssh_base_command(peer: Dict[str, Any], ssh_binary: str = "ssh") -> List[str]:
    ssh = peer.get("ssh", {})
    target = ssh.get("target")
    if not target:
        raise ValueError("peer has no ssh.target")
    command = [
        ssh_binary,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=4",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=1",
    ]
    if ssh.get("identity_file"):
        command.extend(["-i", str(Path(ssh["identity_file"]).expanduser())])
    command.append(target)
    return command


def remote_clipboard_command(peer: Dict[str, Any], action: str, ssh_binary: str = "ssh") -> List[str]:
    if action not in {"read", "write"}:
        raise ValueError("invalid clipboard action")
    remote_cli = peer.get("ssh", {}).get("remote_cli", "lanmouse-suite")
    return ssh_base_command(peer, ssh_binary) + [remote_cli, "clipboard", action]


class RemoteClipboard:
    def __init__(self, peer: Dict[str, Any], runner: Optional[CommandRunner] = None, ssh_binary: str = "ssh") -> None:
        self.peer = peer
        self.runner = runner or CommandRunner()
        self.ssh_binary = ssh_binary

    def read(self, max_bytes: int) -> Optional[bytes]:
        result = self.runner.run_bounded(
            remote_clipboard_command(self.peer, "read", self.ssh_binary), max_bytes, timeout=8
        )
        if result.returncode != 0:
            return None
        try:
            result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        return result.stdout

    def write(self, data: bytes, max_bytes: int) -> bool:
        if len(data) > max_bytes:
            return False
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
        result = self.runner.run_bounded(
            remote_clipboard_command(self.peer, "write", self.ssh_binary), 65536, data=data, timeout=8
        )
        return result.returncode == 0


class ClipboardSynchronizer:
    def __init__(
        self,
        peer_id: str,
        local: PlatformAdapter,
        remote: Any,
        state_path: Path,
        max_bytes: int,
        conflict_winner: str,
        logger: Any,
    ) -> None:
        self.peer_id = peer_id
        self.local = local
        self.remote = remote
        self.state_path = state_path
        self.max_bytes = max_bytes
        self.conflict_winner = conflict_winner
        self.logger = logger

    def _peer_state(self) -> Dict[str, Any]:
        state = read_json(self.state_path)
        peers = state.get("peers", {})
        value = peers.get(self.peer_id, {}) if isinstance(peers, dict) else {}
        return value if isinstance(value, dict) else {}

    def _save(self, local_hash: str, remote_hash: str) -> None:
        state = read_json(self.state_path)
        peers = state.setdefault("peers", {})
        peers[self.peer_id] = {"local_hash": local_hash, "remote_hash": remote_hash, "updated_at": int(time.time())}
        write_json(self.state_path, state)

    def sync_once(self) -> str:
        local_data = self.local.read_clipboard(self.max_bytes)
        remote_data = self.remote.read(self.max_bytes)
        if local_data is None or remote_data is None:
            return "unavailable"
        local_hash = digest(local_data)
        remote_hash = digest(remote_data)
        prior = self._peer_state()
        prior_local = prior.get("local_hash")
        prior_remote = prior.get("remote_hash")
        if local_hash == remote_hash:
            self._save(local_hash, remote_hash)
            return "equal"
        if prior_local is None and prior_remote is None:
            if self.conflict_winner == "remote":
                if self.local.write_clipboard(remote_data, self.max_bytes):
                    self._save(remote_hash, remote_hash)
                    self.logger.info("clipboard peer=%s direction=remote-to-local bytes=%d", self.peer_id, len(remote_data))
                    return "remote-to-local"
            elif self.remote.write(local_data, self.max_bytes):
                self._save(local_hash, local_hash)
                self.logger.info("clipboard peer=%s direction=local-to-remote bytes=%d", self.peer_id, len(local_data))
                return "local-to-remote"
            return "delivery-failed"
        local_changed = local_hash != prior_local
        remote_changed = remote_hash != prior_remote
        if local_changed and remote_changed:
            if self.conflict_winner == "remote":
                if self.local.write_clipboard(remote_data, self.max_bytes):
                    self._save(remote_hash, remote_hash)
                    self.logger.info("clipboard peer=%s conflict=remote-won bytes=%d", self.peer_id, len(remote_data))
                    return "remote-won"
            elif self.remote.write(local_data, self.max_bytes):
                self._save(local_hash, local_hash)
                self.logger.info("clipboard peer=%s conflict=local-won bytes=%d", self.peer_id, len(local_data))
                return "local-won"
            return "delivery-failed"
        if local_changed:
            if self.remote.write(local_data, self.max_bytes):
                self._save(local_hash, local_hash)
                self.logger.info("clipboard peer=%s direction=local-to-remote bytes=%d", self.peer_id, len(local_data))
                return "local-to-remote"
            return "delivery-failed"
        if remote_changed:
            if self.local.write_clipboard(remote_data, self.max_bytes):
                self._save(remote_hash, remote_hash)
                self.logger.info("clipboard peer=%s direction=remote-to-local bytes=%d", self.peer_id, len(remote_data))
                return "remote-to-local"
            return "delivery-failed"
        return "unchanged"
