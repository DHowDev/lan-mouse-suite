from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from .adapters import CommandRunner, PlatformAdapter
from .remote import RemoteControlError, RemoteEndpoint


def _result(status: str, **values: Any) -> Dict[str, Any]:
    output = {"status": status}
    output.update(values)
    return output


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def doctor_report(config: Dict[str, Any], config_path: Path, adapter: PlatformAdapter) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    try:
        config_hash = _hash_file(config_path.resolve(strict=True))
        checks["config"] = _result("ok", sha256=config_hash)
    except OSError:
        checks["config"] = _result("blocked", reason="config file is unreadable")

    configured = str(config.get("upstream", {}).get("binary", ""))
    found = configured if Path(configured).is_absolute() else shutil.which(configured)
    if not found:
        checks["executable"] = _result("blocked", reason="selected upstream executable was not found")
    else:
        try:
            executable = Path(found).expanduser().resolve(strict=True)
            if not executable.is_file() or not os.access(str(executable), os.X_OK):
                raise OSError("not executable")
            version = CommandRunner().run_bounded([str(executable), "--version"], 16384, timeout=5)
            if version.returncode == 0:
                checks["executable"] = _result("ok", path=str(executable), version_probe="passed")
            else:
                checks["executable"] = _result("blocked", path=str(executable), reason="--version probe failed")
        except OSError:
            checks["executable"] = _result("blocked", reason="selected upstream path is not executable")

    cert_value = config.get("upstream", {}).get("cert_path")
    if not cert_value:
        checks["certificate"] = _result("unknown", reason="no explicit cert_path selected")
    else:
        try:
            cert = Path(cert_value).expanduser().resolve(strict=True)
            if not cert.is_file():
                raise OSError("not regular")
            checks["certificate"] = _result("ok", path=str(cert), sha256=_hash_file(cert), fingerprint="not-computed")
        except OSError:
            checks["certificate"] = _result("blocked", reason="selected certificate is unreadable")

    ready = getattr(adapter, "graphical_environment_ready", lambda: True)()
    checks["graphical_environment"] = _result("ok" if ready else "blocked")

    ssh_checks: Dict[str, Any] = {}
    for peer in config.get("peers", []):
        if not peer.get("remote_control", {}).get("enabled", False):
            continue
        try:
            on = RemoteEndpoint(peer).status()
            ssh_checks[peer["id"]] = _result("ok", remote_on=on)
        except (RemoteControlError, OSError, ValueError):
            ssh_checks[peer["id"]] = _result("unknown", reason="authenticated endpoint status unavailable")
    checks["ssh_endpoints"] = ssh_checks or _result("unknown", reason="no remote-control peers configured")

    screenshots = config.get("screenshots", {})
    root_checks: Dict[str, Any] = {}
    for key in ("inbox_root", "export_root"):
        value = screenshots.get(key)
        if not screenshots.get("enabled", False):
            root_checks[key] = _result("unknown", reason="screenshots disabled")
        elif not value:
            root_checks[key] = _result("blocked", reason="root is not configured")
        else:
            try:
                root = Path(value).expanduser().resolve(strict=True)
                root_checks[key] = _result("ok" if root.is_dir() else "blocked")
            except OSError:
                root_checks[key] = _result("blocked", reason="configured root is unavailable")
    checks["screenshot_roots"] = root_checks
    blocked = []
    for key in ("config", "executable", "graphical_environment"):
        if checks[key].get("status") == "blocked":
            blocked.append(key)
    return {"state": "blocked" if blocked else "ready", "blocked": blocked, "checks": checks}
