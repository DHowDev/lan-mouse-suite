import unittest
from unittest.mock import Mock
from lanmouse_suite.mixer_cli import request
from lanmouse_suite.mixer import Mixer, MixerError

class NativeBridgeTests(unittest.TestCase):
    def test_read(self):
        mixer = Mock()
        mixer.discover.return_value = []
        self.assertEqual(request({"op": "read"}, mixer), [])
        mixer.set.assert_not_called()

    def test_strict_operations(self):
        for payload in ([], {}, {"op": "read", "password": "x"}, {"op": "set", "id": "x"}, {"op": "set", "id": "x", "volume": 1, "muted": True}):
            with self.assertRaises(ValueError):
                request(payload, Mock())

    def test_invalid_values_and_ids_never_write(self):
        client = Mock()
        client.get_input_list.return_value.inputs = []
        mixer = Mixer(client)
        for kwargs in ({"volume": float("nan")}, {"volume": -1}, {"volume": True}, {"muted": 1}, {"volume": 0.5}):
            with self.assertRaises(MixerError):
                request(dict(op="set", id="missing", **kwargs), mixer)
        client.set_input_volume.assert_not_called()
        client.set_input_mute.assert_not_called()
