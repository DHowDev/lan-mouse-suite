import argparse
import hashlib
import importlib.util
import logging
import tempfile
import unittest
from pathlib import Path

from lanmouse_suite.cli import _clipboard
from lanmouse_suite.config import ConfigError, default_config
from lanmouse_suite.doctor import doctor_report
from lanmouse_suite.models import CommandResult
from lanmouse_suite.orchestration import LanMouseProcess
from lanmouse_suite.paths import SuitePaths
from lanmouse_suite.remote import RemoteEndpoint, remote_endpoint_command


class NoClipboardAdapter:
    def read_clipboard(self, max_bytes): raise AssertionError("must remain gated")
    def write_clipboard(self, data, max_bytes): raise AssertionError("must remain gated")
    def graphical_environment_ready(self): return True


class EndpointRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def run_bounded(self, argv, max_bytes, data=None, timeout=8):
        self.calls.append(list(argv))
        return CommandResult(list(argv), 0, self.responses.pop(0), b"")


class EndpointSecurityTests(unittest.TestCase):
    def test_clipboard_read_write_require_explicit_endpoint_flag(self):
        config = default_config()
        paths = SuitePaths(Path("/tmp/config"), Path("/tmp/state"), Path("/tmp/log"))
        for action in ("read", "write"):
            args = argparse.Namespace(clipboard_command=action)
            with self.assertRaisesRegex(ConfigError, "endpoint is disabled"):
                _clipboard(args, config, paths, NoClipboardAdapter(), logging.getLogger("test"))

    def test_remote_endpoint_uses_fixed_argv_and_authenticated_readback(self):
        peer = {
            "ssh": {"target": "user@desk.local", "remote_cli": "/opt/suite/bin/lanmouse-suite"},
            "remote_control": {"enabled": True, "remote_peer_id": "laptop"},
        }
        expected = remote_endpoint_command(peer, "on", "laptop")
        self.assertEqual(expected[-5:], ["user@desk.local", "/opt/suite/bin/lanmouse-suite", "endpoint", "on", "laptop"])
        runner = EndpointRunner([b'{"on":true}', b'{"on":true}'])
        self.assertTrue(RemoteEndpoint(peer, runner=runner).set_on())
        self.assertEqual(runner.calls[0][-3:], ["endpoint", "on", "laptop"])
        self.assertEqual(runner.calls[1][-3:], ["endpoint", "status", "laptop"])

    def test_forced_command_allowlist_refuses_extra_or_wrong_peer_arguments(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "ssh-forced-command.py"
        spec = importlib.util.spec_from_file_location("ssh_forced_command", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cli = "/opt/suite/bin/lanmouse-suite"
        self.assertEqual(module.allowed_arguments(cli + " endpoint on laptop", cli, "laptop"), ["endpoint", "on", "laptop"])
        self.assertIsNone(module.allowed_arguments(cli + " endpoint on other", cli, "laptop"))
        self.assertIsNone(module.allowed_arguments(cli + " endpoint status laptop; id", cli, "laptop"))
        self.assertEqual(module.allowed_arguments(cli + " clipboard read", cli, "laptop"), ["clipboard", "read"])

    def test_process_argv_includes_explicit_cert_path(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SuitePaths(root / "config", root / "state", root / "logs")
            toml = root / "managed.toml"
            toml.write_text("port = 4242\n")
            cert = root / "lan-mouse.pem"
            cert.write_bytes(b"identity")
            config = default_config()
            config["upstream"]["binary"] = sys.executable
            config["upstream"]["cert_path"] = str(cert)
            process = LanMouseProcess(config, paths, NoClipboardAdapter())
            argv = process._argv(toml)
            index = argv.index("--cert-path")
            self.assertEqual(argv[index + 1], str(cert.resolve()))
            self.assertEqual(argv[1:3], ["--config", str(toml.resolve())])

    def test_doctor_reports_pem_hash_without_claiming_fingerprint(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text("{}")
            cert = root / "lan-mouse.pem"
            cert.write_bytes(b"identity")
            config = default_config()
            config["upstream"]["binary"] = sys.executable
            config["upstream"]["cert_path"] = str(cert)
            report = doctor_report(config, config_path, NoClipboardAdapter())
            certificate = report["checks"]["certificate"]
            self.assertEqual(certificate["sha256"], hashlib.sha256(b"identity").hexdigest())
            self.assertEqual(certificate["fingerprint"], "not-computed")


if __name__ == "__main__":
    unittest.main()
