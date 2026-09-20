from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import get_adapter
from .clipboard import ClipboardSynchronizer, RemoteClipboard
from .config import ConfigError, default_config, import_existing_config, load_config, save_config
from .doctor import doctor_report
from .logging_utils import configure_logging
from .orchestration import OrchestrationError, Orchestrator
from .paths import SuitePaths, native_paths
from .screenshots import ScreenshotError, pull_screenshot, read_export
from .service import SuiteService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lanmouse-suite")
    parser.add_argument("--config", type=Path, help="override platform-native config.json")
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="trusted LAN, peer, and process status")
    status.add_argument("--json", action="store_true")
    on = commands.add_parser("on", help="clear manual OFF and start for a peer")
    on.add_argument("peer", nargs="?")
    commands.add_parser("off", help="persist manual OFF and stop only the tracked process")
    toggle = commands.add_parser("toggle", help="toggle one peer")
    toggle.add_argument("peer")
    commands.add_parser("all-off", help="persist manual OFF and stop the suite process")
    guard = commands.add_parser("guard", help="run one trusted-LAN guard pass")
    guard.add_argument("--json", action="store_true")

    endpoint = commands.add_parser("endpoint", help="restricted SSH remote-control endpoint")
    endpoint.add_argument("action", choices=("status", "on", "off"))
    endpoint.add_argument("peer")

    doctor = commands.add_parser("doctor", help="emit redacted staged-release diagnostics")
    doctor.add_argument("--json", action="store_true", help="emit JSON (the default and only output format)")

    service = commands.add_parser("service", help="run orchestration and clipboard worker")
    service.add_argument("action", choices=("run", "once"))

    clipboard = commands.add_parser("clipboard", help="read, write, or synchronize UTF-8 text")
    clipboard_sub = clipboard.add_subparsers(dest="clipboard_command", required=True)
    clipboard_sub.add_parser("read")
    clipboard_sub.add_parser("write")
    sync = clipboard_sub.add_parser("sync")
    sync.add_argument("peer")
    sync.add_argument("--once", action="store_true")

    screenshot = commands.add_parser("screenshot", help="safe optional screenshot path handoff")
    screenshot_sub = screenshot.add_subparsers(dest="screenshot_command", required=True)
    export = screenshot_sub.add_parser("export")
    export.add_argument("--path")
    export.add_argument("--request-stdin", action="store_true")
    pull = screenshot_sub.add_parser("pull")
    pull.add_argument("peer")
    pull.add_argument("remote_path")
    pull.add_argument("--copy-path", action="store_true")

    config = commands.add_parser("config", help="initialize, validate, or migrate config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    init = config_sub.add_parser("init")
    init.add_argument("--force", action="store_true")
    config_sub.add_parser("validate")
    show = config_sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    migrate = config_sub.add_parser("import-lan-mouse")
    migrate.add_argument("source", type=Path)

    commands.add_parser("paths", help="print native suite paths as JSON")
    commands.add_parser("gui", help="open the portable Tk control window")
    return parser


def _config_path(args: argparse.Namespace, paths: SuitePaths) -> Path:
    return args.config or paths.config_file


def _peer(config: Dict[str, Any], peer_id: str) -> Dict[str, Any]:
    for peer in config.get("peers", []):
        if peer["id"] == peer_id:
            return peer
    raise ConfigError("unknown peer: " + peer_id)


def _print_status(status: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, sort_keys=True))
        return
    print("Network: " + status["network"])
    print("Manual OFF: " + ("yes" if status["manual_off"] else "no"))
    print("Upstream: " + ("running" if status["process"]["running"] else "stopped"))
    for row in status["devices"]:
        print("- %s: %s" % (row["name"], row["detail"]))


def _clipboard(args: argparse.Namespace, config: Dict[str, Any], paths: SuitePaths, adapter: Any, logger: Any) -> int:
    settings = config.get("clipboard", {})
    max_bytes = int(settings.get("max_bytes", 200000))
    action = args.clipboard_command
    if action in {"read", "write"} and not settings.get("endpoint_enabled", False):
        raise ConfigError("clipboard endpoint is disabled")
    if action == "read":
        data = adapter.read_clipboard(max_bytes)
        if data is None:
            return 1
        sys.stdout.buffer.write(data)
        return 0
    if action == "write":
        data = sys.stdin.buffer.read(max_bytes + 1)
        if len(data) > max_bytes:
            print("clipboard payload exceeds configured limit", file=sys.stderr)
            return 2
        return 0 if adapter.write_clipboard(data, max_bytes) else 1
    if not settings.get("enabled", False):
        raise ConfigError("clipboard synchronization is disabled")
    peer = _peer(config, args.peer)
    sync = ClipboardSynchronizer(
        peer["id"], adapter, RemoteClipboard(peer), paths.clipboard_state, max_bytes, settings.get("conflict_winner", "local"), logger
    )
    if args.once:
        print(sync.sync_once())
        return 0
    poll = float(settings.get("poll_seconds", 0.8))
    backoff = float(settings.get("backoff_seconds", 2.0))
    while True:
        outcome = sync.sync_once()
        time.sleep(backoff if outcome in {"unavailable", "delivery-failed"} else poll)


def _screenshot(args: argparse.Namespace, config: Dict[str, Any], adapter: Any) -> int:
    settings = config.get("screenshots", {})
    if not settings.get("enabled", False):
        raise ScreenshotError("screenshots are disabled")
    max_bytes = int(settings.get("max_bytes", 20000000))
    if args.screenshot_command == "export":
        requested = args.path
        if args.request_stdin:
            request = json.loads(sys.stdin.buffer.read(65536).decode("utf-8"))
            requested = request.get("path") if isinstance(request, dict) else None
        if not isinstance(requested, str) or not requested:
            raise ScreenshotError("a screenshot path is required")
        data = read_export(Path(settings["export_root"]), requested, max_bytes)
        sys.stdout.buffer.write(data)
        return 0
    peer = _peer(config, args.peer)
    target = pull_screenshot(
        peer, args.remote_path, Path(settings["inbox_root"]), max_bytes, adapter, copy_path=args.copy_path
    )
    print(str(target))
    return 0


def _endpoint_state(orchestrator: Orchestrator, peer_id: str) -> Dict[str, Any]:
    status = orchestrator.status(probe=False, include_remote=False)
    row = next((item for item in status["devices"] if item["id"] == peer_id), None)
    return {"on": bool(row and row["on"]), "peer": peer_id}


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    paths = native_paths()
    config_path = _config_path(args, paths)
    if args.command == "paths":
        print(json.dumps({"config": str(paths.config_file), "state": str(paths.state_dir), "logs": str(paths.log_dir)}, sort_keys=True))
        return 0
    if args.command == "config" and args.config_command == "init":
        if config_path.exists() and not args.force:
            print("config already exists: %s" % config_path, file=sys.stderr)
            return 2
        save_config(default_config(), config_path, paths)
        print(str(config_path))
        return 0
    try:
        config = load_config(config_path, paths)
        logger = configure_logging(paths.log_file, args.verbose)
        utf8_locale = str(config.get("clipboard", {}).get("utf8_locale", "en_US.UTF-8"))
        adapter = get_adapter(utf8_locale=utf8_locale)
        if args.command == "config":
            if args.config_command == "validate":
                print("valid: " + str(config_path))
                return 0
            if args.config_command == "show":
                print(json.dumps(config, sort_keys=True, indent=2) if args.json else str(config_path))
                return 0
            source = args.source.expanduser().resolve()
            config, count = import_existing_config(config, source)
            save_config(config, config_path, paths)
            print(json.dumps({"imported_fingerprints": count, "source_preserved": str(source), "managed_config": str(source.with_name("config.lanmouse-suite.toml")), "cert_path_selected": bool(config.get("upstream", {}).get("cert_path"))}))
            return 0
        if args.command == "doctor":
            print(json.dumps(doctor_report(config, config_path, adapter), sort_keys=True))
            return 0
        if args.command == "clipboard":
            return _clipboard(args, config, paths, adapter, logger)
        if args.command == "screenshot":
            return _screenshot(args, config, adapter)
        if args.command == "gui":
            from .gui import ControlWindow
            import tkinter as tk

            root = tk.Tk()
            ControlWindow(root, config_path)
            root.mainloop()
            return 0
        orchestrator = Orchestrator(config, paths, adapter, logger)
        if args.command == "endpoint":
            if not config.get("remote_control", {}).get("endpoint_enabled", False):
                raise ConfigError("remote-control endpoint is disabled")
            _peer(config, args.peer)
            if args.action == "on":
                orchestrator.manual_on(args.peer, coordinate_remote=False)
            elif args.action == "off":
                orchestrator.manual_off(coordinate_remote=False)
            print(json.dumps(_endpoint_state(orchestrator, args.peer), sort_keys=True))
            return 0
        if args.command == "status":
            _print_status(orchestrator.status(), args.json)
            return 0
        if args.command == "on":
            _print_status(orchestrator.manual_on(args.peer), True)
            return 0
        if args.command in {"off", "all-off"}:
            _print_status(orchestrator.manual_off(), True)
            return 0
        if args.command == "toggle":
            status = orchestrator.status()
            row = next((item for item in status["devices"] if item["id"] == args.peer), None)
            output = orchestrator.manual_off() if row and row["on"] else orchestrator.manual_on(args.peer)
            _print_status(output, True)
            return 0
        if args.command == "guard":
            output = orchestrator.guard_once()
            print(json.dumps(output, sort_keys=True) if args.json else output["action"])
            return 0
        service = SuiteService(config, paths, adapter, logger)
        if args.action == "once":
            print(json.dumps(service.once(), sort_keys=True))
            return 0
        service.run()
        return 0
    except (ConfigError, OrchestrationError, ScreenshotError, ValueError, OSError, json.JSONDecodeError) as exc:
        print("lanmouse-suite: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
