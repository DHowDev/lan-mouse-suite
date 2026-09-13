import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from lanmouse_suite.mixer import Mixer, MixerError, connect


class FakeOBS:
    def __init__(self):
        self.volume = 0.5
        self.muted = False
        self.writes = []
    def get_input_list(self):
        return NS(inputs=[{"inputName": "Titan Audio UDP5012"}])
    def get_input_volume(self, name):
        return NS(input_volume_mul=self.volume)
    def get_input_mute(self, name):
        return NS(input_muted=self.muted)
    def set_input_volume(self, name, vol_mul):
        self.writes.append(name)
        self.volume = vol_mul
    def set_input_mute(self, name, muted):
        self.writes.append(name)
        self.muted = muted


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.obs = FakeOBS()
        self.mixer = Mixer(self.obs)
    def test_discovery_preserves_owned_label(self):
        self.assertEqual(self.mixer.discover()[0]["label"], "Titan Audio UDP5012")
    def test_gain_mute_and_readback(self):
        row = self.mixer.set("Titan Audio UDP5012", 0.25, True)
        self.assertEqual(row["volume"], 0.25)
        self.assertTrue(row["muted"])
    def test_invalid_gain_never_writes(self):
        for value in [-1, 2, float("nan"), float("inf"), True, "0.5"]:
            with self.assertRaises(MixerError):
                self.mixer.set("Titan Audio UDP5012", value)
        self.assertEqual(self.obs.writes, [])
    def test_unknown_source_and_invalid_mute(self):
        for source, muted in [("$(touch /tmp/no)", True), ("Titan Audio UDP5012", 1)]:
            with self.assertRaises(MixerError):
                self.mixer.set(source, muted=muted)
        self.assertEqual(self.obs.writes, [])
    def test_readback_mismatch(self):
        with patch.object(self.obs, "set_input_mute"):
            with self.assertRaises(MixerError):
                self.mixer.set("Titan Audio UDP5012", muted=True)
    def test_setup_fails_closed_idempotently(self):
        with patch.dict(os.environ, {}, clear=True):
            for _ in range(2):
                with self.assertRaises(MixerError):
                    connect()
    def test_non_audio_not_discovered(self):
        with patch.object(self.obs, "get_input_volume", side_effect=RuntimeError):
            self.assertEqual(self.mixer.discover(), [])
