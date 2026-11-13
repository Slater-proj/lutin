"""Outbound web guard (lutin.net_guard, lutin.web.web_telecharger): a page read by the model cannot make Lutin talk to the local network.

Reproduced during the audit, and now refused: the target of a redirection was contacted before being checked; the host name was resolved twice
(once to check it, once to connect), which a changing DNS answer exploits; the carrier-grade NAT range (Tailscale) was accepted."""
import http.server
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-net-guard-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_CONFIG": str(_TEMP / "config.json"),
                   "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ[key] = value
os.environ.pop("LUTIN_WEB_LOCAL", None)          # the guard is tested for real: no local test mode in this file
(_TEMP / "project").mkdir()

from lutin import moteur as A  # noqa: E402
from lutin import net_guard, web  # noqa: E402

RECEIVED = []          # every request that reached the « internal » service


class Internal(http.server.BaseHTTPRequestHandler):
    """A service of the local network: it must never be contacted, except through the one host the user allowed."""

    def log_message(self, *args):
        pass

    def _answer(self):
        RECEIVED.append((self.command, self.path, self.headers.get("X-Api-Key")))
        if self.path.startswith("/to-internal"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/admin/delete-everything" % PORT)
            self.end_headers()
        elif self.path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path.startswith("/next"):
            self.send_response(303 if self.command == "POST" else 302)
            self.send_header("Location", "/page")
            self.end_headers()
        else:
            body = b"INTERNAL-SECRET"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_GET = do_POST = _answer


SERVER = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Internal)
PORT = SERVER.server_address[1]
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
REAL_GETADDRINFO = socket.getaddrinfo


def setUpModule():
    """A developer machine behind a system proxy would take the unpinned path: these tests are about the pinned one."""
    patch = mock.patch.object(net_guard, "uses_proxy", lambda url: False)
    patch.start()
    unittest.addModuleCleanup(patch.stop)


def fake_dns(names):
    """A resolver where `names` (name -> list of addresses, consumed one call at a time, the last one repeated) answer what the test decides."""
    calls = []

    def getaddrinfo(host, port, *args, **kwargs):
        if host not in names:
            return REAL_GETADDRINFO(host, port, *args, **kwargs)
        calls.append(host)
        answers = names[host]
        address = answers[min(len(calls), len(answers)) - 1]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port or 0) if family == socket.AF_INET else (address, port or 0, 0, 0))]
    return mock.patch.object(socket, "getaddrinfo", getaddrinfo), calls


class Addresses(unittest.TestCase):
    def test_only_public_addresses_are_accepted(self):
        for address in ("127.0.0.1", "10.0.0.1", "192.168.1.10", "172.16.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "255.255.255.255",
                        "100.64.0.1", "100.100.100.100",                                   # carrier-grade NAT: where Tailscale machines live
                        "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:192.168.1.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2002:7f00:1::1", "2001:db8::1", "fe80::1%eth0"):
            self.assertTrue(net_guard.forbidden_address(address), address)
        for address in ("93.184.216.34", "1.1.1.1", "8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"):
            self.assertFalse(net_guard.forbidden_address(address), address)

    def test_a_name_with_one_internal_address_is_refused(self):
        patch, _ = fake_dns({"mixed.test": ["10.0.0.5"]})
        with patch, self.assertRaises(net_guard.ForbiddenAddress):
            net_guard.resolve_checked("mixed.test", 80)
        with self.assertRaises(net_guard.UnknownHost):
            net_guard.resolve_checked("no-such-host.invalid", 80)

    def test_the_test_switch_needs_both_variables(self):
        with mock.patch.dict(os.environ, {"LUTIN_WEB_LOCAL": "1", "LUTIN_TESTS": ""}):
            self.assertFalse(net_guard.local_test_mode(), "LUTIN_WEB_LOCAL alone (a shell profile, a compose file) no longer switches the guard off")
        with mock.patch.dict(os.environ, {"LUTIN_WEB_LOCAL": "1", "LUTIN_TESTS": "1"}):
            self.assertTrue(net_guard.local_test_mode())


class Pinning(unittest.TestCase):
    def setUp(self):
        RECEIVED.clear()

    def test_the_address_checked_is_the_address_connected(self):
        """Rebinding: the attacker's name ends up answering the loopback. There is no earlier check to fool: the connection resolves once and checks what it connects to."""
        patch, calls = fake_dns({"rebind.test": ["127.0.0.1"]})
        with patch, self.assertRaises(net_guard.ForbiddenAddress):
            net_guard.open_following("http://rebind.test:%d/secret" % PORT, check=lambda url: None)
        self.assertEqual(RECEIVED, [], "nothing was sent to the internal service")
        self.assertEqual(calls, ["rebind.test"], "one resolution: the one of the connection")

    def test_web_download_refuses_a_name_that_points_inside(self):
        patch, calls = fake_dns({"rebind.test": ["127.0.0.1"]})
        with patch, self.assertRaises(A.ErreurOutil) as caught:
            web.web_telecharger("http://rebind.test:%d/secret" % PORT)
        self.assertIn("rebind.test", str(caught.exception))
        self.assertEqual(RECEIVED, [])
        self.assertEqual(len(calls), 1)

    def test_the_host_the_user_configured_is_reached_and_resolved_once(self):
        patch, calls = fake_dns({"searx.test": ["127.0.0.1"]})
        with patch:
            final, kind, text = web.web_telecharger("http://searx.test:%d/page" % PORT, hote_autorise="searx.test")
        self.assertEqual((kind, text), ("text/plain", "INTERNAL-SECRET"))
        self.assertEqual(calls, ["searx.test"])


class Redirections(unittest.TestCase):
    def setUp(self):
        RECEIVED.clear()

    def test_a_redirection_towards_the_local_network_is_refused_before_any_request(self):
        """The audit's reproduction: the first host is legitimate (here the allowed one), it redirects to an internal address."""
        patch, _ = fake_dns({"searx.test": ["127.0.0.1"]})
        with patch, self.assertRaises(A.ErreurOutil) as caught:
            web.web_telecharger("http://searx.test:%d/to-internal" % PORT, hote_autorise="searx.test")
        self.assertIn("127.0.0.1", str(caught.exception))
        self.assertEqual([path for _, path, _ in RECEIVED], ["/to-internal"], "the internal target received nothing")

    def test_every_hop_is_checked_before_it_is_requested(self):
        seen = []

        def check(url):
            seen.append((url.rsplit("/", 1)[-1], len(RECEIVED)))

        with net_guard.open_following("http://127.0.0.1:%d/next" % PORT, check=check, pinned=False) as response:
            self.assertEqual(response.read(), b"INTERNAL-SECRET")
            self.assertTrue(response.geturl().endswith("/page"))
        self.assertEqual(seen, [("next", 0), ("page", 1)], "the check of a hop comes before its request")

    def test_a_post_becomes_a_get_and_private_headers_stay_with_the_first_host(self):
        patch, _ = fake_dns({"api.test": ["127.0.0.1"]})
        with patch:
            with net_guard.open_following("http://api.test:%d/next" % PORT, check=lambda url: None, data=b"q=1", private_headers={"X-Api-Key": "secret"}, pinned=False):
                pass
            self.assertEqual(RECEIVED, [("POST", "/next", "secret"), ("GET", "/page", "secret")], "same host: the key follows")
            RECEIVED.clear()
            with self.assertRaises(RuntimeError):
                net_guard.open_following("http://api.test:%d/to-internal" % PORT, private_headers={"X-Api-Key": "secret"}, pinned=False,
                                         check=lambda url: (_ for _ in ()).throw(RuntimeError(url)) if "127.0.0.1" in url else None)
            self.assertEqual(RECEIVED, [("GET", "/to-internal", "secret")])
            RECEIVED.clear()
            with net_guard.open_following("http://api.test:%d/to-internal" % PORT, check=lambda url: None, private_headers={"X-Api-Key": "secret"}, pinned=False):
                pass
            self.assertEqual(RECEIVED[-1], ("GET", "/admin/delete-everything", None), "another host never receives the key")

    def test_endless_redirections_stop(self):
        with self.assertRaises(net_guard.TooManyRedirections):
            net_guard.open_following("http://127.0.0.1:%d/loop" % PORT, check=lambda url: None, pinned=False)
        self.assertEqual(len(RECEIVED), net_guard.MAX_REDIRECTIONS + 1)

    def test_other_schemes_are_refused_by_the_web_check(self):
        for url in ("file:///etc/passwd", "ftp://example.org/x", "gopher://example.org/", "http:///nohost"):
            with self.assertRaises(A.ErreurOutil, msg=url):
                web.web_telecharger(url)


if __name__ == "__main__":
    unittest.main()
