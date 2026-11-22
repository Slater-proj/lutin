"""`/api/v1/web-search` (docs/modernization/PARITY.md, item 8): the engines tried in order, SearXNG, the personal keys and « test the search », on
the real server of tests/test_api_v1.py.

Hermetic: recherche.json lives in the temporary data folder of test_api_v1, and the test of the engines is `core.tester_moteurs_recherche` replaced:
nothing reaches the network."""
import json
import os
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import web_search

A = V.A


def setUpModule():
    V.setUpModule()


class WebSearch(unittest.TestCase):
    def setUp(self):
        path = A.DATA / "recherche.json"
        path.unlink(missing_ok=True)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

    def test_the_engines_are_listed_in_the_order_they_are_tried(self):
        status, answer = V.call("GET", "/api/v1/web-search", V.OWNER)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["searxng"], "")
        self.assertEqual([k["provider"] for k in answer["keys"]], ["brave", "tavily", "exa", "perplexity"])
        self.assertFalse(any(k["kept"] for k in answer["keys"]))
        self.assertTrue(answer["can_configure"])
        self.assertFalse(V.call("GET", "/api/v1/web-search", V.DEVICE)[1]["can_configure"])

    def test_searxng_and_a_key_are_kept_and_the_key_never_sent_back(self):
        with mock.patch.dict(os.environ, {"LUTIN_RECHERCHE_URL": ""}):
            status, answer = V.call("PATCH", "/api/v1/web-search", V.OWNER, {"searxng": "127.0.0.1:8080", "keys": {"brave": "abcdefghij-1234"}})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["searxng"], "http://127.0.0.1:8080")
        self.assertEqual(answer["keys"][0], {"provider": "brave", "kept": True, "ends_with": "1234"})
        self.assertNotIn("abcdefghij", json.dumps(answer))
        self.assertEqual(web_search.config()["brave_cle"], "abcdefghij-1234")
        self.assertEqual([(e["id"], e["configured"], e["at_home"]) for e in answer["engines"]][:2], [("searxng", True, True), ("brave", True, False)],
                         "the ones set up are tried first; only a SearXNG of the local network keeps the query at home")
        status, answer = V.call("PATCH", "/api/v1/web-search", V.OWNER, {"keys": {"brave": ""}})
        self.assertEqual((status, answer["keys"][0]["kept"], answer["searxng"]), (200, False, "http://127.0.0.1:8080"), "a key removed, the rest untouched")

    def test_what_cannot_be_an_address_or_a_key_is_refused(self):
        for body in ({"searxng": "ftp://example.org"}, {"keys": {"brave": "short"}}, {"keys": {"google": "abcdefghijkl"}}, {"keys": ["brave"]}):
            status, answer = V.call("PATCH", "/api/v1/web-search", V.OWNER, body)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), body)
        self.assertEqual(web_search.config()["searxng"], "")

    def test_only_this_machine_changes_them(self):
        status, _ = V.call("PATCH", "/api/v1/web-search", V.DEVICE, {"searxng": "http://127.0.0.1:8080"})
        self.assertEqual(status, 403)
        self.assertEqual(web_search.config()["searxng"], "")

    def test_the_test_asks_each_engine_and_is_refused_offline(self):
        status, answer = V.call("POST", "/api/v1/web-search/test", V.DEVICE, {})
        self.assertEqual((status, answer["error"]["code"]), (409, "offline"), "test_api_v1 runs in strict offline mode")
        tried = [{"nom": "duckduckgo", "ok": True, "nombre": 7, "ms": 120, "erreur": "", "exemple": "A title"},
                 {"nom": "bing", "ok": False, "nombre": 0, "ms": 40000, "erreur": "pas de réponse à temps", "exemple": ""}]
        with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": ""}), mock.patch.object(A, "tester_moteurs_recherche", lambda: tried):
            status, answer = V.call("POST", "/api/v1/web-search/test", V.DEVICE, {})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["results"], [{"id": "duckduckgo", "ok": True, "count": 7, "ms": 120, "error": "", "example": "A title"},
                                             {"id": "bing", "ok": False, "count": 0, "ms": 40000, "error": "pas de réponse à temps", "example": ""}])


if __name__ == "__main__":
    unittest.main()
