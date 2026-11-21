"""`/api/v1/offline` (docs/modernization/PARITY.md, item 7): the strict offline switch, on the real server of tests/test_api_v1.py.

Hermetic: the configuration file is a temporary one, and LUTIN_HORS_LIGNE (set by test_api_v1 for the whole module) is cleared or set per test."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)


def setUpModule():
    V.setUpModule()


class Offline(unittest.TestCase):
    def setUp(self):
        self.config = Path(tempfile.mkdtemp(prefix="lutin-offline-")) / "config.json"
        self.config.write_text(json.dumps({"kept": 1}), encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"LUTIN_CONFIG": str(self.config), "LUTIN_HORS_LIGNE": ""})
        patch.start()
        self.addCleanup(patch.stop)

    def saved(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_the_state_says_what_is_allowed_and_blocked(self):
        status, answer = V.call("GET", "/api/v1/offline", V.OWNER)
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["active"], answer["forced"], answer["can_turn_off"]), (False, False, True))
        self.assertIn("127.0.0.1", answer["allowed_hosts"])
        self.assertIn("web_search", answer["blocks"])
        self.assertFalse(V.call("GET", "/api/v1/offline", V.DEVICE)[1]["can_turn_off"], "a paired device cannot open this machine to the network")

    def test_it_is_turned_on_kept_and_shown_in_the_status(self):
        status, answer = V.call("POST", "/api/v1/offline", V.DEVICE, {})
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer["active"])
        self.assertEqual(self.saved(), {"kept": 1, "hors_ligne": True}, "kept in config.json, the rest untouched")
        self.assertTrue(V.call("GET", "/api/v1/status", V.OWNER)[1]["offline"])

    def test_only_this_machine_turns_it_off(self):
        V.call("POST", "/api/v1/offline", V.OWNER, {})
        status, answer = V.call("DELETE", "/api/v1/offline", V.DEVICE)
        self.assertEqual(status, 403, answer)
        self.assertTrue(self.saved()["hors_ligne"])
        status, answer = V.call("DELETE", "/api/v1/offline", V.OWNER)
        self.assertEqual(status, 200, answer)
        self.assertFalse(answer["active"])
        self.assertFalse(self.saved()["hors_ligne"])
        self.assertFalse(V.call("GET", "/api/v1/status", V.OWNER)[1]["offline"])

    def test_the_variable_forces_it_for_the_launch(self):
        with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": "1"}):
            answer = V.call("GET", "/api/v1/offline", V.OWNER)[1]
            self.assertEqual((answer["active"], answer["forced"], answer["can_turn_off"]), (True, True, False))
            status, answer = V.call("DELETE", "/api/v1/offline", V.OWNER)
            self.assertEqual((status, answer["error"]["code"]), (409, "forced"))

    def test_without_a_configuration_file_it_cannot_be_kept(self):
        with mock.patch.dict(os.environ, {"LUTIN_CONFIG": ""}):
            status, answer = V.call("POST", "/api/v1/offline", V.OWNER, {})
        self.assertEqual((status, answer["error"]["code"]), (409, "not_available"))


if __name__ == "__main__":
    unittest.main()
