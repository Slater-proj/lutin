"""`/api/v1/setup`: when the guide of the first launch is shown. The rule that matters: an installation that already lives is NEVER taken for a new machine."""
import time
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
        with mock.patch.object(A, "conv_list", return_value=[]), mock.patch.object(A, "DATA", A.DATA / "empty-folder-for-this-test"):
            self.assertFalse(api_v1._has_history())
        with mock.patch.object(A, "conv_list", return_value=[{"id": "0123abcd"}]):
            self.assertTrue(api_v1._has_history())
        (A.DATA / "reglages.json").write_text("{}", encoding="utf-8")
        self.addCleanup(lambda: (A.DATA / "reglages.json").unlink(missing_ok=True))
        with mock.patch.object(A, "conv_list", return_value=[]):
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

class Language(unittest.TestCase):
    def test_the_language_is_read_chosen_and_refused_when_unknown(self):
        from lutin import i18n
        before = i18n.configured_language()
        self.addCleanup(i18n.save_language, before or "auto")
        status, answer = V.call("PATCH", "/api/v1/language", V.OWNER, {"language": "en"})
        self.assertEqual((status, answer["choice"]), (200, "en"))          # `language` is the one in use: the test server forces it with LUTIN_LANGUE
        self.assertEqual(V.call("GET", "/api/v1/language", V.OWNER)[1]["choice"], "en")
        self.assertEqual(sorted(answer), ["choice", "language"])
        status, answer = V.call("PATCH", "/api/v1/language", V.OWNER, {"language": "auto"})
        self.assertEqual((status, answer["choice"]), (200, "auto"))
        status, answer = V.call("PATCH", "/api/v1/language", V.OWNER, {"language": "klingon"})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

class SpeedTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(api_v1.SPEED.update, state="idle", model="", tokens_per_second=None, level=None, error="")
        api_v1.SPEED.update(state="idle")

    def wait(self, wanted):
        for _ in range(100):
            answer = V.call("GET", "/api/v1/speed-test", V.OWNER)[1]
            if answer["state"] == wanted:
                return answer
            time.sleep(0.05)
        self.fail("the test never reached %s: %s" % (wanted, answer))

    def test_a_short_measure_is_started_followed_and_put_in_words(self):
        installed = mock.patch.object(api_v1._m, "etat_ollama", return_value={"installes": [api_v1._m.settings()["modele"]]})
        engine = mock.patch.object(api_v1._m, "moteur_actuel", return_value=mock.Mock(id="ollama"))
        with installed, engine, mock.patch.object(api_v1, "_measure_speed", return_value=21.4):
            status, answer = V.call("POST", "/api/v1/speed-test", V.OWNER, {})
            self.assertEqual((status, answer["state"]), (202, "running"))
            done = self.wait("done")
        self.assertEqual((done["tokens_per_second"], done["level"]), (21.4, "comfortable"))
        self.assertEqual([api_v1._speed_level(x) for x in (3, 10, 21, 45, 90)], ["slow", "fair", "comfortable", "fast", "very_fast"])

    def test_a_failing_engine_ends_the_test_and_a_missing_model_or_busy_turn_refuses_it(self):
        installed = mock.patch.object(api_v1._m, "etat_ollama", return_value={"installes": [api_v1._m.settings()["modele"]]})
        engine = mock.patch.object(api_v1._m, "moteur_actuel", return_value=mock.Mock(id="ollama"))
        with installed, engine, mock.patch.object(api_v1, "_measure_speed", side_effect=RuntimeError("engine down")):
            V.call("POST", "/api/v1/speed-test", V.OWNER, {})
            failed = self.wait("failed")
        self.assertEqual(failed["error"], "engine down")
        with mock.patch.object(api_v1._m, "etat_ollama", return_value={"installes": []}), engine:
            status, answer = V.call("POST", "/api/v1/speed-test", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "model_missing"))
        with installed, engine, mock.patch.dict(api_v1._m.ACTIVE_TURNS, {"x": object()}):
            status, answer = V.call("POST", "/api/v1/speed-test", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "busy"))



if __name__ == "__main__":
    unittest.main()
