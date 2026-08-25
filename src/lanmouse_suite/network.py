from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict, List, Optional, Tuple

from .adapters import PlatformAdapter, normalize_mac
from .models import NetworkSnapshot, ResolvedPeer, TrustedNetwork


def match_trusted_network(snapshot: NetworkSnapshot, profiles: List[Dict[str, Any]]) -> Optional[TrustedNetwork]:
    if not snapshot.address or not snapshot.gateway or not snapshot.interface:
        return None
    try:
        address = ipaddress.ip_address(snapshot.address)
        gateway = ipaddress.ip_address(snapshot.gateway)
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address) or not isinstance(gateway, ipaddress.IPv4Address):
        return None
    observed_mac = normalize_mac(snapshot.gateway_mac)
    for profile in profiles:
        network = ipaddress.ip_network(profile["cidr"], strict=True)
        expected_interface = profile.get("interface")
        if expected_interface and snapshot.interface != expected_interface:
            continue
        expected_ssid = profile.get("ssid")
        if expected_ssid is not None and snapshot.ssid != expected_ssid:
            continue
        expected_mac = normalize_mac(profile.get("gateway_mac"))
        if expected_mac is not None and observed_mac != expected_mac:
            continue
        if address in network and gateway in network and str(gateway) == profile["gateway"]:
            return TrustedNetwork(
                profile["id"],
                profile.get("name", profile["id"]),
                str(network),
                str(address),
                str(gateway),
                snapshot.interface,
                snapshot.ssid,
                observed_mac,
            )
    return None


def profile_by_id(config: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    for profile in config.get("profiles", []):
        if profile["id"] == profile_id:
            return profile
    raise KeyError(profile_id)


def peers_by_id(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {peer["id"]: peer for peer in config.get("peers", [])}


def resolve_peer(peer: Dict[str, Any], trusted: TrustedNetwork, profile: Dict[str, Any], adapter: PlatformAdapter) -> Optional[ResolvedPeer]:
    network = ipaddress.ip_network(trusted.cidr, strict=True)
    candidates: List[str] = []
    mdns = peer.get("mdns")
    if mdns:
        candidates.extend(adapter.resolve_ipv4(mdns))
    candidates.extend(peer.get("addresses", []))
    if profile.get("allow_tailscale", False):
        candidates.extend(peer.get("tailscale_addresses", []))
    for value in candidates:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address) or address not in network:
            continue
        return ResolvedPeer(
            peer["id"],
            peer.get("name", peer["id"]),
            str(address),
            int(peer.get("port", 4242)),
            peer.get("position", "right"),
        )
    return None


def probe_peer(peer: ResolvedPeer, timeout: float = 1.5, probe_port: int = 22) -> bool:
    try:
        connection = socket.create_connection((peer.address, probe_port), timeout=timeout)
    except OSError:
        return False
    connection.close()
    return True


def discover_profile_peers(
    config: Dict[str, Any], trusted: TrustedNetwork, adapter: PlatformAdapter, probe: bool = True
) -> List[Tuple[ResolvedPeer, bool]]:
    profile = profile_by_id(config, trusted.profile_id)
    index = peers_by_id(config)
    rows: List[Tuple[ResolvedPeer, bool]] = []
    for peer_id in profile.get("peers", []):
        source = index[peer_id]
        resolved = resolve_peer(source, trusted, profile, adapter)
        if resolved is not None:
            reachable = probe_peer(resolved, probe_port=int(source.get("probe_port", 22))) if probe else True
            rows.append((resolved, reachable))
    return rows
