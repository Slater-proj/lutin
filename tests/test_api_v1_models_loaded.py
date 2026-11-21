"""`GET /api/v1/models/loaded`: is the model in use in the memory of this machine, on the real server of tests/test_api_v1.py and a FAKE engine. An engine that cannot say is « not known »:
the page shows nothing rather than a « not loaded » that may be wrong."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, engines  # noqa: E402


class Fake(engines.Moteur):
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
        self.fake = Fake()
        self.settings = {"modele": "m1", "machine": ""}
        for patch in (mock.patch.object(api_v1._m, "moteur_actuel", return_value=self.fake), mock.patch.object(api_v1._m, "reglages", side_effect=lambda: dict(self.settings))):
            patch.start()
            self.addCleanup(patch.stop)

    def get(self):
        status, body = V.call("GET", "/api/v1/models/loaded", V.OWNER)
        self.assertEqual(status, 200, body)
        return body

    def test_a_model_in_memory_says_so_with_its_size(self):
        self.fake.held = {"taille": 5_000_000_000, "vram": 4_000_000_000}
        self.assertEqual(self.get(), {"engine": "fake", "model": "m1", "known": True, "loaded": True, "size_bytes": 5_000_000_000, "vram_bytes": 4_000_000_000})

    def test_a_model_that_is_not_in_memory_is_known_not_to_be(self):
        answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"]), (True, False))

    def test_while_a_turn_answers_the_model_stays_in_memory_even_if_the_busy_server_is_late_to_say_it(self):
        """Maintainer, 2026-11-21: the pill went to « not loaded » while the model was thinking. A server that generates (TabbyAPI) answers the question late
        (3 s): that silence was read as « not loaded ». A turn of this machine answering with this engine has its model in memory, or being loaded."""
        with mock.patch.dict(api_v1._m.TOURS_ACTIFS, {"conversation": object()}):
            answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"]), (True, True))
        self.assertEqual(self.get()["loaded"], False, "once the turn is over, the engine's own answer counts again")

    def test_an_engine_that_cannot_say_is_not_known(self):
        self.fake.says = False
        self.fake.held = None
        answer = self.get()
        self.assertEqual((answer["known"], answer["loaded"]), (False, False), "no answer is not « not loaded »")

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
