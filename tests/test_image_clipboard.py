import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanmouse_suite.image_clipboard import ImageClipboardSynchronizer, digest, read_local, write_local


class ImageClipboardTests(unittest.TestCase):
    def test_limits_and_platform_dispatch(self):
        self.assertIsNone(read_local("Unsupported", 100))
        self.assertFalse(write_local("Unsupported", b"png", 100))
        self.assertEqual(len(digest(b"png")), 64)

    def test_image_sync_state_and_dedupe(self):
        class FakeRemote:
            def __init__(self):
                self.data = b"remote"
                self.writes = []
            def read(self, max_bytes):
                return self.data
            def write(self, data, max_bytes):
                self.writes.append(data)
                self.data = data
                return True
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "image.json"
            fake = FakeRemote()
            with patch("lanmouse_suite.image_clipboard.RemoteImageClipboard", return_value=fake), \
                 patch("lanmouse_suite.image_clipboard.read_local", return_value=b"local"), \
                 patch("lanmouse_suite.image_clipboard.write_local", return_value=True):
                sync = ImageClipboardSynchronizer("peer", "Linux", {}, state, 1000, "local", None)
                self.assertEqual(sync.sync_once(), "local-to-remote")
                self.assertEqual(sync.sync_once(), "equal")
                self.assertEqual(fake.writes, [b"local"])


if __name__ == "__main__":
    unittest.main()
