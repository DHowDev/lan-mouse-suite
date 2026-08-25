from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class CommandResult:
    argv: List[str]
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass(frozen=True)
class NetworkSnapshot:
    address: Optional[str]
    gateway: Optional[str]
    interface: Optional[str]
    ssid: Optional[str] = None
    gateway_mac: Optional[str] = None


@dataclass(frozen=True)
class TrustedNetwork:
    profile_id: str
    name: str
    cidr: str
    address: str
    gateway: str
    interface: str
    ssid: Optional[str] = None
    gateway_mac: Optional[str] = None


@dataclass(frozen=True)
class ResolvedPeer:
    peer_id: str
    name: str
    address: str
    port: int
    position: str
