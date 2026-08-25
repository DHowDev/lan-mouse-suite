import tempfile
import unittest
from pathlib import Path

from lanmouse_suite.config import ConfigError, default_config, import_existing_config, validate_config
from lanmouse_suite.models import ResolvedPeer
from lanmouse_suite.paths import SuitePaths
from lanmouse_suite.toml_config import render_toml, write_managed_toml


FP = ":".join(["ab"] * 32)


def configured():
    config = default_config()
    config["upstream"]["authorized_fingerprints"] = {FP: "desk"}
    config["peers"] = [{"id": "desk", "name": "Desk", "addresses": ["192.168.50.20"], "position": "right", "port": 4242, "ssh": {"target": "user@desk.local", "remote_cli": "lanmouse-suite"}}]
    config["profiles"] = [{"id": "home", "name": "Home", "cidr": "192.168.50.0/24", "gateway": "192.168.50.1", "peers": ["desk"], "allow_tailscale": False}]
    return config


class ConfigTests(unittest.TestCase):
    def test_valid_config(self):
        self.assertEqual(validate_config(configured())["version"], 1)

    def test_feature_flags_are_strict_booleans(self):
        for section, key in (("clipboard", "enabled"), ("clipboard", "endpoint_enabled"), ("screenshots", "enabled"), ("remote_control", "endpoint_enabled")):
            with self.subTest(section=section, key=key):
                config = configured()
                config[section][key] = "false"
                with self.assertRaises(ConfigError):
                    validate_config(config)

    def test_clipboard_cadence_ranges_are_bounded(self):
        for key, value in (("poll_seconds", 0), ("poll_seconds", 61), ("backoff_seconds", 0), ("backoff_seconds", 301)):
            config = configured()
            config["clipboard"][key] = value
            with self.assertRaises(ConfigError):
                validate_config(config)

    def test_remote_control_requires_peer_id_and_ssh(self):
        config = configured()
        config["peers"][0]["remote_control"] = {"enabled": True}
        with self.assertRaises(ConfigError):
            validate_config(config)

    def test_rejects_unsafe_ssh_target(self):
        config = configured()
        config["peers"][0]["ssh"]["target"] = "user@desk.local;touch /tmp/x"
        with self.assertRaises(ConfigError):
            validate_config(config)

    def test_rejects_option_like_ssh_target(self):
        config = configured()
        config["peers"][0]["ssh"]["target"] = "-oProxyCommand"
        with self.assertRaises(ConfigError):
            validate_config(config)

    def test_rejects_gateway_outside_cidr(self):
        config = configured()
        config["profiles"][0]["gateway"] = "10.0.0.1"
        with self.assertRaises(ConfigError):
            validate_config(config)

    def test_import_selects_sibling_cert_and_preserves_backend_flags_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "config.toml"
            pem = root / "lan-mouse.pem"
            text = 'capture_backend = "portal"\nemulation_backend = "libei"\n[authorized_fingerprints]\n"%s" = "existing-device"\n' % FP
            source.write_text(text, encoding="utf-8")
            pem.write_bytes(b"PRIVATE IDENTITY BYTES")
            config, count = import_existing_config(configured(), source)
            self.assertEqual(count, 1)
            self.assertEqual(config["upstream"]["cert_path"], str(pem.resolve()))
            self.assertIn("--capture-backend", config["upstream"]["extra_args"])
            self.assertIn("--emulation-backend", config["upstream"]["extra_args"])
            self.assertEqual(source.read_text(encoding="utf-8"), text)
            self.assertEqual(pem.read_bytes(), b"PRIVATE IDENTITY BYTES")
            paths = SuitePaths(root / "suite-config", root / "state", root / "logs")
            target = write_managed_toml(config, [ResolvedPeer("desk", "Desk", "192.168.50.20", 4242, "right")], paths)
            self.assertEqual(target, root / "config.lanmouse-suite.toml")
            self.assertEqual(source.read_text(encoding="utf-8"), text)
            self.assertEqual(pem.read_bytes(), b"PRIVATE IDENTITY BYTES")

    def test_render_keeps_authorized_fingerprints(self):
        text = render_toml(configured(), [ResolvedPeer("desk", "Desk", "192.168.50.20", 4242, "right")])
        self.assertIn("[authorized_fingerprints]", text)
        self.assertIn(FP, text)
        self.assertIn('hostname = "192.168.50.20"', text)


if __name__ == "__main__":
    unittest.main()
