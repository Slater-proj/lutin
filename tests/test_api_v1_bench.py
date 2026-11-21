"""`/api/v1/bench` and `/api/v1/engines/comparison` (docs/modernization/PARITY.md, item 10): the measures of the models and the comparison of the
engines, on the real server of tests/test_api_v1.py.

Hermetic: the bench file and its history are temporary (LUTIN_BENCH), the measures and the comparison are never run (their launchers are replaced),
and the view of the comparison is `engine_bench.vue` replaced."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import engine_bench

A = V.A
MEASURE = {"modele": "qwen3:8b", "date": "2026-11-18T10:00:00", "machine": "demo", "complet": True, "moteur": {"id": "ollama", "version": "0.12"},
           "resultats": {"vitesse": {"tok_s": 42.5, "charge_s": 3.1, "lecture_tok_s": 900},
                         "outils": {"points": 4, "sur": 5, "details": [{"test": "Ouvrir un fichier", "ok": True}]},
                         "francais": {"points": 3, "sur": 4, "details": []}},
           "notes": {"rapide": 8, "creatif": 7}}


def setUpModule():
    V.setUpModule()


class Bench(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="lutin-bench-")) / "bench.json"
        self.path.write_text(json.dumps({"qwen3:8b": MEASURE}), encoding="utf-8")
        history = [{"modele": "qwen3:8b", "date": "2026-11-01", "moteur": {"id": "ollama"}, "tok_s": 60, "epreuves": {"outils": 0.8}},
                   {"modele": "qwen3:8b", "date": "2026-11-18", "moteur": {"id": "ollama"}, "tok_s": 42.5, "epreuves": {"outils": 0.8}}]
        self.path.with_name("bench_historique.jsonl").write_text("".join(json.dumps(x) + "\n" for x in history), encoding="utf-8")
        for patch in (mock.patch.dict(os.environ, {"LUTIN_BENCH": str(self.path)}), mock.patch.dict(A.BENCH, {"en_cours": "", "etape": "", "erreur": "", "file": []})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_results_regressions_and_history_are_read(self):
        status, answer = V.call("GET", "/api/v1/bench", V.DEVICE)
        self.assertEqual(status, 200, answer)
        result = answer["results"][0]
        self.assertEqual((result["model"], result["engine"], result["speed"]["tokens_per_s"]), ("qwen3:8b", "ollama", 42.5))
        self.assertEqual(result["tests"]["tools"], {"points": 4, "out_of": 5, "details": [{"test": "Ouvrir un fichier", "ok": True}]})
        self.assertEqual(sorted(result["tests"]), ["french", "tools"])
        self.assertEqual(result["grades"], {"fast": 8, "creative": 7})
        self.assertEqual(answer["regressions"], [{"model": "qwen3:8b", "kind": "speed", "before": 60, "after": 42.5, "engine_changed": False}])
        self.assertEqual([m["tokens_per_s"] for m in answer["history"][0]["measures"]], [60, 42.5])
        self.assertEqual(answer["running"], "")

    def test_a_series_is_started_and_one_measure_at_a_time(self):
        started = []
        with mock.patch.object(A, "lancer_bench_serie", lambda models, quick: started.append((models, quick)) or {"ok": True, "modeles": models}):
            status, answer = V.call("POST", "/api/v1/bench", V.DEVICE, {"models": ["qwen3:8b", "gemma3:4b"], "quick": True})
            self.assertEqual((status, answer), (202, {"models": ["qwen3:8b", "gemma3:4b"]}))
            self.assertEqual(started, [(["qwen3:8b", "gemma3:4b"], True)])
            self.assertEqual(V.call("POST", "/api/v1/bench", V.DEVICE, {"models": []})[0], 400)
            with mock.patch.dict(A.BENCH, {"en_cours": "qwen3:8b"}):
                status, answer = V.call("POST", "/api/v1/bench", V.DEVICE, {"models": ["qwen3:8b"]})
            self.assertEqual((status, answer["error"]["code"]), (409, "busy"))
        self.assertEqual(len(started), 1)

    def test_a_model_that_is_not_installed_is_refused(self):
        with mock.patch.object(A, "moteur_local", lambda: mock.Mock(modeles=lambda: {"installes": ["qwen3:8b"]})):
            status, answer = V.call("POST", "/api/v1/bench", V.DEVICE, {"models": ["absent:1b"]})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertIn("absent:1b", answer["error"]["message"])


class Comparison(unittest.TestCase):
    SEEN = {"modele": "qwen3:8b", "a_refaire": False, "comparables": 2, "en_cours": False, "etape": "", "erreur": "",
            "disponibilite": [{"nom": "Ollama", "raison": "", "modele": "qwen3:8b"}, {"nom": "llama.cpp", "raison": "", "modele": "qwen3-8b.gguf"}],
            "recommandation": {"moteur": "llamacpp", "nom": "llama.cpp", "source": "banc", "raison": "plus rapide ici", "limites": ["un"], "theorique": False},
            "resultat": {"date": "2026-11-18", "mode": "rapide", "machine": "demo", "ignores": [{"id": "colibri", "nom": "Colibri", "raison": "absent"}],
                         "moteurs": [{"id": "ollama", "nom": "Ollama", "modele": "qwen3:8b", "version": "0.12", "ok": True, "passes": 3, "erreurs": [], "charge_s": 3.0,
                                      "premier_jeton_s": 0.4, "tok_s": 40.0, "lecture_tok_s": 800, "ram": 1, "vram": 2}]}}

    def test_the_comparison_is_read_in_english(self):
        with mock.patch.object(engine_bench, "vue", lambda *args: self.SEEN):
            status, answer = V.call("GET", "/api/v1/engines/comparison", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["recommendation"]["engine"], answer["result"]["mode"], answer["comparable"]), ("llamacpp", "quick", 2))
        self.assertEqual(answer["result"]["engines"][0]["tokens_per_s"], 40.0)
        self.assertEqual(answer["result"]["skipped"], [{"id": "colibri", "name": "Colibri", "reason": "absent"}])

    def test_only_this_machine_starts_it(self):
        launched = []
        with mock.patch.object(engine_bench, "vue", lambda *args: self.SEEN), mock.patch.object(engine_bench, "launch", lambda *args: launched.append(args)):
            self.assertEqual(V.call("POST", "/api/v1/engines/comparison", V.DEVICE, {"mode": "quick"})[0], 403)
            self.assertEqual(V.call("POST", "/api/v1/engines/comparison", V.OWNER, {"mode": "fast"})[0], 400)
            status, answer = V.call("POST", "/api/v1/engines/comparison", V.OWNER, {"mode": "deep"})
            self.assertEqual(status, 202, answer)
        self.assertEqual([args[1] for args in launched], ["approfondi"])


if __name__ == "__main__":
    unittest.main()
