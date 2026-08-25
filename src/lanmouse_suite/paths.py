from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SuitePaths:
    config_dir: Path
    state_dir: Path
    log_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def control_state(self) -> Path:
        return self.state_dir / "control.json"

    @property
    def guard_state(self) -> Path:
        return self.state_dir / "guard.json"

    @property
    def process_state(self) -> Path:
        return self.state_dir / "lan-mouse-process.json"

    @property
    def clipboard_state(self) -> Path:
        return self.state_dir / "clipboard.json"

    @property
    def control_lock(self) -> Path:
        return self.state_dir / "control.lock"

    @property
    def generated_toml(self) -> Path:
        return self.state_dir / "lan-mouse.generated.toml"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "lanmouse-suite.log"


def native_paths(system: Optional[str] = None, home: Optional[Path] = None) -> SuitePaths:
    name = system or platform.system()
    base_home = Path(home) if home is not None else Path.home()
    if name == "Darwin":
        support = base_home / "Library" / "Application Support" / "LanMouseSuite"
        return SuitePaths(support, support / "State", base_home / "Library" / "Logs" / "LanMouseSuite")
    if name == "Windows":
        roaming = Path(os.environ.get("APPDATA", str(base_home / "AppData" / "Roaming")))
        local = Path(os.environ.get("LOCALAPPDATA", str(base_home / "AppData" / "Local")))
        return SuitePaths(roaming / "LanMouseSuite", local / "LanMouseSuite" / "State", local / "LanMouseSuite" / "Logs")
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(base_home / ".config"))) / "lanmouse-suite"
    state = Path(os.environ.get("XDG_STATE_HOME", str(base_home / ".local" / "state"))) / "lanmouse-suite"
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(base_home / ".cache"))) / "lanmouse-suite"
    return SuitePaths(config, state, cache)
