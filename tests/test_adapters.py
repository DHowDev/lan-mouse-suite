import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanmouse_suite.adapters import CommandRunner, LinuxAdapter, MacOSAdapter, WindowsAdapter
from lanmouse_suite.clipboard import remote_clipboard_command
from lanmouse_suite.models import CommandResult


class FakeRunner(CommandRunner):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, argv, data=None, timeout=8.0):
        args = list(argv)
        self.calls.append((args, data))
        if self.responses:
            code, output = self.responses.pop(0)
            return CommandResult(args, code, output, b"")
        return CommandResult(args, 0, b"", b"")


class AdapterCommandTests(unittest.TestCase):
    def test_macos_commands_and_parsing(self):
        runner = FakeRunner([(0, b"gateway: 192.168.1.1\ninterface: en0\n"), (0, b"192.168.1.9\n")])
        adapter = MacOSAdapter(runner, utf8_locale="en_US.UTF-8")
        prefix = ["/usr/bin/env", "LANG=en_US.UTF-8", "LC_ALL=en_US.UTF-8"]
        self.assertEqual(adapter.clipboard_read_command(), prefix + ["/usr/bin/pbpaste"])
        self.assertEqual(adapter.clipboard_write_command(), prefix + ["/usr/bin/pbcopy"])
        snapshot = adapter.network_snapshot()
        self.assertEqual(snapshot.interface, "en0")
        self.assertEqual(runner.calls[1][0], ["/usr/sbin/ipconfig", "getifaddr", "en0"])

    def test_linux_commands_and_parsing(self):
        route = json.dumps([{"dev": "wlan0", "gateway": "192.168.1.1"}]).encode()
        addr = json.dumps([{"addr_info": [{"family": "inet", "scope": "global", "local": "192.168.1.9"}]}]).encode()
        runner = FakeRunner([(0, route), (0, addr)])
        adapter = LinuxAdapter(runner)
        self.assertEqual(adapter.clipboard_read_command(), ["wl-paste", "--type", "text/plain", "--no-newline"])
        self.assertEqual(adapter.clipboard_write_command(), ["wl-copy", "--type", "text/plain"])
        self.assertEqual(adapter.network_snapshot().address, "192.168.1.9")
        self.assertEqual(runner.calls[0][0], ["ip", "-j", "route", "show", "default"])

    def test_linux_child_environment_discovers_wayland_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            sock = socket.socket(socket.AF_UNIX)
            path = Path(directory) / "wayland-7"
            sock.bind(str(path))
            try:
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}, clear=True):
                    environment = LinuxAdapter(FakeRunner([])).child_environment()
                self.assertEqual(environment["WAYLAND_DISPLAY"], "wayland-7")
                self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=%s/bus" % directory)
            finally:
                sock.close()

    def test_windows_commands_use_fixed_powershell_scripts(self):
        runner = FakeRunner([(0, b'{"address":"192.168.1.9","gateway":"192.168.1.1","interface":"Ethernet"}')])
        adapter = WindowsAdapter(runner)
        self.assertEqual(adapter.clipboard_read_command()[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertIn("Set-Clipboard", adapter.clipboard_write_command()[-1])
        snapshot = adapter.network_snapshot()
        self.assertEqual(snapshot.interface, "Ethernet")
        self.assertIn("Get-NetRoute", runner.calls[0][0][-1])
        self.assertIn("Get-NetIPAddress", runner.calls[0][0][-1])

    def test_ssh_remote_clipboard_is_argv_not_interpolated(self):
        peer = {"ssh": {"target": "user@desk.local", "remote_cli": "/opt/lanmouse/bin/lanmouse-suite", "identity_file": "/keys/id_ed25519"}}
        command = remote_clipboard_command(peer, "write")
        self.assertEqual(command[-4:], ["user@desk.local", "/opt/lanmouse/bin/lanmouse-suite", "clipboard", "write"])
        self.assertIn("/keys/id_ed25519", command)


if __name__ == "__main__":
    unittest.main()
