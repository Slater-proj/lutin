"""`/api/v1/setup`: when the guide of the first launch is shown. The rule that matters: an installation that already lives is NEVER taken for a new machine."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1  # noqa: E402

A = V.A
NOBODY = {"actif": False, "installes": [], "tailles": {}}


def setUpModule():
    V.setUpModule()


def state(installed=(), history=False):
    """The answer of /setup for a machine with this engine state and this history."""
    with mock.patch.object(api_v1, "_has_history", return_value=history), mock.patch.object(A, "etat_moteur", return_value={"actif": True, "installes": list(installed), "tailles": {}}):
        return V.call("GET", "/api/v1/setup", V.OWNER)


class Setup(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: api_v1._setup_path().unlink(missing_ok=True))
        api_v1._setup_path().unlink(missing_ok=True)

    def test_a_new_machine_needs_the_guide(self):
        self.assertEqual(state(), (200, {"done": False, "needed": True, "skipped": False}))

    def test_an_installation_that_already_lives_never_does(self):
        self.assertEqual(state(history=True), (200, {"done": False, "needed": False, "skipped": False}), "conversations or a settings file: used before")
        self.assertEqual(state(installed=["qwen3:8b"]), (200, {"done": False, "needed": False, "skipped": False}), "a machine where a model was installed before Lutin")

    def test_history_is_decided_before_the_engine_is_asked(self):
        with mock.patch.object(api_v1, "_has_history", return_value=True), mock.patch.object(A, "etat_moteur", side_effect=AssertionError("the engine must not be asked")):
            self.assertEqual(V.call("GET", "/api/v1/setup", V.OWNER)[1]["needed"], False)

    def test_what_a_used_installation_leaves_is_what_is_looked_at(self):
        with mock.patch.object(A, "conv_liste", return_value=[]), mock.patch.object(A, "DONNEES", A.DONNEES / "empty-folder-for-this-test"):
            self.assertFalse(api_v1._has_history())
        with mock.patch.object(A, "conv_liste", return_value=[{"id": "0123abcd"}]):
            self.assertTrue(api_v1._has_history())
        (A.DONNEES / "reglages.json").write_text("{}", encoding="utf-8")
        self.addCleanup(lambda: (A.DONNEES / "reglages.json").unlink(missing_ok=True))
        with mock.patch.object(A, "conv_liste", return_value=[]):
            self.assertTrue(api_v1._has_history())

    def test_finishing_or_skipping_is_remembered(self):
        status, answer = V.call("POST", "/api/v1/setup/complete", V.OWNER, body={})
        self.assertEqual((status, answer), (200, {"done": True, "needed": False, "skipped": False}))
        self.assertEqual(state(), (200, {"done": True, "needed": False, "skipped": False}), "even on a machine that looks new")
        api_v1._setup_path().unlink()
        self.assertEqual(V.call("POST", "/api/v1/setup/complete", V.OWNER, body={"skipped": True})[1], {"done": True, "needed": False, "skipped": True})

    def test_refusals_and_rights(self):
        self.assertEqual(V.call("POST", "/api/v1/setup/complete", V.OWNER, body={"skipped": "yes"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(V.call("POST", "/api/v1/setup/complete", V.OWNER, body={"other": 1})[1]["error"]["code"], "invalid_request")
        self.assertFalse(api_v1._setup_path().exists(), "a refused request writes nothing")
        self.assertEqual(V.call("POST", "/api/v1/setup/complete", V.DEVICE, body={})[1]["error"]["code"], "configurator", "a phone does not decide for the machine")
        self.assertEqual(V.call("GET", "/api/v1/setup", V.DEVICE)[0], 200)


if __name__ == "__main__":
    unittest.main()
