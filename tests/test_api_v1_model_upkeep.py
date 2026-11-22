"""The upkeep of the models in `/api/v1/models/…` (docs/modernization/PARITY.md, item 10): the proposals and the check, the precision variants and
the Ollama library, on the real server of tests/test_api_v1.py (strict offline mode, as set there).

Hermetic: the proposals and config.json are temporary files, the checker is a function of the test, ollama.com is `model_variants.list_variants` and
`model_discovery.search` replaced, and the machine is the demonstration profile (nothing is detected)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import hardware, model_discovery, model_fit, model_variants

A = V.A
PROPOSALS = {"date": 1700000000, "catalogue": "absent", "erreurs": [], "propositions": [
    {"cle": "maj:qwen3:8b", "type": "maj", "modele": "qwen3:8b", "raison": "Une version plus récente de ce modèle est disponible."},
    {"cle": "nouveau:code:qwen3-coder:30b", "type": "nouveau", "role": "code", "modele": "qwen3-coder:30b", "ancien": "qwen2.5-coder:7b", "phrase": "Pour coder.", "go": 18.6, "raison": "Mieux."},
    {"cle": "obsolete:llama3:8b", "type": "obsolete", "modele": "llama3:8b", "remplace_par": "llama3.1:8b", "go": 4.7, "raison": "Remplacé."}]}


def setUpModule():
    V.setUpModule()


class Upkeep(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp(prefix="lutin-upkeep-"))
        self.proposals, self.config = folder / "propositions.json", folder / "config.json"
        self.proposals.write_text(json.dumps(PROPOSALS), encoding="utf-8")
        self.config.write_text("{}", encoding="utf-8")
        for patch in (mock.patch.dict(os.environ, {"LUTIN_PROPOSITIONS": str(self.proposals), "LUTIN_CONFIG": str(self.config)}),
                      mock.patch.dict(model_fit._state, {"profil": hardware.profil_demo(), "quand": time.time() + 3600, "en_cours": False})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_proposals_are_read_from_the_cache(self):
        status, answer = V.call("GET", "/api/v1/models/proposals", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual([(p["kind"], p["model"]) for p in answer["proposals"]], [("update", "qwen3:8b"), ("new", "qwen3-coder:30b"), ("obsolete", "llama3:8b")])
        new = answer["proposals"][1]
        self.assertEqual((new["role"], new["replaces"], new["size_gb"], new["summary"]), ("code", "qwen2.5-coder:7b", 18.6, "Pour coder."))
        self.assertEqual(answer["proposals"][2]["replaced_by"], "llama3.1:8b")
        self.assertEqual((answer["checked_at"], answer["catalogue"]), (1700000000, "absent"))

    def test_a_dismissed_proposal_is_not_made_again(self):
        status, answer = V.call("DELETE", "/api/v1/models/proposals/obsolete:llama3:8b", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertNotIn("llama3:8b", [p["model"] for p in answer["proposals"]])
        self.assertIn("obsolete:llama3:8b", json.loads(self.config.read_text(encoding="utf-8"))["modeles"]["ignores"])
        self.assertEqual(V.call("DELETE", "/api/v1/models/proposals/obsolete:llama3:8b", V.DEVICE)[0], 404)

    def test_a_followed_proposal_makes_the_model_the_one_of_its_role(self):
        status, answer = V.call("POST", "/api/v1/models/proposals/nouveau:code:qwen3-coder:30b/applied", V.DEVICE, {})
        self.assertEqual(status, 200, answer)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["modeles"]["choisis"], {"code": "qwen3-coder:30b"})
        status, answer = V.call("POST", "/api/v1/models/proposals/maj:qwen3:8b/applied", V.DEVICE, {})
        self.assertEqual([p["kind"] for p in answer["proposals"]], ["obsolete"])
        self.assertNotIn("maj:qwen3:8b", json.loads(self.config.read_text(encoding="utf-8"))["modeles"]["ignores"], "an update installed does not silence the next ones")

    def test_a_check_is_asked_now_with_its_scope(self):
        asked = []

        def checker(scope):
            asked.append(scope)
            self.proposals.write_text(json.dumps(dict(PROPOSALS, propositions=PROPOSALS["propositions"][:1], date=1800000000)), encoding="utf-8")
        with mock.patch.object(A, "MODEL_CHECKER", None):
            status, answer = V.call("POST", "/api/v1/models/check", V.DEVICE, {"scope": "updates"})
            self.assertEqual((status, answer["error"]["code"]), (409, "not_available"))
        with mock.patch.object(A, "MODEL_CHECKER", checker):
            status, answer = V.call("POST", "/api/v1/models/check", V.DEVICE, {"scope": "updates"})
            self.assertEqual(status, 200, answer)
            self.assertEqual((asked, len(answer["proposals"]), answer["checked_at"]), (["maj"], 1, 1800000000))
            self.assertEqual(V.call("POST", "/api/v1/models/check", V.DEVICE, {"scope": "everything"})[0], 400)

    def test_the_variants_are_judged_for_this_machine(self):
        found = {"defaut": {"id": "qwen3:8b", "go": 5.2}, "variantes": [{"precision": "q4_K_M", "id": "qwen3:8b-q4_K_M", "go": 5.2, "defaut": True},
                                                                       {"precision": "fp16", "id": "qwen3:8b-fp16", "go": 16.4, "defaut": False}]}
        with mock.patch.object(model_variants, "list_variants", lambda name: found):
            status, answer = V.call("GET", "/api/v1/models/variants?model=qwen3:8b", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["default"], {"name": "qwen3:8b", "size_gb": 5.2})
        self.assertEqual([(v["name"], v["default"], v["installed"]) for v in answer["variants"]], [("qwen3:8b-q4_K_M", True, False), ("qwen3:8b-fp16", False, False)])
        self.assertIn(answer["variants"][1]["fit"]["level"], ("comfortable", "good", "tight", "too_big"))
        self.assertTrue(answer["variants"][1]["meaning"])

    def test_the_library_gives_each_size_an_estimate_and_a_verdict(self):
        found = {"suite": True, "modeles": [{"nom": "gemma3", "description": "A model.", "capacites": ["vision"], "tailles": ["4b", "27b"], "maj": "2 weeks ago", "telechargements": 1200}]}
        with mock.patch.object(model_discovery, "search", lambda *args, **kwargs: found):
            status, answer = V.call("GET", "/api/v1/models/library?q=gemma&order=popular", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer["more"])
        model = answer["models"][0]
        self.assertEqual((model["name"], model["capabilities"], model["downloads"]), ("gemma3", ["vision"], 1200))
        self.assertEqual([size["name"] for size in model["sizes"]], ["gemma3:4b", "gemma3:27b"])
        self.assertLess(model["sizes"][0]["estimated_gb"], model["sizes"][1]["estimated_gb"])
        self.assertIsNotNone(model["sizes"][0]["fit"])
        self.assertEqual(V.call("GET", "/api/v1/models/library?order=random", V.DEVICE)[0], 400)

    def test_ollama_com_is_not_reached_in_strict_offline_mode(self):
        for path in ("/api/v1/models/variants?model=qwen3:8b", "/api/v1/models/library?q=offline-test"):
            status, answer = V.call("GET", path, V.DEVICE)
            self.assertEqual((status, answer["error"]["code"]), (409, "offline"), path)


if __name__ == "__main__":
    unittest.main()
