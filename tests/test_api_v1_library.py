"""`/api/v1/engines/{id}/library`: search a model on Hugging Face, see the quantisations of a repository with a verdict for the machine, download one. A FAKE engine and a fictive machine:
nothing is downloaded and no hardware is read."""
import time
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, engines, hardware, model_fit  # noqa: E402

BASE = "/api/v1/engines/lib/library"


class Library(engines.Moteur):
    id, nom, genre, gere_modeles, description = "lib", "Library engine", "openai", True, "An engine with a library."

    def __init__(self):
        self.downloaded, self.can = [], {"possible": True, "raison": ""}

    def chercher_modeles(self, terme):
        if not terme.strip():
            raise ValueError("Write the name of a model to search.")
        return [{"id": "author/qwen-GGUF", "telechargements": 1200, "likes": 30}]

    def fichiers_du_depot(self, repo):
        if repo == "nobody/nothing":
            raise ValueError("Repository not found.")
        return [{"fichier": "q2.gguf", "taille": 2_000_000_000}, {"fichier": "q8.gguf", "taille": 900_000_000_000}, {"fichier": "empty.gguf", "taille": 0}]

    def telechargeable(self):
        return self.can

    def telecharger_modele(self, repo, fichier, progression):
        progression("downloading", 1, 2)
        self.downloaded.append((repo, fichier))
        return "q2"

    def statut(self):
        return {"installe": True, "actif": True, "version": "", "detail": ""}

    def modeles(self):
        return {"actif": True, "installes": [], "tailles": {}}

    def actions(self):
        return {}


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body=body)


class Tests(unittest.TestCase):
    def setUp(self):
        self.engine = Library()
        plain = engines.Moteur.__new__(engines.Moteur)          # no `chercher_modeles` at all
        plain.id, plain.nom, plain.genre, plain.gere_modeles, plain.description = "plain", "Plain engine", "openai", True, ""
        for patch in (mock.patch.dict(engines.ENGINES, {"lib": self.engine, "plain": plain}), mock.patch.object(api_v1._offline, "is_active", return_value=False),
                      mock.patch.dict(model_fit._etat, {"profil": hardware.profil_demo(), "quand": time.time() + 3600, "en_cours": False})):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(lambda: engines.TASKS.pop("lib", None))

    def test_a_search_gives_english_keys_and_asks_for_words(self):
        status, answer = call("GET", BASE + "?q=qwen")
        self.assertEqual((status, answer), (200, {"results": [{"repo": "author/qwen-GGUF", "downloads": 1200, "likes": 30}]}))
        status, answer = call("GET", BASE + "?q=")
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

    def test_the_files_come_with_a_verdict_for_this_machine_and_none_when_the_size_is_unknown(self):
        status, answer = call("GET", BASE + "/files?repo=author/qwen-GGUF")
        self.assertEqual(status, 200)
        files = {item["file"]: item for item in answer["files"]}
        self.assertEqual(sorted(files["q2.gguf"]), ["file", "fit", "size_bytes"])
        self.assertIn(files["q2.gguf"]["fit"]["level"], ("comfortable", "good", "tight"))
        self.assertEqual(files["q8.gguf"]["fit"]["level"], "too_big", "900 GB does not fit this machine")
        self.assertIsNone(files["empty.gguf"]["fit"])
        self.assertEqual(call("GET", BASE + "/files?repo=nobody/nothing")[0], 400)

    def test_the_machine_not_yet_detected_gives_no_verdict_but_still_lists_the_files(self):
        with mock.patch.dict(model_fit._etat, {"profil": None, "quand": 0.0, "en_cours": True}):
            files = call("GET", BASE + "/files?repo=author/qwen-GGUF")[1]["files"]
        self.assertTrue(files and all(item["fit"] is None for item in files))

    def test_a_download_needs_the_confirmation_and_runs_as_a_task(self):
        for body in ({"repo": "author/qwen-GGUF", "file": "q2.gguf"}, {"repo": "author/qwen-GGUF", "file": "q2.gguf", "confirm": False}):
            status, answer = call("POST", BASE + "/download", body)
            self.assertEqual((status, answer["error"]["code"]), (400, "confirmation_required"), body)
        self.assertEqual(self.engine.downloaded, [], "nothing downloaded without the confirmation")
        status, task = call("POST", BASE + "/download", {"repo": "author/qwen-GGUF", "file": "q2.gguf", "confirm": True})
        self.assertEqual(status, 202, task)
        for _ in range(100):
            if self.engine.downloaded:
                break
            time.sleep(0.05)
        self.assertEqual(self.engine.downloaded, [("author/qwen-GGUF", "q2.gguf")])

    def test_refusals_carry_a_code(self):
        self.assertEqual(call("POST", BASE + "/download", {"repo": "a/b"})[1]["error"]["code"], "invalid_request", "a file is needed")
        self.assertEqual(call("POST", BASE + "/download", {"repo": "a/b", "file": "c", "confirm": "yes"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", BASE + "/download", {"repo": "a/b", "file": "c", "confirm": True, "x": 1})[1]["error"]["code"], "invalid_request")
        self.engine.can = {"possible": False, "raison": "No download here."}
        status, answer = call("POST", BASE + "/download", {"repo": "a/b", "file": "c.gguf", "confirm": True})
        self.assertEqual((status, answer["error"]), (400, {"code": "action_impossible", "message": "No download here."}))
        self.assertEqual(call("GET", "/api/v1/engines/nope/library?q=x")[1]["error"]["code"], "not_found")
        for path in ("/engines/plain/library?q=x", "/engines/plain/library/files?repo=a/b"):
            self.assertEqual(call("GET", "/api/v1" + path)[1]["error"]["code"], "no_library", path)
        self.assertEqual(call("POST", "/api/v1/engines/plain/library/download", {"repo": "a/b", "file": "c", "confirm": True})[1]["error"]["code"], "no_library")

    def test_strict_offline_mode_refuses_each_of_them_and_the_confirmation_comes_first(self):
        with mock.patch.object(api_v1._offline, "is_active", return_value=True):
            for method, path, body in (("GET", BASE + "?q=x", None), ("GET", BASE + "/files?repo=a/b", None), ("POST", BASE + "/download", {"repo": "a/b", "file": "c", "confirm": True})):
                status, answer = call(method, path, body)
                self.assertEqual((status, answer["error"]["code"]), (409, "offline"), path)
            self.assertEqual(call("POST", BASE + "/download", {"repo": "a/b", "file": "c"})[1]["error"]["code"], "confirmation_required")
        self.assertEqual(self.engine.downloaded, [])

    def test_a_paired_device_may_not_search_or_download(self):
        for method, path in (("GET", BASE + "?q=x"), ("GET", BASE + "/files?repo=a/b"), ("POST", BASE + "/download")):
            self.assertEqual(call(method, path, {} if method == "POST" else None, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


if __name__ == "__main__":
    unittest.main()
