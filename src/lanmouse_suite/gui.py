from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from .paths import native_paths


class ControlWindow:
    def __init__(self, root: tk.Tk, config_path: Optional[Path] = None) -> None:
        self.root = root
        self.config_path = config_path
        self.rows: Dict[str, Dict[str, Any]] = {}
        root.title("Lan Mouse Suite")
        root.geometry("620x410")
        root.minsize(520, 320)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Lan Mouse Suite", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        self.network = ttk.Label(frame, text="Checking network…")
        self.network.pack(anchor="w", pady=(4, 12))
        self.tree = ttk.Treeview(frame, columns=("state", "detail", "address"), show="headings", height=8)
        for column, title, width in (("state", "State", 80), ("detail", "Device", 250), ("address", "LAN address", 150)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Turn selected on", command=self.turn_selected_on).pack(side="left")
        ttk.Button(buttons, text="All off", command=lambda: self.run_cli(["all-off"])).pack(side="left", padx=8)
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(buttons, text="Open logs", command=self.open_logs).pack(side="right")
        self.footer = ttk.Label(frame, text="Emergency release: Control + Shift + Alt/Option + Command/Meta")
        self.footer.pack(anchor="w", pady=(12, 0))
        self.refresh()

    def command(self, args: List[str]) -> List[str]:
        command = [sys.executable, "-m", "lanmouse_suite.cli"]
        if self.config_path:
            command.extend(["--config", str(self.config_path)])
        return command + args

    def call_cli(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(self.command(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False, timeout=15)

    def run_cli(self, args: List[str]) -> None:
        result = self.call_cli(args)
        if result.returncode != 0:
            messagebox.showerror("Lan Mouse Suite", result.stderr.decode("utf-8", errors="replace") or "Command failed")
        self.refresh()

    def refresh(self) -> None:
        result = self.call_cli(["status", "--json"])
        if result.returncode != 0:
            self.network.configure(text="Status unavailable")
            self.root.after(4000, self.refresh)
            return
        try:
            status = json.loads(result.stdout.decode("utf-8"))
        except ValueError:
            self.network.configure(text="Invalid status response")
            self.root.after(4000, self.refresh)
            return
        suffix = " — manual OFF" if status.get("manual_off") else ""
        self.network.configure(text="Network: " + status.get("network", "Unknown") + suffix)
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.rows = {}
        for row in status.get("devices", []):
            state = "On" if row.get("on") else "Off"
            remote = row.get("remote_on")
            remote_text = "remote unknown" if remote is None else ("remote on" if remote else "remote off")
            self.tree.insert("", "end", iid=row["id"], values=(state, row.get("name") + " — " + row.get("detail", "") + "; " + remote_text, row.get("address") or ""))
            self.rows[row["id"]] = row
        if selected_id in self.rows:
            self.tree.selection_set(selected_id)
        self.root.after(4000, self.refresh)

    def turn_selected_on(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Lan Mouse Suite", "Select a peer first.")
            return
        self.run_cli(["on", selected[0]])

    def open_logs(self) -> None:
        path = native_paths().log_dir
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer.exe", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])


def main(argv: Optional[List[str]] = None) -> int:
    root = tk.Tk()
    ControlWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
