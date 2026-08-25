import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lanmouse_suite.config import default_config
from lanmouse_suite.models import ResolvedPeer, TrustedNetwork
from lanmouse_suite.orchestration import OrchestrationError, Orchestrator
from lanmouse_suite.paths import SuitePaths
from lanmouse_suite.remote import RemoteControlError
from lanmouse_suite.state import read_json


class FakeProcess:
    def __init__(self, events=None, start_error=False, start_delay=0):
        self.running = False
        self.starts = 0
        self.stops = 0
        self.events = events if events is not None else []
        self.start_error = start_error
        self.start_delay = start_delay
        self.started_event = threading.Event()

    def status(self):
        return {"running": self.running, "pid": 10 if self.running else None, "tracked_pid": 10 if self.running else None, "ambiguous": False}

    def start(self, path):
        self.events.append("local-on")
        self.started_event.set()
        time.sleep(self.start_delay)
        self.starts += 1
        if self.start_error:
            raise OrchestrationError("candidate failed")
        self.running = True
        return True

    def stop(self):
        self.events.append("local-off")
        self.stops += 1
        self.running = False
        return True


class FakeAdapter:
    def wait_graphical_environment(self, timeout): return True


class FakeRemote:
    def __init__(self, events, status_error=False):
        self.events = events
        self.status_error = status_error
    def set_on(self): self.events.append("remote-on"); return True
    def set_off(self): self.events.append("remote-off"); return False
    def status(self):
        if self.status_error: raise RemoteControlError("unavailable")
        return True


class TestOrchestrator(Orchestrator):
    __test__ = False

    def __init__(self, *args, trusted=None, resolved=None, remote=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_trusted = trusted
        self.fixed_resolved = resolved or []
        self.fixed_remote = remote

    def _network(self): return self.fixed_trusted
    def _reachable(self, trusted, probe=True): return list(self.fixed_resolved)
    def _remote(self, peer): return self.fixed_remote or super()._remote(peer)
    def status(self, probe=True, include_remote=True):
        control = self.control()
        return {"running": self.process.status()["running"], "manual_off": control["manual_off"]}


class FullStatusOrchestrator(TestOrchestrator):
    def status(self, probe=True, include_remote=True):
        return Orchestrator.status(self, probe=probe, include_remote=include_remote)


def make_config(remote=False):
    config = default_config()
    config["upstream"]["authorized_fingerprints"] = {}
    peer = {"id": "desk", "name": "Desk", "addresses": ["192.168.50.20"], "position": "right", "port": 4242, "probe_port": 22, "ssh": {"target": "user@desk.local", "remote_cli": "lanmouse-suite"}}
    if remote:
        peer["remote_control"] = {"enabled": True, "remote_peer_id": "laptop"}
    config["peers"] = [peer]
    config["profiles"] = [{"id": "home", "name": "Home", "cidr": "192.168.50.0/24", "gateway": "192.168.50.1", "peers": ["desk"], "allow_tailscale": False}]
    return config


class OrchestrationTests(unittest.TestCase):
    def make(self, root, trusted, resolved, remote=None, remote_enabled=False, full_status=False):
        paths = SuitePaths(root / "config", root / "state", root / "logs")
        cls = FullStatusOrchestrator if full_status else TestOrchestrator
        return cls(make_config(remote_enabled), paths, FakeAdapter(), logging.getLogger("test"), trusted=trusted, resolved=resolved, remote=remote)

    def trusted_peer(self):
        return (
            TrustedNetwork("home", "Home", "192.168.50.0/24", "192.168.50.9", "192.168.50.1", "eth0"),
            ResolvedPeer("desk", "Desk", "192.168.50.20", 4242, "right"),
        )

    def test_manual_off_persists_and_guard_does_not_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            trusted, peer = self.trusted_peer()
            orch = self.make(Path(directory), trusted, [peer])
            orch.process = FakeProcess()
            orch.manual_off()
            self.assertTrue(read_json(orch.paths.control_state)["manual_off"])
            result = orch.guard_once()
            self.assertEqual(result["action"], "manual-off-preserved")
            self.assertEqual(orch.process.starts, 0)
            self.assertGreaterEqual(orch.process.stops, 2)

    def test_untrusted_network_uses_hysteresis_then_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            orch = self.make(Path(directory), None, [])
            orch.process = FakeProcess()
            self.assertEqual(orch.guard_once()["action"], "hysteresis")
            self.assertEqual(orch.guard_once()["action"], "hysteresis")
            self.assertEqual(orch.guard_once()["action"], "guard-stopped")

    def test_remote_target_first_local_second_and_off_reverse(self):
        with tempfile.TemporaryDirectory() as directory:
            trusted, peer = self.trusted_peer()
            events = []
            orch = self.make(Path(directory), trusted, [peer], FakeRemote(events), remote_enabled=True)
            orch.process = FakeProcess(events)
            orch.manual_on("desk")
            self.assertEqual(events[:2], ["remote-on", "local-on"])
            orch.manual_off()
            self.assertEqual(events[-2:], ["local-off", "remote-off"])

    def test_local_start_failure_rolls_remote_back_off(self):
        with tempfile.TemporaryDirectory() as directory:
            trusted, peer = self.trusted_peer()
            events = []
            orch = self.make(Path(directory), trusted, [peer], FakeRemote(events), remote_enabled=True)
            orch.process = FakeProcess(events, start_error=True)
            with self.assertRaises(OrchestrationError):
                orch.manual_on("desk")
            self.assertEqual(events, ["remote-on", "local-on", "remote-off"])

    def test_remote_status_failure_is_nullable_unknown_not_local_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            trusted, peer = self.trusted_peer()
            orch = self.make(Path(directory), trusted, [peer], FakeRemote([], status_error=True), remote_enabled=True, full_status=True)
            orch.process = FakeProcess()
            orch.process.running = True
            result = orch.status(probe=False)
            self.assertTrue(result["devices"][0]["on"])
            self.assertIsNone(result["devices"][0]["remote_on"])

    def test_concurrent_on_off_serializes_and_finishes_off(self):
        with tempfile.TemporaryDirectory() as directory:
            trusted, peer = self.trusted_peer()
            orch = self.make(Path(directory), trusted, [peer])
            process = FakeProcess(start_delay=0.15)
            orch.process = process
            errors = []
            on_thread = threading.Thread(target=lambda: self._capture(errors, orch.manual_on, "desk"))
            off_thread = threading.Thread(target=lambda: self._capture(errors, orch.manual_off))
            on_thread.start()
            self.assertTrue(process.started_event.wait(1))
            off_thread.start()
            on_thread.join(2)
            off_thread.join(2)
            self.assertEqual(errors, [])
            self.assertFalse(process.running)
            self.assertTrue(read_json(orch.paths.control_state)["manual_off"])

    @staticmethod
    def _capture(errors, function, *args):
        try:
            function(*args)
        except Exception as exc:
            errors.append(exc)


if __name__ == "__main__":
    unittest.main()
