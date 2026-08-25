from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .adapters import CommandRunner
from .clipboard import ssh_base_command


class RemoteControlError(RuntimeError):
    pass


def remote_endpoint_command(peer: Dict[str, Any], action: str, remote_peer_id: str, ssh_binary: str = "ssh") -> List[str]:
    if action not in {"status", "on", "off"}:
        raise ValueError("invalid remote endpoint action")
    if not isinstance(remote_peer_id, str) or not remote_peer_id:
        raise ValueError("remote peer id is required")
    remote_cli = peer.get("ssh", {}).get("remote_cli", "lanmouse-suite")
    return ssh_base_command(peer, ssh_binary) + [remote_cli, "endpoint", action, remote_peer_id]


class RemoteEndpoint:
    def __init__(self, peer: Dict[str, Any], runner: Optional[CommandRunner] = None, ssh_binary: str = "ssh") -> None:
        self.peer = peer
        self.runner = runner or CommandRunner()
        self.ssh_binary = ssh_binary
        remote = peer.get("remote_control", {})
        self.remote_peer_id = remote.get("remote_peer_id")
        if not remote.get("enabled", False) or not self.remote_peer_id:
            raise RemoteControlError("remote control is not enabled for peer")

    def _invoke(self, action: str) -> Dict[str, Any]:
        result = self.runner.run_bounded(
            remote_endpoint_command(self.peer, action, self.remote_peer_id, self.ssh_binary),
            65536,
            timeout=12,
        )
        if result.returncode != 0:
            raise RemoteControlError("remote endpoint %s failed" % action)
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RemoteControlError("remote endpoint returned invalid status") from exc
        if not isinstance(value, dict) or not isinstance(value.get("on"), bool):
            raise RemoteControlError("remote endpoint status is not authoritative")
        return value

    def status(self) -> bool:
        return bool(self._invoke("status")["on"])

    def set_on(self) -> bool:
        self._invoke("on")
        return self.status()

    def set_off(self) -> bool:
        self._invoke("off")
        return self.status()
