"""Le relais de réveil (Docker bridge) : refuse sans secret, envoie avec."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import context  # noqa: F401
from lutin import moteur  # noqa: F401,E402
from lutin import relais_reveil


class Relais(unittest.TestCase):
    def setUp(self):
        self.recus = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), relais_reveil.fabriquer("secret-de-seize-car", lambda mac, hote: self.recus.append((mac, hote)) or [("x", 9)]))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_avec_le_secret(self):
        env = {"LUTIN_WAKE_RELAY": self.url, "LUTIN_WAKE_TOKEN": "secret-de-seize-car"}
        with mock.patch.dict("os.environ", env):
            self.assertEqual(relais_reveil.via_relais("00:1A:2B:3C:4D:5E", "192.168.1.20"), 1)
        self.assertEqual(self.recus, [("00:1A:2B:3C:4D:5E", "192.168.1.20")])

    def test_mauvais_secret_refuse(self):
        env = {"LUTIN_WAKE_RELAY": self.url, "LUTIN_WAKE_TOKEN": "mauvais"}
        with mock.patch.dict("os.environ", env), self.assertRaises(ValueError):
            relais_reveil.via_relais("00:1A:2B:3C:4D:5E")
        self.assertEqual(self.recus, [])

    def test_sans_relais_configure(self):
        with mock.patch.dict("os.environ", {"LUTIN_WAKE_RELAY": ""}):
            self.assertIsNone(relais_reveil.via_relais("00:1A:2B:3C:4D:5E"))

    def test_secret_trop_court(self):
        with self.assertRaises(ValueError):
            relais_reveil.servir(token="court")

    def test_mauvaise_adresse_mac(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), relais_reveil.fabriquer("secret-de-seize-car"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        req = urllib.request.Request("http://127.0.0.1:%d/wake" % srv.server_address[1], data=json.dumps({"mac": "zz"}).encode(), method="POST", headers={"X-Token": "secret-de-seize-car"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 400)
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
