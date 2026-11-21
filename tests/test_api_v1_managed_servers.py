"""`/api/v1/managed-servers/{id}/…` (docs/modernization/PARITY.md, item 10): the models of ExLlamaV3, LM Studio and Colibri, on the real server of
tests/test_api_v1.py (strict offline mode, as set there).

Hermetic: which server is chosen and what lutin.managed_models reads (the disk, Hugging Face, Colibri) are replaced; no task is started."""
import os
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import managed_models

FIT = {"niveau": "bien", "texte": "Tient sur cette machine."}


def setUpModule():
    V.setUpModule()


class ManagedServers(unittest.TestCase):
    def chosen(self, kind):
        patch = mock.patch.object(managed_models, "chosen", lambda wanted, mo=None: wanted == kind)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_server_that_is_not_chosen_or_unknown_is_refused(self):
        self.chosen("lmstudio")
        status, answer = V.call("GET", "/api/v1/managed-servers/exllamav3/models", V.DEVICE)
        self.assertEqual((status, answer["error"]["code"]), (409, "not_chosen"))
        self.assertEqual(V.call("GET", "/api/v1/managed-servers/vllm/models", V.DEVICE)[0], 404)

    def test_the_models_on_disk_are_judged_and_the_one_in_use_marked(self):
        self.chosen("exllamav3")
        seen = {"modeles": [{"nom": "Qwen3-8B-exl3", "taille_go": 6.1, "depot": "turboderp/Qwen3-8B-exl3", "revision": "4.0bpw", "commit": "", "incomplet": False,
                             "adequation": FIT, "utilise": True}], "installe": True, "dossier": "/models", "actif": False, "maj": True, "nom": "ExLlamaV3", "statut": "arrêté", "demarrer": None}
        with mock.patch.object(managed_models, "models", lambda kind, current: seen):
            status, answer = V.call("GET", "/api/v1/managed-servers/exllamav3/models", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["installed"], answer["running"], answer["can_check_updates"]), (True, False, True))
        self.assertEqual(answer["models"], [{"name": "Qwen3-8B-exl3", "fit": {"level": "good", "text": "Tient sur cette machine."}, "size_gb": 6.1, "repo": "turboderp/Qwen3-8B-exl3",
                                             "revision": "4.0bpw", "path": None, "incomplete": False, "in_use": True, "deletable": True}])

    def test_the_catalogue_and_the_quantizations(self):
        self.chosen("lmstudio")
        found = {"suite": True, "modeles": [{"id": "lmstudio-community/Qwen3-8B-GGUF", "nom": "Qwen3-8B-GGUF", "auteur": "lmstudio-community", "telechargements": 9, "aime": 2, "maj": "",
                                              "estimation_go": 5.0, "adequation": FIT, "installes": ["Q4_K_M"]}]}
        asked = []
        with mock.patch.object(managed_models, "catalog", lambda *args: asked.append(args) or found), \
                mock.patch.object(managed_models, "quantizations", lambda kind, repo: [{"revision": "Q4_K_M", "go": 5.0, "fichiers": 1, "adequation": FIT, "installe": True}]):
            status, answer = V.call("GET", "/api/v1/managed-servers/lmstudio/catalog?q=qwen&order=popular&community=1", V.DEVICE)
            self.assertEqual(status, 200, answer)
            self.assertEqual(asked, [("lmstudio", "qwen", "populaire", True, "1")])
            self.assertEqual((answer["models"][0]["on_disk"], answer["more"]), (["Q4_K_M"], True))
            self.assertEqual(V.call("GET", "/api/v1/managed-servers/lmstudio/catalog?order=size", V.DEVICE)[0], 400)
            status, answer = V.call("GET", "/api/v1/managed-servers/lmstudio/quantizations?repo=lmstudio-community/Qwen3-8B-GGUF", V.DEVICE)
            self.assertEqual(answer["quantizations"], [{"revision": "Q4_K_M", "size_gb": 5.0, "fit": {"level": "good", "text": "Tient sur cette machine."}, "on_disk": True}])

    def test_the_recommended_models_come_with_the_quantisation_to_take_and_the_exact_size(self):
        self.chosen("exllamav3")
        found = [{"id": "turboderp/Qwen3-27B-exl3", "nom": "Qwen3-27B-exl3", "revision": "5.0bpw", "go": 17.9, "adequation": FIT, "installe": False}]
        with mock.patch.object(managed_models, "recommended", lambda kind: found):
            status, answer = V.call("GET", "/api/v1/managed-servers/exllamav3/recommended", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["models"], [{"id": "turboderp/Qwen3-27B-exl3", "name": "Qwen3-27B-exl3", "revision": "5.0bpw", "size_gb": 17.9,
                                             "fit": {"level": "good", "text": "Tient sur cette machine."}, "on_disk": False}])
        with mock.patch.object(managed_models, "recommended", side_effect=ValueError("Hugging Face ne répond pas")):
            status, answer = V.call("GET", "/api/v1/managed-servers/exllamav3/recommended", V.DEVICE)
        self.assertEqual((status, answer["error"]["code"]), (502, "unreachable"))
        self.chosen("lmstudio")
        self.assertEqual(V.call("GET", "/api/v1/managed-servers/exllamav3/recommended", V.DEVICE)[0], 409, "only the server in use")

    def test_a_check_for_updates_is_for_exllamav3_only(self):
        self.chosen("lmstudio")
        self.assertEqual(V.call("POST", "/api/v1/managed-servers/lmstudio/check", V.DEVICE, {"scope": "updates"})[0], 400)
        with mock.patch.object(managed_models, "check", lambda kind, scope: {"propositions": [{"id": "a/b", "nom": "b", "estimation_go": 4.0, "adequation": FIT}]}):
            status, answer = V.call("POST", "/api/v1/managed-servers/lmstudio/check", V.DEVICE, {"scope": "new"})
        self.assertEqual((status, [p["id"] for p in answer["proposals"]]), (200, ["a/b"]))

    def test_a_download_needs_this_machine_a_confirmation_and_the_network(self):
        self.chosen("exllamav3")
        started = []
        with mock.patch.object(managed_models, "download", lambda *args: started.append(args)):
            self.assertEqual(V.call("POST", "/api/v1/managed-servers/exllamav3/downloads", V.DEVICE, {"repo": "a/b", "confirm": True})[0], 403)
            status, answer = V.call("POST", "/api/v1/managed-servers/exllamav3/downloads", V.OWNER, {"repo": "a/b"})
            self.assertEqual((status, answer["error"]["code"]), (400, "confirmation_required"))
            status, answer = V.call("POST", "/api/v1/managed-servers/exllamav3/downloads", V.OWNER, {"repo": "a/b", "confirm": True})
            self.assertEqual((status, answer["error"]["code"]), (409, "offline"))
            with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": ""}):
                status, answer = V.call("POST", "/api/v1/managed-servers/exllamav3/downloads", V.OWNER, {"repo": "a/b", "revision": "4.0bpw", "confirm": True})
        self.assertEqual(status, 202, answer)
        self.assertEqual(started, [("exllamav3", "a/b", "4.0bpw")])


if __name__ == "__main__":
    unittest.main()
