from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapters import normalize_mac
from .paths import SuitePaths, native_paths
from .state import write_json

SSH_TARGET = re.compile(r"^(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.-]+$")
REMOTE_COMMAND = re.compile(r"^[A-Za-z0-9_./\\:-]+$")
FINGERPRINT = re.compile(r"^(?:[0-9a-fA-F]{2}:){31}[0-9a-fA-F]{2}$")
POSITIONS = {"left", "right", "top", "bottom"}


class ConfigError(ValueError):
    pass


def default_config() -> Dict[str, Any]:
    return {
        "version": 1,
        "guard": {"failure_limit": 3, "interval_seconds": 10, "graphical_ready_seconds": 3},
        "upstream": {
            "binary": "lan-mouse",
            "extra_args": ["daemon"],
            "port": 4242,
            "release_chord": ["KeyLeftCtrl", "KeyLeftShift", "KeyLeftAlt", "KeyLeftMeta"],
            "authorized_fingerprints": {},
        },
        "profiles": [],
        "peers": [],
        "remote_control": {"endpoint_enabled": False},
        "clipboard": {
            "enabled": False,
            "endpoint_enabled": False,
            "poll_seconds": 0.8,
            "backoff_seconds": 2.0,
            "max_bytes": 200000,
            "conflict_winner": "local",
            "utf8_locale": "en_US.UTF-8",
        },
        "screenshots": {"enabled": False, "inbox_root": "", "export_root": "", "max_bytes": 20000000},
    }


def _require_dict(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(label + " must be an object")
    return value


def _require_list(value: Any, label: str) -> List[Any]:
    if not isinstance(value, list):
        raise ConfigError(label + " must be an array")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(label + " must be boolean")
    return value


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
        raise ConfigError("%s must be between %s and %s" % (label, minimum, maximum))
    return float(value)


def _clean_arg(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ConfigError(label + " must be a non-empty single-line string")
    return value


def validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = _require_dict(raw, "config")
    if config.get("version") != 1:
        raise ConfigError("version must be 1")
    guard = _require_dict(config.get("guard", {}), "guard")
    limit = guard.get("failure_limit", 3)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ConfigError("guard.failure_limit must be between 1 and 20")
    _number(guard.get("interval_seconds", 10), "guard.interval_seconds", 1, 3600)
    _number(guard.get("graphical_ready_seconds", 3), "guard.graphical_ready_seconds", 0, 30)

    upstream = _require_dict(config.get("upstream", {}), "upstream")
    upstream["binary"] = _clean_arg(upstream.get("binary", "lan-mouse"), "upstream.binary")
    args = _require_list(upstream.get("extra_args", ["daemon"]), "upstream.extra_args")
    upstream["extra_args"] = [_clean_arg(item, "upstream.extra_args item") for item in args]
    port = upstream.get("port", 4242)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("upstream.port must be a valid TCP/UDP port")
    chord = _require_list(upstream.get("release_chord", []), "upstream.release_chord")
    if not chord or any(not isinstance(key, str) or not key for key in chord):
        raise ConfigError("upstream.release_chord must contain key names")
    fingerprints = _require_dict(upstream.get("authorized_fingerprints", {}), "upstream.authorized_fingerprints")
    for fingerprint, label in fingerprints.items():
        if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
            raise ConfigError("authorized fingerprint must be 32 colon-separated hex bytes")
        _clean_arg(label, "authorized fingerprint label")
    for key in ("existing_config", "cert_path"):
        value = upstream.get(key)
        if value is not None:
            upstream[key] = _clean_arg(value, "upstream." + key)

    peer_ids = set()
    peers = _require_list(config.get("peers", []), "peers")
    for item in peers:
        peer = _require_dict(item, "peer")
        peer_id = _clean_arg(peer.get("id"), "peer.id")
        if peer_id in peer_ids:
            raise ConfigError("duplicate peer id: " + peer_id)
        peer_ids.add(peer_id)
        _clean_arg(peer.get("name", peer_id), "peer.name")
        if peer.get("position", "right") not in POSITIONS:
            raise ConfigError("peer.position must be left, right, top, or bottom")
        addresses = _require_list(peer.get("addresses", []), "peer.addresses")
        tailscale = _require_list(peer.get("tailscale_addresses", []), "peer.tailscale_addresses")
        for address in addresses + tailscale:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ConfigError("invalid peer IPv4 address: " + str(address)) from exc
            if not isinstance(parsed, ipaddress.IPv4Address):
                raise ConfigError("peer addresses must be IPv4")
        mdns = peer.get("mdns")
        if mdns is not None:
            _clean_arg(mdns, "peer.mdns")
        ssh = _require_dict(peer.get("ssh", {}), "peer.ssh")
        target = ssh.get("target")
        if target is not None and (not isinstance(target, str) or target.startswith("-") or not SSH_TARGET.fullmatch(target)):
            raise ConfigError("peer.ssh.target contains unsafe characters")
        remote_cli = ssh.get("remote_cli", "lanmouse-suite")
        if not isinstance(remote_cli, str) or not REMOTE_COMMAND.fullmatch(remote_cli):
            raise ConfigError("peer.ssh.remote_cli contains unsafe characters")
        identity = ssh.get("identity_file")
        if identity is not None:
            _clean_arg(identity, "peer.ssh.identity_file")
        for key, default in (("port", port), ("probe_port", 22)):
            value = peer.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ConfigError("peer.%s must be valid" % key)
        remote = _require_dict(peer.get("remote_control", {}), "peer.remote_control")
        enabled = _require_bool(remote.get("enabled", False), "peer.remote_control.enabled")
        remote_peer_id = remote.get("remote_peer_id")
        if enabled:
            _clean_arg(remote_peer_id, "peer.remote_control.remote_peer_id")
            if not target:
                raise ConfigError("remote-controlled peer requires peer.ssh.target")
        elif remote_peer_id is not None:
            _clean_arg(remote_peer_id, "peer.remote_control.remote_peer_id")

    profiles = _require_list(config.get("profiles", []), "profiles")
    profile_ids = set()
    for item in profiles:
        profile = _require_dict(item, "profile")
        profile_id = _clean_arg(profile.get("id"), "profile.id")
        if profile_id in profile_ids:
            raise ConfigError("duplicate profile id: " + profile_id)
        profile_ids.add(profile_id)
        try:
            network = ipaddress.ip_network(profile.get("cidr"), strict=True)
            gateway = ipaddress.ip_address(profile.get("gateway"))
        except ValueError as exc:
            raise ConfigError("profile CIDR/gateway is invalid") from exc
        if not isinstance(network, ipaddress.IPv4Network) or not isinstance(gateway, ipaddress.IPv4Address):
            raise ConfigError("profiles must use IPv4")
        if gateway not in network:
            raise ConfigError("profile gateway must be inside its CIDR")
        for key in ("interface", "ssid"):
            if profile.get(key) is not None:
                _clean_arg(profile[key], "profile." + key)
        if profile.get("gateway_mac") is not None:
            normalized = normalize_mac(profile.get("gateway_mac"))
            if normalized is None:
                raise ConfigError("profile.gateway_mac must be a 6-byte MAC address")
            profile["gateway_mac"] = normalized
        for peer_id in _require_list(profile.get("peers", []), "profile.peers"):
            if peer_id not in peer_ids:
                raise ConfigError("profile references unknown peer: " + str(peer_id))
        _require_bool(profile.get("allow_tailscale", False), "profile.allow_tailscale")

    remote_control = _require_dict(config.get("remote_control", {}), "remote_control")
    _require_bool(remote_control.get("endpoint_enabled", False), "remote_control.endpoint_enabled")

    clipboard = _require_dict(config.get("clipboard", {}), "clipboard")
    _require_bool(clipboard.get("enabled", False), "clipboard.enabled")
    _require_bool(clipboard.get("endpoint_enabled", False), "clipboard.endpoint_enabled")
    max_bytes = clipboard.get("max_bytes", 200000)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 5000000:
        raise ConfigError("clipboard.max_bytes must be between 1 and 5000000")
    _number(clipboard.get("poll_seconds", 0.8), "clipboard.poll_seconds", 0.1, 60)
    _number(clipboard.get("backoff_seconds", 2.0), "clipboard.backoff_seconds", 0.1, 300)
    if clipboard.get("conflict_winner", "local") not in {"local", "remote"}:
        raise ConfigError("clipboard.conflict_winner must be local or remote")
    utf8_locale = clipboard.get("utf8_locale", "en_US.UTF-8")
    if not isinstance(utf8_locale, str) or not re.fullmatch(r"[A-Za-z0-9._@-]{1,64}", utf8_locale):
        raise ConfigError("clipboard.utf8_locale contains unsafe characters")
    clipboard["utf8_locale"] = utf8_locale

    screenshots = _require_dict(config.get("screenshots", {}), "screenshots")
    enabled = _require_bool(screenshots.get("enabled", False), "screenshots.enabled")
    shot_max = screenshots.get("max_bytes", 20000000)
    if isinstance(shot_max, bool) or not isinstance(shot_max, int) or not 1 <= shot_max <= 200000000:
        raise ConfigError("screenshots.max_bytes is out of range")
    if enabled:
        for key in ("inbox_root", "export_root"):
            value = screenshots.get(key)
            if not isinstance(value, str) or not value:
                raise ConfigError("screenshots.%s is required when enabled" % key)
    return config


def load_config(path: Optional[Path] = None, paths: Optional[SuitePaths] = None) -> Dict[str, Any]:
    target = path or (paths or native_paths()).config_file
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError("config not found: %s (copy examples/config.example.json)" % target) from exc
    except (OSError, ValueError) as exc:
        raise ConfigError("cannot read config: %s" % exc) from exc
    return validate_config(raw)


def save_config(config: Dict[str, Any], path: Optional[Path] = None, paths: Optional[SuitePaths] = None) -> Path:
    checked = validate_config(config)
    target = path or (paths or native_paths()).config_file
    write_json(target, checked)
    return target


def parse_authorized_fingerprints(text: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    in_section = False
    assignment = re.compile(r'^\s*"([0-9a-fA-F:]+)"\s*=\s*"([^"]+)"\s*(?:#.*)?$')
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped == "[authorized_fingerprints]"
            continue
        if not in_section:
            continue
        match = assignment.match(line)
        if match and FINGERPRINT.fullmatch(match.group(1)):
            found[match.group(1).lower()] = match.group(2)
    return found


def _toml_string(text: str, key: str) -> Optional[str]:
    pattern = re.compile(r'^\s*%s\s*=\s*"((?:[^"\\]|\\.)*)"\s*(?:#.*)?$' % re.escape(key), re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    try:
        return json.loads('"' + match.group(1) + '"')
    except ValueError:
        return None


def _append_option(args: List[str], option: str, value: str) -> None:
    if option in args:
        return
    index = args.index("daemon") if "daemon" in args else len(args)
    args[index:index] = [option, value]


def import_existing_config(config: Dict[str, Any], source: Path) -> Tuple[Dict[str, Any], int]:
    text = source.read_text(encoding="utf-8")
    imported = parse_authorized_fingerprints(text)
    upstream = config.setdefault("upstream", {})
    current = upstream.setdefault("authorized_fingerprints", {})
    current.update(imported)
    upstream["existing_config"] = str(source.resolve())
    if not upstream.get("cert_path"):
        configured_cert = _toml_string(text, "cert_path")
        sibling_cert = source.with_name("lan-mouse.pem")
        if configured_cert:
            candidate = Path(configured_cert).expanduser()
            if not candidate.is_absolute():
                candidate = source.parent / candidate
            upstream["cert_path"] = str(candidate.resolve(strict=False))
        elif sibling_cert.is_file():
            upstream["cert_path"] = str(sibling_cert.resolve())
    args = list(upstream.get("extra_args", ["daemon"]))
    for key, option in (("capture_backend", "--capture-backend"), ("emulation_backend", "--emulation-backend"), ("enter_hook", "--enter-hook")):
        value = _toml_string(text, key)
        if value:
            _append_option(args, option, value)
    upstream["extra_args"] = args
    validate_config(config)
    return config, len(imported)
