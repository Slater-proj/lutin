"""`GET /api/v1/models/loaded`: is the model in use in the memory of this machine, on the real server of tests/test_api_v1.py and a FAKE engine. An engine that cannot say is « not known »:
the page shows nothing rather than a « not loaded » that may be wrong."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, engines  # noqa: E402


class Fake(engines.Engine):
    id, nom, genre = "fake", "Fake engine", "openai"
    held = None
    says = True

    def charge_connue(self):
        return self.says

    def en_memoire(self, modele):
        return self.held


def setUpModule():
    V.setUpModule()


class Loaded(unittest.TestCase):
    def setUp(self):
        api_v1._SEEN_LOADED.clear()
        api_v1._LOADING.clear()
        self.fake = Fake()
        self.settings = {"modele": "m1", "machine": ""}
        for patch in (mock.patch.object(api_v1._m, "moteur_actuel", return_value=self.fake), mock.patch.object(api_v1._m, "settings", side_effect=lambda: dict(self.settings))):
            patch.start()
            self.addCleanup(patch.stop)

    def get(self):
        status, body = V.call("GET", "/api/v1/models/loaded", V.OWNER)
        self.assertEqual(status, 200, body)
        return body

    def test_a_model_in_memory_says_so_with_its_size(self):
        self.fake.held = {"taille": 5_000_000_000, "vram": 4_000_000_000}
        self.assertEqual(self.get(), {"engine": "fake", "model": "m1", "known": True, "loaded": True, "state": "loaded", "loading_bytes": 0, "size_bytes": 5_000_000_000,
                                      "vram_bytes": 4_000_000_000})

    def test_a_model_that_is_not_in_memory_is_known_not_to_be(self):
        answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"]), (True, False))

    def test_while_a_turn_answers_the_model_stays_in_memory_even_if_the_busy_server_is_late_to_say_it(self):
        """Maintainer, 2026-11-21: the pill went to « not loaded » while the model was thinking. A server that generates (TabbyAPI) answers the question late
        (3 s): that silence was read as « not loaded ». A model the engine was seen holding stays in memory while a turn of this machine runs."""
        self.fake.held = {"taille": 1, "vram": 1}
        self.assertEqual(self.get()["state"], "loaded")
        self.fake.held = None
        with mock.patch.dict(api_v1._m.ACTIVE_TURNS, {"conversation": object()}):
            answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"], answer["state"]), (True, True, "loaded"))
        self.assertEqual((self.get()["loaded"], self.get()["state"]), (False, "not_loaded"), "once the turn is over, the engine's own answer counts again")

    def test_a_turn_that_waits_for_a_model_never_seen_in_memory_says_it_is_loading_with_what_the_card_took(self):
        """Maintainer, 2026-11-22: a third state « loading » with its progress. Before, the pill said « in memory » as soon as a turn started; the face of
        the answer could never sleep while the model loaded. The progress is how much the memory of the graphics card grew since the load began."""
        card = {"used": 2_000_000_000}
        api_v1._health.forget_measures("vram")
        with mock.patch.object(api_v1._health, "video_memory", side_effect=lambda: {"nom": "card", "total": 24_000_000_000, "utilise": card["used"], "libre": 1}),                 mock.patch.object(api_v1._health, "MEMO_TTL_S", dict(api_v1._health.MEMO_TTL_S, vram=0)), mock.patch.dict(api_v1._m.ACTIVE_TURNS, {"conversation": object()}):
            first = self.get()
            card["used"] = 7_500_000_000
            later = self.get()
        self.assertEqual((first["known"], first["loaded"], first["state"], first["loading_bytes"]), (True, False, "loading", 0))
        self.assertEqual((later["state"], later["loading_bytes"]), ("loading", 5_500_000_000))
        self.fake.held = {"taille": 1, "vram": 1}
        self.assertEqual(self.get()["state"], "loaded")

    def test_loading_without_a_card_that_says_its_memory_still_says_loading(self):
        api_v1._health.forget_measures("vram")
        with mock.patch.object(api_v1._health, "video_memory", return_value=None), mock.patch.dict(api_v1._m.ACTIVE_TURNS, {"conversation": object()}):
            answer = self.get()
        self.assertEqual((answer["state"], answer["loading_bytes"]), ("loading", 0))

    def test_an_engine_that_cannot_say_is_not_known(self):
        self.fake.says = False
        self.fake.held = None
        answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"], answer["state"]), (False, False, "unknown"), "no answer is not « not loaded »")

    def test_a_model_of_another_machine_is_not_known_here(self):
        self.settings["machine"] = "0123abcd"
        self.fake.held = {"taille": 1, "vram": 1}
        self.assertEqual((self.get()["known"], self.get()["loaded"]), (False, False))

    def test_without_a_model_nothing_is_known(self):
        self.settings["modele"] = ""
        self.assertFalse(self.get()["known"])

    def test_a_visitor_without_session_is_refused(self):
        self.assertEqual(V.call("GET", "/api/v1/models/loaded", {})[0], 401)


if __name__ == "__main__":
    unittest.main()
