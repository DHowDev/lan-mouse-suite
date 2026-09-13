"""Local OBS-only mixer. No remote shell, routing, or recording operations."""
import math
import os


class MixerError(Exception):
    pass


def connect():
    # The endpoint is deliberately not configurable: never send OBS auth remotely.
    password = os.environ.get("LANBRIDGE_OBS_PASSWORD")
    if not password:
        raise MixerError("Setup needed: enable authenticated OBS WebSocket locally; set LANBRIDGE_OBS_PASSWORD in the app environment.")
    try:
        import obsws_python
        return obsws_python.ReqClient(host="127.0.0.1", port=4455, password=password, timeout=2)
    except Exception:
        raise MixerError("OBS unavailable: check local WebSocket authentication and optional obsws-python dependency.") from None


class Mixer:
    def __init__(self, client):
        self.client = client

    def discover(self):
        rows = []
        for item in self.client.get_input_list().inputs:
            name = item["inputName"]
            try:
                volume = self.client.get_input_volume(name).input_volume_mul
                muted = self.client.get_input_mute(name).input_muted
            except Exception:
                # Non-audio inputs are not faders. Never invent enabled controls.
                continue
            rows.append({"id": name, "label": name, "volume": volume, "muted": muted})
        return rows

    def set(self, source, volume=None, muted=None):
        if volume is not None and (type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 1):
            raise MixerError("Volume must be finite and between 0 and 1")
        if muted is not None and type(muted) is not bool:
            raise MixerError("Mute must be boolean")
        if not isinstance(source, str) or source not in {r["id"] for r in self.discover()}:
            raise MixerError("Source disappeared; refresh the mixer")
        if volume is not None:
            self.client.set_input_volume(source, vol_mul=volume)
        if muted is not None:
            self.client.set_input_mute(source, muted)
        actual_volume = self.client.get_input_volume(source).input_volume_mul
        actual_mute = self.client.get_input_mute(source).input_muted
        if volume is not None and not math.isclose(actual_volume, volume, abs_tol=0.001):
            raise MixerError("Volume read-back mismatch; refresh")
        if muted is not None and actual_mute != muted:
            raise MixerError("Mute read-back mismatch; refresh")
        return {"id": source, "volume": actual_volume, "muted": actual_mute}


def perform(source=None, volume=None, muted=None):
    client = connect()
    try:
        mixer = Mixer(client)
        return mixer.discover() if source is None else mixer.set(source, volume, muted)
    except MixerError:
        raise
    except Exception:
        raise MixerError("OBS request failed; refresh before retrying") from None
    finally:
        client.disconnect()
