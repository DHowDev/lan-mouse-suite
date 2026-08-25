import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanmouse_suite.adapters import CommandRunner
from lanmouse_suite.screenshots import ScreenshotError, read_export, remote_basename, validated_path, write_inbox


class ScreenshotTests(unittest.TestCase):
    def test_windows_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "capture.png"
            target.write_bytes(b"png")
            with patch("lanmouse_suite.screenshots.os.name", "nt"):
                with self.assertRaisesRegex(ScreenshotError, "not supported on Windows"):
                    read_export(root, str(target), 100)

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            outside = Path(directory) / "outside.png"
            outside.write_bytes(b"image")
            with self.assertRaises(ScreenshotError):
                validated_path(root, Path("../outside.png"), must_exist=True)
            with self.assertRaises(ScreenshotError):
                read_export(root, str(outside), 100)

    def test_symlink_leaf_and_parent_are_rejected(self):
        if os.name == "nt":
            self.skipTest("POSIX no-follow test")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "root"
            root.mkdir()
            outside = base / "outside.png"
            outside.write_bytes(b"secret")
            (root / "leaf.png").symlink_to(outside)
            with self.assertRaises(ScreenshotError):
                read_export(root, "leaf.png", 100)
            outside_dir = base / "outside-dir"
            outside_dir.mkdir()
            (outside_dir / "capture.png").write_bytes(b"secret")
            (root / "linked").symlink_to(outside_dir, target_is_directory=True)
            with self.assertRaises(ScreenshotError):
                read_export(root, "linked/capture.png", 100)

    def test_stream_runner_terminates_at_max_plus_one(self):
        command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x'*100000); sys.stdout.flush()"]
        result = CommandRunner().run_bounded(command, 1024, timeout=5)
        self.assertEqual(result.returncode, 125)
        self.assertEqual(len(result.stdout), 1025)

    def test_filename_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ScreenshotError):
                write_inbox(Path(directory), "../capture.png", b"image", 100)
            with self.assertRaises(ScreenshotError):
                write_inbox(Path(directory), "sub/capture.png", b"image", 100)

    def test_safe_export_and_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "export"
            inbox = Path(directory) / "inbox"
            root.mkdir()
            source = root / "capture.png"
            source.write_bytes(b"png-data")
            data = read_export(root, str(source), 100)
            target = write_inbox(inbox, "capture.png", data, 100)
            self.assertEqual(target.read_bytes(), b"png-data")

    def test_remote_basename_accepts_windows_or_posix_path(self):
        self.assertEqual(remote_basename("/home/user/capture.png"), "capture.png")
        self.assertEqual(remote_basename(r"C:\Users\user\capture.png"), "capture.png")


if __name__ == "__main__":
    unittest.main()
