from __future__ import annotations

import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .models import CommandResult, NetworkSnapshot


def normalize_mac(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    compact = "".join(ch for ch in value.lower() if ch in "0123456789abcdef")
    if len(compact) != 12:
        return None
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


class CommandRunner:
    def run(self, argv: Sequence[str], data: Optional[bytes] = None, timeout: float = 8.0) -> CommandResult:
        args = [str(item) for item in argv]
        try:
            result = subprocess.run(
                args,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                shell=False,
            )
            return CommandResult(args, result.returncode, result.stdout, result.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(args, 127, b"", str(exc).encode("utf-8", errors="replace"))

    def run_bounded(
        self, argv: Sequence[str], max_bytes: int, data: Optional[bytes] = None, timeout: float = 8.0
    ) -> CommandResult:
        """Capture no more than max_bytes+1 stdout bytes and kill overflow."""
        args = [str(item) for item in argv]
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError as exc:
            return CommandResult(args, 127, b"", str(exc).encode("utf-8", errors="replace"))
        if data is not None and process.stdin is not None:
            try:
                process.stdin.write(data)
                process.stdin.close()
            except OSError:
                pass
        capacity = max_bytes + 1
        payload = bytearray(capacity)
        result: Dict[str, Any] = {"count": 0, "error": None}

        def reader() -> None:
            try:
                assert process.stdout is not None
                view = memoryview(payload)
                while result["count"] < capacity:
                    count = process.stdout.readinto(view[result["count"] : capacity])
                    if not count:
                        break
                    result["count"] += count
                    if result["count"] >= capacity:
                        try:
                            process.terminate()
                        except OSError:
                            pass
                        break
            except (OSError, ValueError) as exc:
                result["error"] = exc

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)
        timed_out = thread.is_alive()
        if timed_out:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            returncode = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=2)
        thread.join(2)
        count = int(result["count"])
        stdout = bytes(memoryview(payload)[:count])
        if process.stdout is not None:
            process.stdout.close()
        if timed_out:
            return CommandResult(args, 124, stdout, b"command timed out")
        if count > max_bytes:
            return CommandResult(args, 125, stdout, b"stdout exceeded configured limit")
        if result["error"] is not None:
            return CommandResult(args, 127, stdout, str(result["error"]).encode("utf-8", errors="replace"))
        return CommandResult(args, returncode, stdout, b"")


class PlatformAdapter(ABC):
    platform_name = ""

    def __init__(self, runner: Optional[CommandRunner] = None) -> None:
        self.runner = runner or CommandRunner()

    @abstractmethod
    def clipboard_read_command(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def clipboard_write_command(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def network_snapshot(self) -> NetworkSnapshot:
        raise NotImplementedError

    def process_identity(self, pid: int) -> Optional[Dict[str, Any]]:
        return None

    @abstractmethod
    def terminate_process(self, pid: int) -> bool:
        raise NotImplementedError

    def read_clipboard(self, max_bytes: int) -> Optional[bytes]:
        result = self.runner.run_bounded(self.clipboard_read_command(), max_bytes, timeout=3)
        if result.returncode != 0:
            return None
        try:
            result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        return result.stdout

    def write_clipboard(self, data: bytes, max_bytes: int) -> bool:
        if len(data) > max_bytes:
            return False
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
        return self.runner.run(self.clipboard_write_command(), data=data, timeout=3).returncode == 0

    def image_clipboard_read_command(self) -> Optional[List[str]]:
        return None

    def image_clipboard_write_command(self) -> Optional[List[str]]:
        return None

    def read_image_clipboard(self, max_bytes: int) -> Optional[bytes]:
        command = self.image_clipboard_read_command()
        if command is None:
            return None
        result = self.runner.run_bounded(command, max_bytes, timeout=5)
        return result.stdout if result.returncode == 0 and result.stdout else None

    def write_image_clipboard(self, data: bytes, max_bytes: int) -> bool:
        command = self.image_clipboard_write_command()
        if command is None or not data or len(data) > max_bytes:
            return False
        return self.runner.run(command, data=data, timeout=5).returncode == 0

    def resolve_ipv4(self, hostname: str) -> List[str]:
        found = []
        try:
            entries = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        except socket.gaierror:
            return []
        for entry in entries:
            value = entry[4][0]
            if value not in found:
                found.append(value)
        return found

    def child_environment(self) -> Dict[str, str]:
        return dict(os.environ)

    def graphical_environment_ready(self) -> bool:
        return True

    def wait_graphical_environment(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.graphical_environment_ready():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def process_matches(self, pid: int, expected: Dict[str, Any]) -> bool:
        if pid <= 0 or not isinstance(expected, dict):
            return False
        live = self.process_identity(pid)
        if not live:
            return False
        executable = expected.get("executable")
        argv = expected.get("argv")
        creation_id = expected.get("creation_id")
        config_path = expected.get("config_path")
        if not all(isinstance(value, str) and value for value in (executable, creation_id, config_path)):
            return False
        if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
            return False
        try:
            live_executable = str(Path(str(live.get("executable"))).resolve(strict=True))
            expected_executable = str(Path(executable).resolve(strict=True))
            expected_config = str(Path(config_path).resolve(strict=True))
        except (OSError, RuntimeError):
            return False
        live_argv = live.get("argv")
        if live_executable != expected_executable or live.get("creation_id") != creation_id or live_argv != argv:
            return False
        config_indexes = [index for index, value in enumerate(live_argv) if value == "--config"]
        if len(config_indexes) != 1 or config_indexes[0] + 1 >= len(live_argv):
            return False
        try:
            live_config = str(Path(live_argv[config_indexes[0] + 1]).resolve(strict=True))
        except (OSError, RuntimeError):
            return False
        return live_config == expected_config

    def wait_for_exit(self, pid: int, creation_id: str, timeout: float = 8.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            identity = self.process_identity(pid)
            if identity is None or identity.get("creation_id") != creation_id:
                return True
            time.sleep(0.05)
        identity = self.process_identity(pid)
        return identity is None or identity.get("creation_id") != creation_id


class MacOSAdapter(PlatformAdapter):
    platform_name = "Darwin"

    def __init__(self, runner: Optional[CommandRunner] = None, utf8_locale: str = "en_US.UTF-8") -> None:
        super().__init__(runner)
        self.utf8_locale = utf8_locale

    def _utf8_clipboard_command(self, executable: str) -> List[str]:
        # pbcopy/pbpaste fall back to MacRoman when launchd provides no locale.
        # Pass both variables explicitly so every CLI and service path is UTF-8.
        return [
            "/usr/bin/env",
            "LANG=" + self.utf8_locale,
            "LC_ALL=" + self.utf8_locale,
            executable,
        ]

    def clipboard_read_command(self) -> List[str]:
        return self._utf8_clipboard_command("/usr/bin/pbpaste")

    def clipboard_write_command(self) -> List[str]:
        return self._utf8_clipboard_command("/usr/bin/pbcopy")

    def image_clipboard_read_command(self) -> Optional[List[str]]:
        return ["/usr/bin/osascript", "-e", "get (the clipboard as «class PNGf»)"]

    def network_snapshot(self) -> NetworkSnapshot:
        route = self.runner.run(["/sbin/route", "-n", "get", "default"], timeout=4)
        interface = None
        gateway = None
        for raw in route.stdout.decode("utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("interface:"):
                interface = line.split(":", 1)[1].strip()
            elif line.startswith("gateway:"):
                gateway = line.split(":", 1)[1].strip()
        address = None
        ssid = None
        gateway_mac = None
        if interface:
            value = self.runner.run(["/usr/sbin/ipconfig", "getifaddr", interface], timeout=3)
            if value.returncode == 0:
                address = value.stdout.decode("utf-8", errors="replace").strip() or None
            wifi = self.runner.run(["/usr/sbin/networksetup", "-getairportnetwork", interface], timeout=3)
            wifi_text = wifi.stdout.decode("utf-8", errors="replace").strip()
            if wifi.returncode == 0 and ": " in wifi_text and "not associated" not in wifi_text.lower():
                ssid = wifi_text.split(": ", 1)[1] or None
        if gateway:
            arp = self.runner.run(["/usr/sbin/arp", "-n", gateway], timeout=3)
            words = arp.stdout.decode("utf-8", errors="replace").replace("(", " ").replace(")", " ").split()
            if "at" in words:
                index = words.index("at")
                if index + 1 < len(words):
                    gateway_mac = normalize_mac(words[index + 1])
        return NetworkSnapshot(address, gateway, interface, ssid, gateway_mac)

    def process_identity(self, pid: int) -> Optional[Dict[str, Any]]:
        if pid <= 0 or sys.platform != "darwin":
            return None
        try:
            import ctypes
            import struct

            # KERN_PROCARGS2 returns argc followed by the executable path and
            # the original NUL-delimited argv. Unlike `ps command=`, this
            # preserves argument boundaries and paths containing spaces.
            libc = ctypes.CDLL(None, use_errno=True)
            mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
            size = ctypes.c_size_t(0)
            if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value < 8:
                return None
            buffer = ctypes.create_string_buffer(size.value)
            if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
                return None
            raw = buffer.raw[: size.value]
            argc = struct.unpack_from("=i", raw, 0)[0]
            if argc <= 0 or argc > 65536:
                return None
            offset = 4
            executable_end = raw.find(b"\0", offset)
            if executable_end < 0:
                return None
            proc_path = ctypes.create_string_buffer(4096)
            length = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pidpath(pid, proc_path, len(proc_path))
            if length <= 0:
                return None
            executable = str(Path(proc_path.value.decode("utf-8", errors="strict")).resolve(strict=True))
            offset = executable_end + 1
            while offset < len(raw) and raw[offset] == 0:
                offset += 1
            argv = []
            for _ in range(argc):
                end = raw.find(b"\0", offset)
                if end < 0:
                    return None
                argv.append(raw[offset:end].decode("utf-8", errors="strict"))
                offset = end + 1
            created = self.runner.run(["/bin/ps", "-p", str(pid), "-o", "lstart="], timeout=3)
            if created.returncode != 0:
                return None
            creation_id = created.stdout.decode("utf-8", errors="strict").strip()
        except (ValueError, UnicodeError, OSError, RuntimeError, struct.error):
            return None
        if not creation_id or not argv:
            return None
        return {"executable": executable, "creation_id": creation_id, "argv": argv}

    def terminate_process(self, pid: int) -> bool:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


class LinuxAdapter(PlatformAdapter):
    platform_name = "Linux"

    def clipboard_read_command(self) -> List[str]:
        return ["wl-paste", "--type", "text/plain", "--no-newline"]

    def clipboard_write_command(self) -> List[str]:
        return ["wl-copy", "--type", "text/plain"]

    def network_snapshot(self) -> NetworkSnapshot:
        route_result = self.runner.run(["ip", "-j", "route", "show", "default"], timeout=4)
        try:
            routes = json.loads(route_result.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            routes = []
        route = routes[0] if isinstance(routes, list) and routes else {}
        interface = route.get("dev") if isinstance(route, dict) else None
        gateway = route.get("gateway") if isinstance(route, dict) else None
        address = None
        gateway_mac = None
        ssid = None
        if interface:
            addr_result = self.runner.run(["ip", "-j", "addr", "show", "dev", str(interface)], timeout=4)
            try:
                interfaces = json.loads(addr_result.stdout.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                interfaces = []
            for item in interfaces if isinstance(interfaces, list) else []:
                for info in item.get("addr_info", []):
                    if info.get("family") == "inet" and info.get("scope") == "global":
                        address = info.get("local")
                        break
                if address:
                    break
            if gateway:
                neigh = self.runner.run(["ip", "-j", "neigh", "show", "to", str(gateway), "dev", str(interface)], timeout=3)
                try:
                    rows = json.loads(neigh.stdout.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    rows = []
                if isinstance(rows, list) and rows:
                    gateway_mac = normalize_mac(rows[0].get("lladdr"))
            wifi = self.runner.run(["iw", "dev", str(interface), "link"], timeout=3)
            for line in wifi.stdout.decode("utf-8", errors="replace").splitlines():
                if line.strip().startswith("SSID:"):
                    ssid = line.split(":", 1)[1].strip() or None
                    break
        return NetworkSnapshot(address, gateway, interface, ssid, gateway_mac)

    def process_identity(self, pid: int) -> Optional[Dict[str, Any]]:
        if pid <= 0:
            return None
        root = Path("/proc") / str(pid)
        try:
            executable = str((root / "exe").resolve(strict=True))
            raw_argv = (root / "cmdline").read_bytes()
            stat_fields = (root / "stat").read_text(encoding="utf-8").split()
            creation_id = stat_fields[21]
            argv = [item.decode("utf-8", errors="strict") for item in raw_argv.rstrip(b"\0").split(b"\0")]
        except (OSError, UnicodeError, IndexError, RuntimeError):
            return None
        if not argv:
            return None
        return {"executable": executable, "creation_id": creation_id, "argv": argv}

    def terminate_process(self, pid: int) -> bool:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False

    def child_environment(self) -> Dict[str, str]:
        environment = dict(os.environ)
        runtime = Path(environment.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
        environment["XDG_RUNTIME_DIR"] = str(runtime)
        if not environment.get("WAYLAND_DISPLAY") and runtime.is_dir():
            for candidate in sorted(runtime.glob("wayland-*")):
                try:
                    if candidate.is_socket():
                        environment["WAYLAND_DISPLAY"] = candidate.name
                        break
                except OSError:
                    continue
        environment.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=%s" % (runtime / "bus"))
        return environment

    def graphical_environment_ready(self) -> bool:
        environment = self.child_environment()
        runtime = Path(environment.get("XDG_RUNTIME_DIR", ""))
        display = environment.get("WAYLAND_DISPLAY")
        bus = runtime / "bus"
        if not runtime.is_dir() or not display or not bus.exists():
            return False
        display_path = Path(display) if Path(display).is_absolute() else runtime / display
        try:
            return stat.S_ISSOCK(display_path.stat().st_mode)
        except OSError:
            return False


class WindowsAdapter(PlatformAdapter):
    platform_name = "Windows"
    POWERSHELL = "powershell.exe"

    def clipboard_read_command(self) -> List[str]:
        return [self.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw -Format Text"]

    def clipboard_write_command(self) -> List[str]:
        return [self.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "$v=[Console]::In.ReadToEnd(); Set-Clipboard -Value $v"]

    def network_snapshot(self) -> NetworkSnapshot:
        script = (
            "$r=Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1;"
            "if($null -eq $r){exit 1};"
            "$a=Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $r.InterfaceIndex | Where-Object {$_.AddressState -eq 'Preferred'} | Select-Object -First 1;"
            "$n=Get-NetNeighbor -AddressFamily IPv4 -InterfaceIndex $r.InterfaceIndex -IPAddress $r.NextHop -ErrorAction SilentlyContinue | Select-Object -First 1;"
            "[pscustomobject]@{address=$a.IPAddress;gateway=$r.NextHop;interface=$r.InterfaceAlias;gateway_mac=$n.LinkLayerAddress}|ConvertTo-Json -Compress"
        )
        result = self.runner.run([self.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script], timeout=6)
        try:
            value = json.loads(result.stdout.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            value = {}
        wifi = self.runner.run(["netsh.exe", "wlan", "show", "interfaces"], timeout=4)
        ssid = None
        for line in wifi.stdout.decode("utf-8", errors="replace").splitlines():
            key, separator, val = line.partition(":")
            if separator and key.strip().lower() == "ssid":
                ssid = val.strip() or None
                break
        return NetworkSnapshot(value.get("address"), value.get("gateway"), value.get("interface"), ssid, normalize_mac(value.get("gateway_mac")))

    def _split_commandline(self, value: str) -> Optional[List[str]]:
        if os.name != "nt" or not value or "\x00" in value:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            count = ctypes.c_int()
            parser = ctypes.windll.shell32.CommandLineToArgvW
            parser.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            parser.restype = ctypes.POINTER(wintypes.LPWSTR)
            pointer = parser(value, ctypes.byref(count))
            if not pointer:
                return None
            try:
                return [pointer[index] for index in range(count.value)]
            finally:
                ctypes.windll.kernel32.LocalFree(pointer)
        except (AttributeError, OSError, ValueError):
            return None

    def process_identity(self, pid: int) -> Optional[Dict[str, Any]]:
        script = (
            "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\";"
            "if($null -eq $p){exit 3};"
            "[pscustomobject]@{executable=$p.ExecutablePath;created=$p.CreationDate;command=$p.CommandLine}|ConvertTo-Json -Compress" % pid
        )
        result = self.runner.run([self.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script], timeout=5)
        if result.returncode != 0:
            return None
        try:
            value = json.loads(result.stdout.decode("utf-8-sig"))
            executable = str(Path(value["executable"]).resolve(strict=True))
            creation_id = str(value["created"])
            argv = self._split_commandline(value["command"])
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, UnicodeDecodeError):
            return None
        if not creation_id or not argv:
            return None
        return {"executable": executable, "creation_id": creation_id, "argv": argv}

    def terminate_process(self, pid: int) -> bool:
        script = "Stop-Process -Id %d -ErrorAction Stop" % pid
        return self.runner.run([self.POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script], timeout=5).returncode == 0


def get_adapter(
    system: Optional[str] = None,
    runner: Optional[CommandRunner] = None,
    utf8_locale: str = "en_US.UTF-8",
) -> PlatformAdapter:
    import platform

    name = system or platform.system()
    if name == "Darwin":
        return MacOSAdapter(runner, utf8_locale=utf8_locale)
    if name == "Windows":
        return WindowsAdapter(runner)
    if name == "Linux":
        return LinuxAdapter(runner)
    raise RuntimeError("unsupported platform: " + name)
