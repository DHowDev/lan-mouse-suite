from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import CommandRunner, PlatformAdapter
from .clipboard import ssh_base_command


class ScreenshotError(ValueError):
    pass


def validated_path(root: Path, candidate: Path, must_exist: bool = True) -> Path:
    resolved_root = root.expanduser().resolve(strict=must_exist)
    resolved_candidate = candidate.expanduser()
    if not resolved_candidate.is_absolute():
        resolved_candidate = resolved_root / resolved_candidate
    resolved_candidate = resolved_candidate.resolve(strict=must_exist)
    try:
        common = os.path.commonpath([str(resolved_root), str(resolved_candidate)])
    except ValueError as exc:
        raise ScreenshotError("path is outside configured root") from exc
    if common != str(resolved_root) or resolved_candidate == resolved_root:
        raise ScreenshotError("path is outside configured root")
    return resolved_candidate


def safe_filename(name: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise ScreenshotError("invalid filename")
    if Path(name).name != name or "\x00" in name or "/" in name or "\\" in name:
        raise ScreenshotError("filename must not contain a path")
    return name


def remote_basename(path: str) -> str:
    return safe_filename(path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])


def _relative_export(root: Path, requested: str) -> tuple:
    if not isinstance(requested, str) or not requested or "\x00" in requested:
        raise ScreenshotError("invalid screenshot path")
    root = root.expanduser().resolve(strict=True)
    candidate = Path(requested).expanduser()
    if candidate.is_absolute():
        normalized = Path(os.path.abspath(str(candidate)))
        try:
            relative = normalized.relative_to(root)
        except ValueError as exc:
            raise ScreenshotError("path is outside configured root") from exc
    else:
        relative = candidate
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ScreenshotError("path is outside configured root")
    return root, parts


def _read_open_file(handle: Any, max_bytes: int) -> bytes:
    before = os.fstat(handle.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise ScreenshotError("requested screenshot is not a regular file")
    if before.st_size <= 0 or before.st_size > max_bytes:
        raise ScreenshotError("screenshot size is outside configured limit")
    data = handle.read(max_bytes + 1)
    after = os.fstat(handle.fileno())
    if len(data) != before.st_size or len(data) > max_bytes or after.st_size != before.st_size:
        raise ScreenshotError("screenshot changed while reading")
    return data


def read_export(root: Path, requested: str, max_bytes: int) -> bytes:
    if os.name == "nt":
        # Windows junction/reparse-point traversal needs native handle-based
        # validation for every component. Fail closed rather than exposing a
        # pathname check/open TOCTOU race. Clipboard sync remains supported.
        raise ScreenshotError("screenshot export is not supported on Windows")
    resolved_root, parts = _relative_export(root, requested)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    descriptor = os.open(str(resolved_root), directory_flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=descriptor)
        try:
            with os.fdopen(file_descriptor, "rb", closefd=False) as handle:
                return _read_open_file(handle, max_bytes)
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise ScreenshotError("requested screenshot is unavailable or unsafe") from exc
    finally:
        os.close(descriptor)


def write_inbox(root: Path, name: str, data: bytes, max_bytes: int) -> Path:
    if not data or len(data) > max_bytes:
        raise ScreenshotError("screenshot payload is outside configured limit")
    filename = safe_filename(name)
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = validated_path(root, root / filename, must_exist=False)
    fd, temporary = tempfile.mkstemp(prefix=".incoming-", dir=str(root))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def remote_screenshot_command(peer: Dict[str, Any], ssh_binary: str = "ssh") -> List[str]:
    remote_cli = peer.get("ssh", {}).get("remote_cli", "lanmouse-suite")
    return ssh_base_command(peer, ssh_binary) + [remote_cli, "screenshot", "export", "--request-stdin"]


def pull_screenshot(
    peer: Dict[str, Any],
    remote_path: str,
    inbox_root: Path,
    max_bytes: int,
    adapter: PlatformAdapter,
    runner: Optional[CommandRunner] = None,
    copy_path: bool = False,
) -> Path:
    request = json.dumps({"path": remote_path}).encode("utf-8")
    result = (runner or CommandRunner()).run_bounded(remote_screenshot_command(peer), max_bytes, data=request, timeout=20)
    if result.returncode == 125:
        raise ScreenshotError("remote screenshot exceeded configured limit")
    if result.returncode != 0:
        raise ScreenshotError("remote screenshot export failed")
    target = write_inbox(inbox_root, remote_basename(remote_path), result.stdout, max_bytes)
    if copy_path and not adapter.write_clipboard(str(target).encode("utf-8"), max_bytes):
        raise ScreenshotError("screenshot received but clipboard path handoff failed")
    return target
