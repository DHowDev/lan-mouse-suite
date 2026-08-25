import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanmouse_suite.adapters import PlatformAdapter
from lanmouse_suite.models import NetworkSnapshot
from lanmouse_suite.paths import SuitePaths
from lanmouse_suite.service import SuiteService


class Adapter(PlatformAdapter):
    def clipboard_read_command(self): return []
    def clipboard_write_command(self): return []
    def network_snapshot(self): return NetworkSnapshot(None, None, None)
    def process_command(self, pid): return []
    def terminate_process(self, pid): return False


class Logger:
    def exception(self, *_args): pass


class Process:
    def status(self): return {"running": True}


class Orchestrator:
    def __init__(self):
        self.process = Process()
        self.guards = 0

    def guard_once(self):
        self.guards += 1
        return {"ok": True}


class ServiceCadenceTests(unittest.TestCase):
    def test_clipboard_poll_is_independent_from_slower_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SuitePaths(root, root, root)
            config = {
                "guard": {"interval_seconds": 0.06},
                "clipboard": {"enabled": True, "poll_seconds": 0.01},
                "peers": [],
            }
            service = SuiteService(config, paths, Adapter(), Logger())
            orchestrator = Orchestrator()
            service.orchestrator = orchestrator
            calls = []

            def clipboard_once():
                calls.append(1)
                if len(calls) >= 3:
                    service.stopping = True
                return {}

            service.clipboard_once = clipboard_once
            with patch("lanmouse_suite.service.signal.signal"):
                service.run()
            self.assertGreaterEqual(len(calls), 3)
            self.assertEqual(orchestrator.guards, 1)


if __name__ == "__main__":
    unittest.main()
