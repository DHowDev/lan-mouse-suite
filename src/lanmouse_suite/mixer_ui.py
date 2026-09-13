"""Mixer embedded in the existing suite control window, not a separate app."""
import queue
import threading
from tkinter import ttk

from .mixer import perform


class MixerPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="LANBRIDGE · Mac OBS / Titan stream")
        self.pack(fill="x", pady=8)
        self.results = queue.Queue()
        self.pending = False
        self.status = ttk.Label(self, text="Not connected. Refresh to discover actual OBS audio sources.")
        self.status.pack(anchor="w")
        ttk.Label(self, text="Existing Titan UDP 5012 → Mac OBS monitoring stays authoritative. No routing changes.").pack(anchor="w")
        ttk.Label(self, text="Setup: OBS → Tools → WebSocket Server Settings. Enable server and authentication,\nuse port 4455, then set LANBRIDGE_OBS_PASSWORD before launching this app.\nIf the server is disabled, enable it manually; this panel never edits OBS settings or restarts OBS.", wraplength=640).pack(anchor="w")
        self.refresh_button = ttk.Button(self, text="Refresh OBS sources", command=self.refresh)
        self.refresh_button.pack(anchor="w")
        self.rows = ttk.Frame(self)
        self.rows.pack(fill="x")
        self.after(100, self.poll)

    def refresh(self):
        self.run()

    def run(self, **kwargs):
        if self.pending:
            return
        self.pending = True
        self.refresh_button.configure(state="disabled")
        for widget in self.rows.winfo_children():
            widget.destroy()
        self.status.configure(text="Checking local OBS…")
        def worker():
            try:
                if kwargs:
                    perform(**kwargs)
                self.results.put((perform(), None))
            except Exception:
                self.results.put(([], "Setup/check needed: local OBS WebSocket :4455, LANBRIDGE_OBS_PASSWORD and obsws-python. No controls enabled."))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            rows, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.pending = False
            self.refresh_button.configure(state="normal")
            self.status.configure(text=error or ("Connected · OBS source faders, not Titan per-app controls" if rows else "Connected · no controllable audio sources"))
            for row in rows:
                line = ttk.Frame(self.rows)
                line.pack(fill="x")
                ttk.Label(line, text=row["label"]).pack(side="left")
                slider = ttk.Scale(line, from_=0, to=1)
                slider.set(min(1, max(0, row["volume"])))
                slider.pack(side="left", fill="x", expand=True)
                ttk.Button(line, text="Apply volume", command=lambda r=row, s=slider: self.run(source=r["id"], volume=s.get())).pack(side="left")
                ttk.Button(line, text="Unmute" if row["muted"] else "Mute", command=lambda r=row: self.run(source=r["id"], muted=not r["muted"])).pack(side="left")
        self.after(100, self.poll)
