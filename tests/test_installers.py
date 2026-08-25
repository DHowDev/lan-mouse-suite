import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerSafetyTests(unittest.TestCase):
    def test_linux_arch_dependency_and_stage_default(self):
        text = (ROOT / "install-linux.sh").read_text(encoding="utf-8")
        self.assertIn("python python-pip tk wl-clipboard", text)
        self.assertNotIn("python-tk", text)
        self.assertIn("--activate", text)
        self.assertIn('if [ "$ACTIVATE" -eq 1 ]', text)
        self.assertIn("systemctl --user is-enabled", text)
        self.assertIn("systemctl --user is-active", text)

    def test_macos_has_separate_status_launchagent_and_stage_gate(self):
        script = (ROOT / "install-macos.sh").read_text(encoding="utf-8")
        self.assertIn("io.nous.lanmouse-suite.status.plist", script)
        self.assertIn('if [ "$ACTIVATE" -eq 1 ]', script)
        self.assertIn("exactly one status process path", script)
        plist = (ROOT / "templates/launchd/io.nous.lanmouse-suite.status.plist").read_text(encoding="utf-8")
        self.assertIn("io.nous.lanmouse-suite.status", plist)
        self.assertIn("@APP_EXECUTABLE@", plist)

    def test_windows_native_calls_are_guarded_and_task_is_read_back(self):
        text = (ROOT / "install-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("function Invoke-Native", text)
        self.assertIn('$PyArgs = @("-3")', text)
        self.assertNotIn("-3.9", text)
        self.assertIn("Get-ScheduledTask", text)
        self.assertIn("Action.Arguments", text)
        self.assertIn("if ($Activate)", text)

    def test_upstream_downloader_rejects_non_linux_platform_before_network(self):
        script = ROOT / "scripts/install-upstream.py"
        result = subprocess.run([
            sys.executable, str(script), "--platform", "Windows", "--url", "https://example.invalid/a.zip",
            "--sha256", "0" * 64, "--output", str(ROOT / "dist/never-created.exe")
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"raw Linux binaries only", result.stderr)
        self.assertFalse((ROOT / "dist/never-created.exe").exists())


if __name__ == "__main__":
    unittest.main()
