"""The engine settings of `/api/v1` (docs/modernization/PARITY.md, item 11): an engine's settings, the engines' folder, the measure of an engine, Ollama's
models folder, the calibration of the cores and the advice for a small machine, on the real server of tests/test_api_v1.py.

Hermetic: the functions underneath that read or change the machine (engine configuration, folders, measures, Ollama) are replaced; what is checked is
the v1 contract: rights, English names, refusals, and what reaches those functions."""
import time
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import calibration, engine_metrics, hardware, llamacpp_engine, locations, low_end_mode, model_fit

A = V.A


def setUpModule():
    V.setUpModule()


class EngineSettings(unittest.TestCase):
    def test_the_settings_are_read_without_the_key(self):
        seen = {"url": "http://127.0.0.1:8080", "cle_definie": True, "variante": "vulkan",
                "avance": {"routeur": True, "routeur_possible": True, "modeles_max": 2, "n_cpu_moe": 0, "n_cpu_moe_possible": False, "version_epinglee": "b6500"}}
        with mock.patch.object(llamacpp_engine, "vue_reglages", lambda engine: seen):
            status, answer = V.call("GET", "/api/v1/engines/llamacpp/settings", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["key_set"], answer["variant"], answer["advanced"]["pinned_version"], answer["advanced"]["models_kept"]), (True, "vulkan", "b6500", 2))
        self.assertNotIn("cle", answer)
        self.assertEqual(V.call("GET", "/api/v1/engines/nothing/settings", V.DEVICE)[0], 404)

    def test_a_change_reaches_the_engine_under_its_stored_names(self):
        applied = []
        with mock.patch.object(llamacpp_engine, "apply_settings", lambda engine, data: applied.append((engine.id, data))), \
                mock.patch.object(llamacpp_engine, "vue_reglages", lambda engine: {}):
            self.assertEqual(V.call("PATCH", "/api/v1/engines/llamacpp/settings", V.DEVICE, {"router": True})[0], 403)
            status, answer = V.call("PATCH", "/api/v1/engines/llamacpp/settings", V.OWNER, {"router": True, "models_kept": 3, "pinned_version": "", "key": "secret"})
            self.assertEqual(status, 200, answer)
            self.assertEqual(V.call("PATCH", "/api/v1/engines/llamacpp/settings", V.OWNER, {"colour": "blue"})[0], 400)
        self.assertEqual(applied, [("llamacpp", {"routeur": True, "modeles_max": 3, "version_epinglee": "", "cle": "secret"})])

    def test_a_refusal_of_the_engine_is_a_400_with_its_sentence(self):
        status, answer = V.call("PATCH", "/api/v1/engines/llamacpp/settings", V.OWNER, {"models_kept": 99})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertIn("8", answer["error"]["message"])

    def test_the_engines_folder_changes_only_when_nothing_is_installed_there(self):
        seen = {"actuel": "C:/IA/moteurs", "defaut": "C:/IA/moteurs", "propose": "D:/IA/moteurs", "libre_go": 20.0, "libre_go_propose": 800.0, "source": "defaut", "probleme": "",
                "docker": False, "montage": "", "modifiable": True, "personnalise": False, "installes": ["llama.cpp"], "sous_dossiers": ["ollama", "llamacpp"]}
        with mock.patch.object(llamacpp_engine, "vue_dossier_moteurs", lambda: seen):
            status, answer = V.call("GET", "/api/v1/engines/folder", V.DEVICE)
            self.assertEqual((status, answer["proposed"], answer["installed_here"], answer["source"]), (200, "D:/IA/moteurs", ["llama.cpp"], "default"))
            with mock.patch.object(llamacpp_engine, "moteurs_installes_par_lutin", lambda: ["llama.cpp"]):
                status, answer = V.call("PATCH", "/api/v1/engines/folder", V.OWNER, {"path": "D:/IA/moteurs"})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertIn("llama.cpp", answer["error"]["message"])


class Measures(unittest.TestCase):
    def test_the_ranking_and_a_measure_started(self):
        seen = {"etat": {"en_cours": False, "moteur": "", "modele": "", "erreur": ""}, "nombre": 1, "candidats": [{"moteur": "ollama", "nom": "Ollama", "modele": "qwen3:8b", "modeles": ["qwen3:8b"]}],
                "classement": [{"moteur": "ollama", "nom": "Ollama", "modele": "qwen3:8b", "date": "2026-11-18 10:00", "mode": "rapide", "ok": True, "tok_s": 41.0, "rang": 1}]}
        launched = []
        with mock.patch.object(engine_metrics, "view", lambda *args: seen), mock.patch.object(engine_metrics, "launch", lambda *args, **kwargs: launched.append(args[1:4])):
            status, answer = V.call("GET", "/api/v1/engines/measures", V.DEVICE)
            self.assertEqual((answer["ranking"][0]["tokens_per_s"], answer["ranking"][0]["rank"], answer["candidates"][0]["model"]), (41.0, 1, "qwen3:8b"))
            self.assertEqual(V.call("POST", "/api/v1/engines/ollama/measure", V.DEVICE, {"model": "qwen3:8b"})[0], 403)
            status, answer = V.call("POST", "/api/v1/engines/ollama/measure", V.OWNER, {"model": "qwen3:8b", "mode": "deep"})
            self.assertEqual(status, 202, answer)
            with mock.patch.dict(engine_metrics.STATE, {"en_cours": True}):
                self.assertEqual(V.call("POST", "/api/v1/engines/ollama/measure", V.OWNER, {"model": "qwen3:8b"})[1]["error"]["code"], "busy")
        self.assertEqual([(engine.id, model, mode) for engine, model, mode in launched], [("ollama", "qwen3:8b", "approfondi")])


class ModelsFolder(unittest.TestCase):
    def test_the_folder_is_analysed_copied_and_chosen(self):
        analysed = {"chemin": "D:/IA/ollama", "reseau": False, "debit": 900, "avertissements": [], "libre": 10 ** 12, "existe": True, "modeles_ici": False,
                    "source": "C:/Users/x/.ollama/models", "source_existe": True, "source_octets": 5 * 10 ** 9}
        chosen, copied = [], []
        with mock.patch.object(locations, "analyze_folder", lambda path: analysed), mock.patch.object(locations, "copy_models", lambda path: copied.append(path)), \
                mock.patch.object(locations, "set_models_folder", lambda path: chosen.append(path) or path), mock.patch.object(locations, "models_gauge", lambda: {"libre": 1, "total": 2}):
            status, answer = V.call("GET", "/api/v1/models/folder", V.DEVICE)
            self.assertEqual((status, answer["copy"]["state"]), (200, "idle"))
            self.assertEqual(V.call("POST", "/api/v1/models/folder/analysis", V.DEVICE, {"path": "D:/IA/ollama"})[0], 403)
            status, answer = V.call("POST", "/api/v1/models/folder/analysis", V.OWNER, {"path": "D:/IA/ollama"})
            self.assertEqual((answer["network"], answer["source_bytes"], answer["models_here"]), (False, 5 * 10 ** 9, False))
            self.assertEqual(V.call("POST", "/api/v1/models/folder/copy", V.OWNER, {"path": "D:/IA/ollama"})[0], 202)
            self.assertEqual(V.call("PATCH", "/api/v1/models/folder", V.OWNER, {"path": "D:/IA/ollama"})[0], 200)
        self.assertEqual((copied, chosen), (["D:/IA/ollama"], ["D:/IA/ollama"]))

    def test_ollama_is_not_restarted_during_an_answer(self):
        with mock.patch.dict(A.TOURS_ACTIFS, {"conversation": object()}):
            status, answer = V.call("POST", "/api/v1/models/folder/restart-ollama", V.OWNER, {})
        self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))


class CalibrationAndAdvice(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(model_fit._state, {"profil": hardware.profil_demo(), "quand": time.time() + 3600, "en_cours": False})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_calibration_is_read_started_and_applied(self):
        done = {"en_cours": False, "etape": "", "erreur": "", "resultats": [{"fils": 4, "tok_s": 10.0}, {"fils": 8, "tok_s": 12.0}], "recommande": 8, "modele": "qwen3:8b", "date": "x"}
        calls = []
        with mock.patch.object(calibration, "state", lambda: done), mock.patch.object(calibration, "start", lambda: calls.append("start")), \
                mock.patch.object(calibration, "apply", lambda: calls.append("apply")), mock.patch.object(calibration, "cancel", lambda: calls.append("cancel")):
            status, answer = V.call("GET", "/api/v1/calibration", V.DEVICE)
            self.assertEqual((answer["advised_threads"], answer["results"][1]), (8, {"threads": 8, "tokens_per_s": 12.0}))
            self.assertEqual(V.call("POST", "/api/v1/calibration", V.DEVICE, {})[0], 403)
            self.assertEqual(V.call("POST", "/api/v1/calibration", V.OWNER, {})[0], 202)
            self.assertEqual(V.call("POST", "/api/v1/calibration/apply", V.OWNER, {})[0], 200)
            self.assertEqual(V.call("DELETE", "/api/v1/calibration", V.OWNER)[0], 200)
        self.assertEqual(calls, ["start", "apply", "cancel"])

    def test_the_advice_of_a_small_machine_speaks_v1_names(self):
        advice = [{"cle": "num_ctx", "actuel": 32768, "conseille": 8192, "texte": "Moins de mémoire."}, {"cle": "reflexion", "actuel": True, "conseille": False, "texte": "Plus rapide."}]
        saved = []
        with mock.patch.object(low_end_mode, "advice", lambda profile, settings: advice), mock.patch.object(A, "enregistrer_reglages", lambda changes: saved.append(changes)):
            status, answer = V.call("GET", "/api/v1/machine/advice", V.DEVICE)
            self.assertEqual([(a["setting"], a["advised"]) for a in answer["advice"]], [("num_ctx", 8192), ("thinking", False)])
            status, answer = V.call("POST", "/api/v1/machine/advice/apply", V.OWNER, {})
            self.assertEqual(answer["applied"], {"num_ctx": 8192, "thinking": False})
            self.assertEqual(V.call("POST", "/api/v1/machine/advice/dismiss", V.OWNER, {})[1], {"dismissed": True})
        self.assertEqual(saved, [{"num_ctx": 8192, "reflexion": False}, {"conseil_machine": False}])


if __name__ == "__main__":
    unittest.main()
