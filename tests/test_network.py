import unittest
from unittest.mock import patch

from lanmouse_suite.adapters import PlatformAdapter
from lanmouse_suite.models import NetworkSnapshot, ResolvedPeer
from lanmouse_suite.network import match_trusted_network, probe_peer, resolve_peer


class ResolveAdapter(PlatformAdapter):
    def __init__(self, resolved): self.resolved = resolved
    def clipboard_read_command(self): return []
    def clipboard_write_command(self): return []
    def network_snapshot(self): return NetworkSnapshot(None, None, None)
    def terminate_process(self, pid): return False
    def resolve_ipv4(self, hostname): return list(self.resolved)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [{
            "id": "home", "name": "Home", "cidr": "192.168.50.0/24",
            "gateway": "192.168.50.1", "interface": "eth0", "peers": ["desk"],
            "allow_tailscale": False,
        }]

    def test_exact_cidr_gateway_and_interface_match(self):
        trusted = match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0"), self.profiles)
        self.assertIsNotNone(trusted)
        self.assertEqual(trusted.profile_id, "home")

    def test_ssid_and_gateway_mac_are_exact_and_fail_closed(self):
        profile = dict(self.profiles[0], ssid="Private LAN", gateway_mac="aa:bb:cc:dd:ee:ff")
        good = NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0", "Private LAN", "AA-BB-CC-DD-EE-FF")
        self.assertIsNotNone(match_trusted_network(good, [profile]))
        self.assertIsNone(match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0", None, "aa:bb:cc:dd:ee:ff"), [profile]))
        self.assertIsNone(match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0", "Private LAN", None), [profile]))
        self.assertIsNone(match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0", "Other", "aa:bb:cc:dd:ee:ff"), [profile]))

    def test_wrong_gateway_or_interface_rejected(self):
        self.assertIsNone(match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.254", "eth0"), self.profiles))
        self.assertIsNone(match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "tailscale0"), self.profiles))

    def test_resolution_requires_in_network_ipv4(self):
        trusted = match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0"), self.profiles)
        peer = {"id": "desk", "name": "Desk", "mdns": "desk.local", "addresses": ["192.168.50.20"], "tailscale_addresses": ["100.64.0.2"], "position": "right", "port": 4242}
        resolved = resolve_peer(peer, trusted, self.profiles[0], ResolveAdapter(["100.64.0.2"]))
        self.assertEqual(resolved.address, "192.168.50.20")

    def test_tailscale_fallback_is_not_used_without_opt_in(self):
        trusted = match_trusted_network(NetworkSnapshot("192.168.50.9", "192.168.50.1", "eth0"), self.profiles)
        peer = {"id": "desk", "addresses": [], "tailscale_addresses": ["100.64.0.2"], "position": "right", "port": 4242}
        self.assertIsNone(resolve_peer(peer, trusted, self.profiles[0], ResolveAdapter([])))

    def test_readiness_uses_management_port_not_lan_mouse_udp_port(self):
        peer = ResolvedPeer("desk", "Desk", "192.168.50.20", 4242, "right")
        with patch("lanmouse_suite.network.socket.create_connection") as connect:
            connect.return_value.close.return_value = None
            self.assertTrue(probe_peer(peer, probe_port=22))
            connect.assert_called_once_with(("192.168.50.20", 22), timeout=1.5)


if __name__ == "__main__":
    unittest.main()
