import logging
import tempfile
import unittest
from pathlib import Path

from lanmouse_suite.clipboard import ClipboardSynchronizer
from lanmouse_suite.state import read_json


class LocalClipboard:
    def __init__(self, data):
        self.data = data
        self.writes = []
        self.allow_write = True

    def read_clipboard(self, max_bytes):
        return self.data

    def write_clipboard(self, data, max_bytes):
        self.writes.append(data)
        if self.allow_write:
            self.data = data
            return True
        return False


class RemoteClipboard:
    def __init__(self, data):
        self.data = data
        self.writes = []
        self.failures = 0

    def read(self, max_bytes):
        return self.data

    def write(self, data, max_bytes):
        self.writes.append(data)
        if self.failures:
            self.failures -= 1
            return False
        self.data = data
        return True


class ClipboardTests(unittest.TestCase):
    def test_failed_delivery_does_not_advance_hash_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "clipboard.json"
            local = LocalClipboard("local text".encode())
            remote = RemoteClipboard("remote text".encode())
            remote.failures = 1
            sync = ClipboardSynchronizer("desk", local, remote, state, 1000, "local", logging.getLogger("test"))
            self.assertEqual(sync.sync_once(), "delivery-failed")
            self.assertEqual(read_json(state), {})
            self.assertEqual(sync.sync_once(), "local-to-remote")
            self.assertEqual(len(remote.writes), 2)
            self.assertIn("desk", read_json(state)["peers"])

    def test_dedupe_prevents_loop_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "clipboard.json"
            local = LocalClipboard(b"alpha")
            remote = RemoteClipboard(b"beta")
            sync = ClipboardSynchronizer("desk", local, remote, state, 1000, "local", logging.getLogger("test"))
            self.assertEqual(sync.sync_once(), "local-to-remote")
            self.assertEqual(sync.sync_once(), "equal")
            self.assertEqual(remote.writes, [b"alpha"])
            self.assertEqual(local.writes, [])

    def test_remote_conflict_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "clipboard.json"
            local = LocalClipboard(b"local")
            remote = RemoteClipboard(b"remote")
            sync = ClipboardSynchronizer("desk", local, remote, state, 1000, "remote", logging.getLogger("test"))
            self.assertEqual(sync.sync_once(), "remote-to-local")
            local.data = b"local-2"
            remote.data = b"remote-2"
            self.assertEqual(sync.sync_once(), "remote-won")
            self.assertEqual(local.data, b"remote-2")


if __name__ == "__main__":
    unittest.main()
