from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .adapters import PlatformAdapter
from .models import ResolvedPeer, TrustedNetwork
from .network import discover_profile_peers, match_trusted_network, profile_by_id
from .paths import SuitePaths
from .remote import RemoteControlError, RemoteEndpoint
from .state import InterProcessLock, read_json, write_json
from .toml_config import managed_toml_path, write_managed_toml


class OrchestrationError(RuntimeError):
    pass


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".rollback.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


class LanMouseProcess:
    def __init__(
        self, config: Dict[str, Any], paths: SuitePaths, adapter: PlatformAdapter, lock: Optional[InterProcessLock] = None
    ) -> None:
        self.config = config
        self.paths = paths
        self.adapter = adapter
        self.lock = lock or InterProcessLock(paths.control_lock)

    def _state(self) -> Dict[str, Any]:
        return read_json(self.paths.process_state)

    def _expected(self, state: Dict[str, Any]) -> Dict[str, Any]:
        expected = state.get("identity")
        return expected if isinstance(expected, dict) else {}

    def _status_unlocked(self) -> Dict[str, Any]:
        state = self._state()
        pid = state.get("pid")
        expected = self._expected(state)
        running = isinstance(pid, int) and bool(expected) and self.adapter.process_matches(pid, expected)
        live = self.adapter.process_identity(pid) if isinstance(pid, int) and not running else None
        ambiguous = bool(isinstance(pid, int) and live is not None and not running)
        return {"running": running, "pid": pid if running else None, "tracked_pid": pid, "ambiguous": ambiguous}

    def status(self) -> Dict[str, Any]:
        with self.lock.held():
            return self._status_unlocked()

    def _resolve_binary(self) -> str:
        configured = str(self.config["upstream"]["binary"])
        if Path(configured).is_absolute() or os.sep in configured or (os.altsep and os.altsep in configured):
            candidate = Path(configured).expanduser()
        else:
            found = shutil.which(configured)
            if not found:
                raise OrchestrationError("upstream.binary was not found: " + configured)
            candidate = Path(found)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise OrchestrationError("upstream.binary is unavailable: " + configured) from exc
        if not resolved.is_file() or not os.access(str(resolved), os.X_OK):
            raise OrchestrationError("upstream.binary is not executable: " + str(resolved))
        return str(resolved)

    def _argv(self, toml_path: Path) -> List[str]:
        upstream = self.config["upstream"]
        argv = [self._resolve_binary(), "--config", str(toml_path.resolve(strict=True))]
        cert_path = upstream.get("cert_path")
        if cert_path:
            try:
                cert = Path(cert_path).expanduser().resolve(strict=True)
            except OSError as exc:
                raise OrchestrationError("upstream.cert_path is unavailable") from exc
            if not cert.is_file():
                raise OrchestrationError("upstream.cert_path is not a regular file")
            argv.extend(["--cert-path", str(cert)])
        argv.extend(str(item) for item in upstream.get("extra_args", ["daemon"]))
        return argv

    def _launch(self, argv: List[str], toml_path: Path, config_text: str) -> bool:
        self.paths.log_dir.mkdir(parents=True, exist_ok=True)
        log_handle = open(self.paths.log_dir / "lan-mouse-upstream.log", "ab", buffering=0)
        kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "shell": False,
            "close_fds": True,
            "env": self.adapter.child_environment(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
        except OSError as exc:
            raise OrchestrationError("failed to start upstream Lan Mouse: %s" % exc) from exc
        finally:
            log_handle.close()
        identity = None
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and process.poll() is None:
            identity = self.adapter.process_identity(process.pid)
            if identity:
                break
            time.sleep(0.05)
        if not identity:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
            raise OrchestrationError("upstream process identity could not be established")
        expected = {
            "executable": argv[0],
            "argv": argv,
            "creation_id": identity.get("creation_id"),
            "config_path": str(toml_path.resolve(strict=True)),
        }
        if not self.adapter.process_matches(process.pid, expected):
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
            raise OrchestrationError("upstream process did not retain the exact managed identity")
        config_sha256 = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
        try:
            write_json(
                self.paths.process_state,
                {
                    "pid": process.pid,
                    "identity": expected,
                    "argv": argv,
                    "config_path": str(toml_path.resolve(strict=True)),
                    "config_text": config_text,
                    "config_sha256": config_sha256,
                    "started_at": int(time.time()),
                },
            )
            ready_deadline = time.monotonic() + 0.5
            while time.monotonic() < ready_deadline:
                if process.poll() is not None or not self.adapter.process_matches(process.pid, expected):
                    raise OrchestrationError("upstream Lan Mouse failed bounded identity readiness")
                time.sleep(0.05)
        except Exception as exc:
            # A candidate without durable ownership state is unsafe: OFF and
            # guard operations could no longer identify it. Tear it down on
            # every persistence/readiness failure so the caller can roll back.
            self.paths.process_state.unlink(missing_ok=True)
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            if isinstance(exc, OrchestrationError):
                raise
            raise OrchestrationError("failed to persist upstream process ownership state") from exc
        return True

    def _stop_unlocked(self) -> bool:
        state = self._state()
        pid = state.get("pid")
        expected = self._expected(state)
        if not isinstance(pid, int):
            return True
        live = self.adapter.process_identity(pid)
        if live is None:
            self.paths.process_state.unlink(missing_ok=True)
            return True
        if not expected or not self.adapter.process_matches(pid, expected):
            return False
        if not self.adapter.terminate_process(pid):
            return False
        creation_id = expected.get("creation_id")
        if not isinstance(creation_id, str) or not self.adapter.wait_for_exit(pid, creation_id, timeout=8.0):
            return False
        self.paths.process_state.unlink(missing_ok=True)
        return True

    def start(self, toml_path: Path) -> bool:
        with self.lock.held():
            candidate_text = toml_path.read_text(encoding="utf-8")
            candidate_sha = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
            prior_state = self._state()
            current = self._status_unlocked()
            if current["running"] and prior_state.get("config_sha256") == candidate_sha:
                return True
            if current.get("ambiguous"):
                raise OrchestrationError("refused to replace an ambiguously identified tracked process")
            prior_running = bool(current["running"])
            if prior_running and not self._stop_unlocked():
                raise OrchestrationError("refused to restart a process that is not safely owned")
            if current.get("tracked_pid") and not prior_running:
                stale_live = self.adapter.process_identity(int(current["tracked_pid"]))
                if stale_live is not None:
                    raise OrchestrationError("tracked PID is live but identity is ambiguous")
                self.paths.process_state.unlink(missing_ok=True)
            try:
                return self._launch(self._argv(toml_path), toml_path, candidate_text)
            except OrchestrationError as candidate_error:
                if prior_running:
                    prior_text = prior_state.get("config_text")
                    prior_path_raw = prior_state.get("config_path")
                    prior_argv = prior_state.get("argv")
                    if isinstance(prior_text, str) and isinstance(prior_path_raw, str) and isinstance(prior_argv, list):
                        prior_path = Path(prior_path_raw)
                        try:
                            _atomic_text(prior_path, prior_text)
                            self._launch([str(item) for item in prior_argv], prior_path, prior_text)
                        except (OSError, OrchestrationError) as rollback_error:
                            raise OrchestrationError(
                                "candidate restart failed and prior process rollback failed: %s; %s"
                                % (candidate_error, rollback_error)
                            ) from candidate_error
                        raise OrchestrationError("candidate restart failed; prior process was restored: %s" % candidate_error) from candidate_error
                raise

    def stop(self) -> bool:
        with self.lock.held():
            return self._stop_unlocked()


class Orchestrator:
    def __init__(self, config: Dict[str, Any], paths: SuitePaths, adapter: PlatformAdapter, logger: Any) -> None:
        self.config = config
        self.paths = paths
        self.adapter = adapter
        self.logger = logger
        self.lock = InterProcessLock(paths.control_lock)
        self.process = LanMouseProcess(config, paths, adapter, self.lock)

    def control(self) -> Dict[str, Any]:
        with self.lock.held():
            state = read_json(self.paths.control_state)
            return {
                "manual_off": bool(state.get("manual_off", False)),
                "selected_peer": state.get("selected_peer") if isinstance(state.get("selected_peer"), str) else None,
            }

    def _network(self) -> Optional[TrustedNetwork]:
        return match_trusted_network(self.adapter.network_snapshot(), self.config.get("profiles", []))

    def _reachable(self, trusted: TrustedNetwork, probe: bool = True) -> List[ResolvedPeer]:
        return [peer for peer, reachable in discover_profile_peers(self.config, trusted, self.adapter, probe=probe) if reachable]

    def _selected(self, peers: Sequence[ResolvedPeer]) -> List[ResolvedPeer]:
        selected = self.control().get("selected_peer")
        if selected:
            return [peer for peer in peers if peer.peer_id == selected]
        return list(peers)

    def _peer_source(self, peer_id: str) -> Dict[str, Any]:
        for peer in self.config.get("peers", []):
            if peer["id"] == peer_id:
                return peer
        raise OrchestrationError("unknown peer: " + peer_id)

    def _remote(self, peer: Dict[str, Any]) -> RemoteEndpoint:
        return RemoteEndpoint(peer)

    def _graphical_ready(self) -> bool:
        wait = getattr(self.adapter, "wait_graphical_environment", None)
        if not callable(wait):
            return True
        timeout = float(self.config.get("guard", {}).get("graphical_ready_seconds", 3))
        return bool(wait(timeout))

    def manual_on(self, peer_id: Optional[str] = None, coordinate_remote: bool = True) -> Dict[str, Any]:
        with self.lock.held():
            trusted = self._network()
            if trusted is None:
                raise OrchestrationError("current network is not trusted")
            profile = profile_by_id(self.config, trusted.profile_id)
            if peer_id is not None and peer_id not in profile.get("peers", []):
                raise OrchestrationError("peer is not available in the current trusted profile")
            resolved = self._reachable(trusted, probe=False)
            selected = [peer for peer in resolved if peer_id is None or peer.peer_id == peer_id]
            if not selected:
                raise OrchestrationError("no selected peer has an address inside the trusted network")
            if not self._graphical_ready():
                raise OrchestrationError("graphical session environment did not become ready")
            enabled_remotes: List[RemoteEndpoint] = []
            if coordinate_remote:
                try:
                    for item in selected:
                        source = self._peer_source(item.peer_id)
                        if source.get("remote_control", {}).get("enabled", False):
                            endpoint = self._remote(source)
                            if not endpoint.set_on():
                                raise RemoteControlError("remote endpoint remained off")
                            enabled_remotes.append(endpoint)
                except RemoteControlError as exc:
                    for endpoint in reversed(enabled_remotes):
                        try:
                            endpoint.set_off()
                        except RemoteControlError:
                            pass
                    raise OrchestrationError(str(exc)) from exc
            toml_path = write_managed_toml(self.config, selected, self.paths)
            try:
                self.process.start(toml_path)
            except OrchestrationError as exc:
                rollback_errors = []
                for endpoint in reversed(enabled_remotes):
                    try:
                        if endpoint.set_off():
                            rollback_errors.append("remote endpoint remained on")
                    except RemoteControlError as remote_error:
                        rollback_errors.append(str(remote_error))
                suffix = "; remote rollback: " + ", ".join(rollback_errors) if rollback_errors else ""
                raise OrchestrationError(str(exc) + suffix) from exc
            write_json(self.paths.control_state, {"manual_off": False, "selected_peer": peer_id})
            self.logger.info("manual on profile=%s peer=%s", trusted.profile_id, peer_id or "all")
            return self.status()

    def _remote_sources_for_off(self, selected_peer: Optional[str]) -> List[Dict[str, Any]]:
        result = []
        for peer in self.config.get("peers", []):
            if selected_peer is not None and peer.get("id") != selected_peer:
                continue
            if peer.get("remote_control", {}).get("enabled", False):
                result.append(peer)
        return result

    def manual_off(self, coordinate_remote: bool = True) -> Dict[str, Any]:
        with self.lock.held():
            prior = self.control()
            write_json(self.paths.control_state, {"manual_off": True, "selected_peer": prior.get("selected_peer")})
            stopped = self.process.stop()
            if not stopped:
                raise OrchestrationError("manual OFF persisted, but ambiguous tracked process termination was refused")
            remote_errors = []
            if coordinate_remote:
                for source in self._remote_sources_for_off(prior.get("selected_peer")):
                    try:
                        endpoint = self._remote(source)
                        if endpoint.set_off():
                            remote_errors.append(source["id"] + " remained on")
                    except RemoteControlError as exc:
                        remote_errors.append(source["id"] + ": " + str(exc))
            self.logger.info("manual off tracked_process_stopped=%s", stopped)
            if remote_errors:
                raise OrchestrationError("local endpoint is off; remote verification failed: " + "; ".join(remote_errors))
            return self.status()

    def guard_once(self) -> Dict[str, Any]:
        with self.lock.held():
            control = self.control()
            guard = read_json(self.paths.guard_state)
            failures = int(guard.get("failures", 0))
            trusted = self._network()
            reason = "untrusted network"
            resolved: List[ResolvedPeer] = []
            if trusted is not None:
                resolved = self._selected(self._reachable(trusted, probe=False))
                if not resolved:
                    reason = "no configured peer address inside trusted network"
                elif not self._graphical_ready():
                    reason = "graphical session environment unavailable"
                else:
                    write_json(self.paths.guard_state, {"failures": 0, "last_profile": trusted.profile_id})
                    if control["manual_off"]:
                        stopped = self.process.stop()
                        action = "manual-off-preserved" if stopped else "manual-off-stop-refused"
                        self.logger.info("guard trusted profile=%s; %s", trusted.profile_id, action)
                        return {"ok": stopped, "action": action, "status": self.status(probe=False)}
                    toml_path = write_managed_toml(self.config, resolved, self.paths)
                    self.process.start(toml_path)
                    return {"ok": True, "action": "running", "status": self.status(probe=False)}
            failures += 1
            limit = int(self.config.get("guard", {}).get("failure_limit", 3))
            write_json(self.paths.guard_state, {"failures": failures, "reason": reason})
            action = "hysteresis"
            if failures >= limit:
                stopped = self.process.stop()
                action = "guard-stopped" if stopped else "guard-stop-refused"
            self.logger.info("guard failure=%d/%d reason=%s action=%s", failures, limit, reason, action)
            return {"ok": True, "action": action, "failures": failures, "reason": reason, "status": self.status(probe=False)}

    def status(self, probe: bool = True, include_remote: bool = True) -> Dict[str, Any]:
        with self.lock.held():
            trusted = self._network()
            process = self.process.status()
            control = self.control()
            current = trusted.profile_id if trusted else None
            rows = []
            active_ids = set()
            if trusted:
                for peer, reachable in discover_profile_peers(self.config, trusted, self.adapter, probe=probe):
                    if process["running"]:
                        selected = control.get("selected_peer")
                        if selected is None or selected == peer.peer_id:
                            active_ids.add(peer.peer_id)
                    rows.append((peer, reachable))
            by_id = {peer["id"]: peer for peer in self.config.get("peers", [])}
            output_rows = []
            for profile_peer_id in [peer["id"] for peer in self.config.get("peers", [])]:
                source = by_id[profile_peer_id]
                pair = next(((peer, reachable) for peer, reachable in rows if peer.peer_id == profile_peer_id), None)
                reachable = bool(pair and pair[1])
                on = profile_peer_id in active_ids
                remote_on = None
                if include_remote and pair and source.get("remote_control", {}).get("enabled", False):
                    try:
                        remote_on = self._remote(source).status()
                    except RemoteControlError:
                        remote_on = None
                if not trusted:
                    detail = "Not on a trusted LAN"
                elif profile_peer_id not in profile_by_id(self.config, trusted.profile_id).get("peers", []):
                    detail = "Not on this LAN"
                elif not pair:
                    detail = "No in-LAN address"
                elif control["manual_off"]:
                    detail = "Manually off"
                elif on:
                    detail = "On" if reachable else "On; management probe unavailable"
                else:
                    detail = "Off"
                output_rows.append(
                    {
                        "id": profile_peer_id,
                        "name": source.get("name", profile_peer_id),
                        "reachable": reachable,
                        "on": on,
                        "remote_on": remote_on,
                        "detail": detail,
                        "address": pair[0].address if pair else None,
                    }
                )
            network = "%s (%s via %s)" % (trusted.name, trusted.cidr, trusted.gateway) if trusted else "Unapproved network"
            return {
                "network": network,
                "current": current,
                "devices": output_rows,
                "any_on": bool(active_ids),
                "manual_off": control["manual_off"],
                "process": process,
                "generated_config": str(managed_toml_path(self.config, self.paths)),
                "log_path": str(self.paths.log_file),
            }
