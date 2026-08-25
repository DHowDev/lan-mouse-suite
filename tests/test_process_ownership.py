import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lanmouse_suite.adapters import LinuxAdapter
from lanmouse_suite.config import default_config
from lanmouse_suite.orchestration import LanMouseProcess, OrchestrationError
from lanmouse_suite.paths import SuitePaths
from lanmouse_suite.state import read_json, write_json


@unittest.skipUnless(sys.platform.startswith("linux"), "real /proc identity test is Linux-specific")
class ProcessOwnershipTests(unittest.TestCase):
    def _paths(self, root):
        return SuitePaths(root / "config", root / "state", root / "logs")

    def _sleep(self, config):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--config", str(config)])

    def test_real_spoof_with_expected_substrings_is_never_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "managed.toml"
            config.write_text("port = 4242\n")
            child = self._sleep(config)
            try:
                adapter = LinuxAdapter()
                live = adapter.process_identity(child.pid)
                expected = {
                    "executable": live["executable"],
                    "creation_id": live["creation_id"],
                    "config_path": str(config),
                    "argv": [live["executable"], "--config", str(config), "daemon"],
                }
                paths = self._paths(root)
                write_json(paths.process_state, {"pid": child.pid, "identity": expected})
                process = LanMouseProcess(default_config(), paths, adapter)
                self.assertFalse(process.stop())
                self.assertIsNone(child.poll())
                self.assertTrue(paths.process_state.exists())
            finally:
                child.terminate()
                child.wait(timeout=3)

    def test_exact_identity_is_terminated_and_exit_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "managed.toml"
            config.write_text("port = 4242\n")
            child = self._sleep(config)
            adapter = LinuxAdapter()
            live = adapter.process_identity(child.pid)
            expected = dict(live)
            expected["config_path"] = str(config)
            paths = self._paths(root)
            write_json(paths.process_state, {"pid": child.pid, "identity": expected})
            process = LanMouseProcess(default_config(), paths, adapter)
            self.assertTrue(process.stop())
            child.wait(timeout=3)
            self.assertIsNotNone(child.poll())
            self.assertFalse(paths.process_state.exists())


class FakeAdapter:
    def __init__(self):
        self.identities = {
            100: {"executable": str(Path(sys.executable).resolve()), "creation_id": "old", "argv": []}
        }

    def child_environment(self): return {}
    def process_identity(self, pid): return self.identities.get(pid)
    def process_matches(self, pid, expected):
        live = self.identities.get(pid)
        return bool(live and live["executable"] == expected["executable"] and live["creation_id"] == expected["creation_id"] and live["argv"] == expected["argv"])
    def terminate_process(self, pid):
        self.identities.pop(pid, None)
        return True
    def wait_for_exit(self, pid, creation_id, timeout=8): return pid not in self.identities


class FakePopen:
    def __init__(self, pid, returncode=None):
        self.pid = pid
        self.returncode = returncode
    def poll(self): return self.returncode
    def terminate(self): self.returncode = -15
    def wait(self, timeout=None): return self.returncode or 0
    def kill(self): self.returncode = -9


class RestartRollbackTests(unittest.TestCase):
    def test_state_write_failure_terminates_untracked_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SuitePaths(root / "config", root / "state", root / "logs")
            managed = root / "managed.toml"
            managed.write_text("port = 4242\n")
            executable = str(Path(sys.executable).resolve())
            config = default_config()
            config["upstream"]["binary"] = executable
            adapter = FakeAdapter()
            adapter.identities.clear()
            candidate = FakePopen(400, None)

            def popen(argv, **_kwargs):
                adapter.identities[400] = {
                    "executable": executable,
                    "creation_id": "candidate",
                    "argv": list(argv),
                }
                return candidate

            with patch("lanmouse_suite.orchestration.subprocess.Popen", side_effect=popen), \
                 patch("lanmouse_suite.orchestration.write_json", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OrchestrationError, "persist upstream process ownership"):
                    LanMouseProcess(config, paths, adapter).start(managed)
            self.assertIsNotNone(candidate.poll())
            self.assertFalse(paths.process_state.exists())

    def test_failed_restart_restores_prior_config_and_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SuitePaths(root / "config", root / "state", root / "logs")
            managed = root / "managed.toml"
            old_text = "port = 4242\n# old\n"
            new_text = "port = 4242\n# candidate\n"
            managed.write_text(new_text)
            executable = str(Path(sys.executable).resolve())
            old_argv = [executable, "--config", str(managed.resolve()), "daemon"]
            adapter = FakeAdapter()
            adapter.identities[100]["argv"] = old_argv
            old_identity = dict(adapter.identities[100])
            old_identity["config_path"] = str(managed.resolve())
            write_json(paths.process_state, {
                "pid": 100, "identity": old_identity, "argv": old_argv,
                "config_path": str(managed.resolve()), "config_text": old_text,
                "config_sha256": "not-candidate",
            })
            config = default_config()
            config["upstream"]["binary"] = executable
            launches = []

            def popen(argv, **_kwargs):
                launches.append(list(argv))
                if len(launches) == 1:
                    return FakePopen(200, 1)
                process = FakePopen(300, None)
                adapter.identities[300] = {"executable": executable, "creation_id": "rollback", "argv": list(argv)}
                return process

            with patch("lanmouse_suite.orchestration.subprocess.Popen", side_effect=popen):
                with self.assertRaisesRegex(OrchestrationError, "prior process was restored"):
                    LanMouseProcess(config, paths, adapter).start(managed)
            self.assertEqual(managed.read_text(), old_text)
            state = read_json(paths.process_state)
            self.assertEqual(state["pid"], 300)
            self.assertEqual(state["config_text"], old_text)
            self.assertEqual(len(launches), 2)


if __name__ == "__main__":
    unittest.main()
