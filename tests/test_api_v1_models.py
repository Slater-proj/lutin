"""`/api/v1/models`: list, install, delete, on a real server with the fake engine of tests/test_moteur.py.

What is fixed here: the fields of the list and of a download, the translated states, and the refusals with a code."""
import time
import unittest
from unittest import mock

import test_api_v1_turns as U  # its callers and, through it, the fake engine of tests/test_moteur.py (imported as modules: their tests do not run here)

from lutin import offline  # noqa: E402

T, A, api = U.T, U.A, U.api


class Models(unittest.TestCase):
    def setUp(self):
        installed, model = list(T.INSTALLES), A.reglages()["modele"]

        def restore():
            T.INSTALLES[:] = installed
            A.PULLS.clear()
            A.enregistrer_reglages({"modele": model})
        self.addCleanup(restore)

    def test_the_list_gives_what_the_model_selector_needs(self):
        status, answer = api("GET", "/api/v1/models")
        self.assertEqual((status, sorted(answer)), (200, ["current", "downloads", "engine", "models", "running"]))
        self.assertEqual((answer["engine"], answer["running"], answer["current"], answer["downloads"]), ("ollama", True, A.reglages()["modele"], []))
        self.assertEqual([sorted(model) for model in answer["models"]], [["name", "size_bytes"]] * len(T.INSTALLES))
        self.assertEqual([model["name"] for model in answer["models"]], T.INSTALLES)

    def test_a_download_is_started_then_followed_through_the_list(self):
        status, started = api("POST", "/api/v1/models", {"name": "gemma4:12b"})
        self.assertEqual((status, sorted(started)), (202, ["done_bytes", "name", "restart_engine_advised", "state", "text", "total_bytes"]))
        self.assertEqual((started["name"], started["state"], started["restart_engine_advised"]), ("gemma4:12b", "downloading", False))
        for _ in range(60):
            download = api("GET", "/api/v1/models")[1]["downloads"][0]
            if download["state"] != "downloading":
                break
            time.sleep(0.1)
        self.assertEqual((download["name"], download["state"], download["done_bytes"], download["total_bytes"]), ("gemma4:12b", "done", 100, 100))
        self.assertIn("gemma4:12b", [model["name"] for model in api("GET", "/api/v1/models")[1]["models"]])

    def test_a_failed_download_says_so(self):
        api("POST", "/api/v1/models", {"name": "inexistant:1m"})
        for _ in range(60):
            download = api("GET", "/api/v1/models")[1]["downloads"][0]
            if download["state"] != "downloading":
                break
            time.sleep(0.1)
        self.assertEqual((download["state"], bool(download["text"])), ("failed", True))

    def test_refusals_carry_a_code(self):
        fields = (400, {"error": {"code": "invalid_request", "message": "Champs acceptés : name."}})
        for body in ({}, {"name": 3}, {"name": "gemma4:12b", "modele": "x"}):
            self.assertEqual(api("POST", "/api/v1/models", body), fields, body)
        self.assertEqual(api("POST", "/api/v1/models", {"name": "bad name!"}), (400, {"error": {"code": "invalid_request", "message": "Nom de modèle invalide."}}))
        self.assertEqual(api("DELETE", "/api/v1/models/bad%20name!"), (400, {"error": {"code": "invalid_request", "message": "Nom de modèle invalide."}}))
        self.assertEqual(api("DELETE", "/api/v1/models/unknown:1b"), (400, {"error": {"code": "invalid_request", "message": "Ce modèle n'est pas installé."}}))
        self.assertEqual(A.PULLS, {}, "no download was started by a refused request")
        with mock.patch.object(offline, "actif", lambda *a: True):          # strict offline mode
            status, answer = api("POST", "/api/v1/models", {"name": "gemma4:12b"})
        self.assertEqual((status, answer["error"]["code"]), (409, "offline"))

    def test_deleting_the_model_in_use_switches_to_another(self):
        T.INSTALLES[:] = ["qwen3.8:27b", "other:7b"]
        A.enregistrer_reglages({"modele": "qwen3.8:27b"})
        self.assertEqual(api("DELETE", "/api/v1/models/qwen3.8:27b"), (200, {"deleted": True, "current": "other:7b"}))
        self.assertEqual([model["name"] for model in api("GET", "/api/v1/models")[1]["models"]], ["other:7b"])
        self.assertEqual(api("DELETE", "/api/v1/models/other%3A7b"), (200, {"deleted": True, "current": "other:7b"}), "the last one: nothing to switch to")
        self.assertEqual(api("GET", "/api/v1/models")[1]["models"], [])


if __name__ == "__main__":
    unittest.main()
