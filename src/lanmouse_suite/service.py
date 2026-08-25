from __future__ import annotations

import signal
import time
from typing import Any, Dict

from .adapters import PlatformAdapter
from .clipboard import ClipboardSynchronizer, RemoteClipboard
from .orchestration import Orchestrator
from .paths import SuitePaths


class SuiteService:
    def __init__(self, config: Dict[str, Any], paths: SuitePaths, adapter: PlatformAdapter, logger: Any) -> None:
        self.config = config
        self.paths = paths
        self.adapter = adapter
        self.logger = logger
        self.orchestrator = Orchestrator(config, paths, adapter, logger)
        self.stopping = False

    def stop(self, *_args: Any) -> None:
        self.stopping = True

    def once(self) -> Dict[str, Any]:
        guard = self.orchestrator.guard_once()
        return {"guard": guard, "clipboard": self.clipboard_once()}

    def clipboard_once(self) -> Dict[str, str]:
        clipboard_results: Dict[str, str] = {}
        clipboard = self.config.get("clipboard", {})
        graphical_ready = getattr(self.adapter, "graphical_environment_ready", lambda: True)
        if not graphical_ready():
            return {"_local": "graphical-environment-unavailable"}
        status = self.orchestrator.status(probe=False, include_remote=False)
        if clipboard.get("enabled", False) and status["process"].get("running"):
            active = {row["id"] for row in status["devices"] if row["on"]}
            for peer in self.config.get("peers", []):
                if peer["id"] not in active or not peer.get("ssh", {}).get("target"):
                    continue
                sync = ClipboardSynchronizer(
                    peer["id"],
                    self.adapter,
                    RemoteClipboard(peer),
                    self.paths.clipboard_state,
                    int(clipboard.get("max_bytes", 200000)),
                    clipboard.get("conflict_winner", "local"),
                    self.logger,
                )
                clipboard_results[peer["id"]] = sync.sync_once()
        return clipboard_results

    def run(self) -> None:
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            value = getattr(signal, name, None)
            if value is not None:
                signal.signal(value, self.stop)
        guard_interval = float(self.config.get("guard", {}).get("interval_seconds", 10))
        clipboard = self.config.get("clipboard", {})
        clipboard_enabled = bool(clipboard.get("enabled", False))
        clipboard_interval = float(clipboard.get("poll_seconds", 0.8))
        clipboard_backoff = float(clipboard.get("backoff_seconds", 2.0))
        next_guard = 0.0
        next_clipboard = 0.0
        while not self.stopping:
            now = time.monotonic()
            try:
                if now >= next_guard:
                    next_guard = now + guard_interval
                    self.orchestrator.guard_once()
                if clipboard_enabled and now >= next_clipboard:
                    outcomes = self.clipboard_once()
                    failed = any(value in {"unavailable", "delivery-failed", "graphical-environment-unavailable"} for value in outcomes.values())
                    next_clipboard = now + (clipboard_backoff if failed else clipboard_interval)
            except Exception as exc:
                self.logger.exception("service iteration failed: %s", exc)
                if clipboard_enabled:
                    next_clipboard = time.monotonic() + clipboard_backoff
            deadlines = [next_guard]
            if clipboard_enabled:
                deadlines.append(next_clipboard)
            deadline = min(deadlines)
            while not self.stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
