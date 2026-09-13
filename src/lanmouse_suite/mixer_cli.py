"""Native mixer JSON bridge; credentials are inherited, never arguments."""
import contextlib
import json
import logging
import sys
from .mixer import Mixer, connect


def request(payload, mixer):
    if not isinstance(payload, dict):
        raise ValueError("object required")
    op = payload.get("op")
    if op == "read" and set(payload) == {"op"}:
        return mixer.discover()
    if op != "set" or set(payload) not in ({"op", "id", "volume"}, {"op", "id", "muted"}):
        raise ValueError("invalid operation")
    mixer.set(payload["id"], **{k: payload[k] for k in ("volume", "muted") if k in payload})
    return mixer.discover()


def main():
    logging.disable(logging.CRITICAL)
    try:
        payload = json.loads(sys.stdin.read(65537))
        # Third-party diagnostics must never leak credentials or corrupt JSON.
        import os
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rows = request(payload, Mixer(connect()))
        result = {"ok": True, "sources": rows}
    except Exception:
        result = {"ok": False, "sources": [], "error": "OBS offline or request rejected. Enable authenticated OBS WebSocket on loopback port 4455 and launch with the hidden password prompt."}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
