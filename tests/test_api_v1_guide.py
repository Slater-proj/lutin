"""The routes of the guided choice of a model (`/machine`, `/models/catalog`, `/models/recommendation`), on the real server of tests/test_api_v1.py and a FICTIVE machine
(`hardware.profil_demo`: a 12 GB graphics card, 32 GB of memory): the tests never depend on the hardware of the one who runs them."""
import time
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1  # noqa: E402
from lutin import hardware, model_fit  # noqa: E402

A = V.A
LEVELS = {"comfortable", "good", "tight", "too_big"}


def setUpModule():
    V.setUpModule()
    # The engine of this test answers nothing and asking it waits 2 s each time (the cost the routes pay on a first launch, where no engine runs yet): the tests do not wait.
    patch = mock.patch.object(A, "etat_moteur", return_value={"actif": False, "installes": [], "tailles": {}})
    patch.start()
    unittest.addModuleCleanup(patch.stop)


def known_machine():
    return mock.patch.dict(model_fit._etat, {"profil": hardware.profil_demo(), "quand": time.time(), "en_cours": False})


def unknown_machine():
    return mock.patch.dict(model_fit._etat, {"profil": None, "quand": 0.0, "en_cours": True})          # « detecting »: no thread is started, no hardware is read


def get(path):
    return V.call("GET", path, V.OWNER)


class Machine(unittest.TestCase):
    def test_while_the_machine_is_being_detected_the_answer_says_so_and_nothing_is_read(self):
        with unknown_machine():
            self.assertEqual(get("/api/v1/machine"), (200, {"detected": False}))

    def test_the_machine_in_figures(self):
        with known_machine():
            status, answer = get("/api/v1/machine")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(answer), ["architecture", "budget_gb", "budget_set_gb", "class", "cores", "cpu", "detected", "disks", "gpus", "ram_free_gb", "ram_gb", "summary", "system"])
        self.assertEqual((answer["detected"], answer["cpu"], answer["cores"], answer["ram_gb"], answer["class"], answer["budget_gb"]), (True, "AMD Ryzen 7 7700 8-Core Processor", 16, 32.0, "medium", 10.2))
        self.assertEqual(answer["gpus"], [{"name": "NVIDIA GeForce RTX 4070", "vendor": "nvidia", "memory_gb": 12.0, "free_gb": 10.6, "integrated": False}])
        self.assertEqual(answer["disks"], [{"path": "C:\\", "free_gb": 412.0, "total_gb": 931.0}])
        self.assertIn("RTX 4070", answer["summary"])


    def test_the_memory_given_to_models_can_be_corrected_by_hand_and_given_back_to_the_detection(self):
        self.addCleanup(V.call, "PATCH", "/api/v1/settings", V.OWNER, {"memory_budget_gb": 0})
        with known_machine():
            self.assertEqual(get("/api/v1/machine")[1]["budget_set_gb"], None)
            self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, {"memory_budget_gb": 6})[0], 200)
            answer = get("/api/v1/machine")[1]
            self.assertEqual((answer["budget_gb"], answer["budget_set_gb"]), (6.0, 6.0), "the figure given by the person replaces the one Lutin calculates")
            tight = [m for m in get("/api/v1/models/catalog")[1]["models"] if m["size_gb"] > 6.5 and m["fit"]]
            self.assertTrue(tight and all(m["fit"]["level"] in ("tight", "too_big") for m in tight), "the verdicts follow the corrected figure")
            self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, {"memory_budget_gb": 0})[0], 200)
            answer = get("/api/v1/machine")[1]
            self.assertEqual((answer["budget_gb"], answer["budget_set_gb"]), (10.2, None), "0 gives it back to the detection")


class Catalog(unittest.TestCase):
    def test_every_model_has_its_figures_a_verdict_for_this_machine_and_one_for_the_engine(self):
        with known_machine():
            status, answer = get("/api/v1/models/catalog")
        self.assertEqual((status, answer["detected"], sorted(answer)), (200, True, ["detected", "disclaimer", "models"]))
        self.assertTrue(answer["disclaimer"], "the catalogue says its notes are editorial estimates, not measures: the page must be able to say so")
        models = answer["models"]
        self.assertGreater(len(models), 20)
        self.assertEqual(len({model["id"] for model in models}), len(models))
        keys = ["active_parameters_b", "advanced", "capabilities", "compatibility", "context_max", "fit", "id", "installed", "licence", "name", "parameters_b", "roles", "size_gb", "summary", "warning"]
        for model in models:
            self.assertEqual(sorted(model), keys, model["id"])
            self.assertIn(model["fit"]["level"], LEVELS, model["id"])
            self.assertTrue(model["fit"]["text"], model["id"])
            self.assertEqual(sorted(model["compatibility"]), ["compatible", "memory_gb", "reasons", "warnings"])
            self.assertTrue(set(model["capabilities"]) <= {"tools", "thinking", "vision"}, model["capabilities"])
            self.assertFalse(model["installed"], "the engine of the test answers nothing: no model is installed")
        self.assertTrue(set(next(iter(models))["roles"]) <= {"general", "fast", "creative", "code", "images"})

    def test_the_verdict_is_the_one_of_model_fit_and_follows_the_size(self):
        with known_machine():
            models = get("/api/v1/models/catalog")[1]["models"]
            profile = hardware.profil_demo()
            mapping = api_v1.FIT_LEVELS
            for model in models:
                source = next(item for item in A._CATALOGUE["modeles"] if item["id"] == model["id"])
                self.assertEqual(model["fit"]["level"], mapping[model_fit.evaluer(source, profile)["niveau"]], model["id"])
        smallest = min(models, key=lambda model: model["size_gb"])
        biggest = max(models, key=lambda model: model["size_gb"])
        self.assertEqual(smallest["fit"]["level"], "comfortable", "a model of 1 or 2 GB on a 12 GB card")
        self.assertEqual(biggest["fit"]["level"], "too_big", "the biggest of the catalogue on a 12 GB card")

    def test_without_the_machine_there_is_no_verdict_and_the_models_are_still_listed(self):
        with unknown_machine():
            answer = get("/api/v1/models/catalog")[1]
        self.assertFalse(answer["detected"])
        self.assertTrue(all(model["fit"] is None for model in answer["models"]))
        self.assertGreater(len(answer["models"]), 20)

    def test_advanced_models_appear_only_when_asked(self):
        with known_machine():
            plain = get("/api/v1/models/catalog")[1]["models"]
            everything = get("/api/v1/models/catalog?advanced=1")[1]["models"]
        self.assertFalse(any(model["advanced"] for model in plain))
        self.assertGreaterEqual(len(everything), len(plain))
        self.assertEqual(len(everything) - len(plain), sum(1 for model in A._CATALOGUE["modeles"] if model.get("avance")))


class Recommendation(unittest.TestCase):
    def test_each_use_gets_a_model_that_fits_with_what_the_download_would_cost(self):
        with known_machine():
            catalog = {model["id"]: model for model in get("/api/v1/models/catalog")[1]["models"]}
            for use in ("chat", "code", "documents", "unsure"):
                status, answer = get("/api/v1/models/recommendation?use=" + use)
                self.assertEqual((status, answer["detected"], answer["use"]), (200, True, use), use)
                self.assertEqual(sorted(answer), ["alternatives", "detected", "download", "engine", "offline", "recommended", "use"], use)
                recommended = answer["recommended"]
                self.assertEqual(sorted(recommended), ["context_tokens", "memory_gb", "model", "role", "runs_on"], use)
                self.assertEqual(recommended["model"], catalog[recommended["model"]["id"]], "the same entry as the catalogue, same verdict")
                self.assertIn(recommended["model"]["fit"]["level"], ("comfortable", "good", "tight"), "never a model that is too big")
                self.assertIn(recommended["runs_on"], ("gpu", "partial", "cpu"))
                self.assertEqual(answer["download"]["models"], [recommended["model"]["id"]])
                self.assertEqual(answer["download"]["size_gb"], round(recommended["model"]["size_gb"], 1))
                self.assertEqual(sorted(answer["download"]), ["fits_on_disk", "free_gb", "models", "size_gb"])
                self.assertEqual(sorted(answer["engine"]), ["id", "name", "running"])
                self.assertNotIn(recommended["model"]["id"], [other["model"]["id"] for other in answer["alternatives"]], "an alternative is another model")

    def test_the_use_changes_the_role(self):
        with known_machine():
            code = get("/api/v1/models/recommendation?use=code")[1]["recommended"]
            chat = get("/api/v1/models/recommendation?use=chat")[1]["recommended"]
        self.assertEqual((code["role"], chat["role"]), ("code", "general"))

    def test_a_model_already_installed_costs_nothing(self):
        with known_machine():
            wanted = get("/api/v1/models/recommendation?use=chat")[1]["recommended"]["model"]["id"]
            with mock.patch.object(A, "etat_moteur", return_value={"actif": True, "installes": [wanted], "tailles": {}}):
                answer = get("/api/v1/models/recommendation?use=chat")[1]
        self.assertEqual((answer["download"]["models"], answer["download"]["size_gb"], answer["engine"]["running"]), ([], 0.0, True))

    def test_the_disk_is_taken_into_account(self):
        with known_machine(), mock.patch.object(api_v1._health, "disk_space", return_value={"total": 10 * 1024 ** 3, "libre": 1024 ** 3, "racine": "C:\\"}):
            answer = get("/api/v1/models/recommendation?use=chat")[1]
        self.assertEqual((answer["download"]["free_gb"], answer["download"]["fits_on_disk"]), (1.0, answer["download"]["size_gb"] <= 1.0))
        with known_machine(), mock.patch.object(api_v1._health, "disk_space", return_value=None):
            answer = get("/api/v1/models/recommendation?use=chat")[1]
        self.assertEqual((answer["download"]["free_gb"], answer["download"]["fits_on_disk"]), (None, None), "a disk that cannot be reached is said, not guessed")

    def test_strict_offline_mode_is_reported_before_any_download_is_offered(self):
        with known_machine(), mock.patch.object(api_v1._offline, "is_active", return_value=True):
            self.assertTrue(get("/api/v1/models/recommendation?use=chat")[1]["offline"])

    def test_refusals_and_the_machine_not_ready(self):
        self.assertEqual(get("/api/v1/models/recommendation?use=poetry"), (400, {"error": {"code": "invalid_request", "message": "Valeur invalide pour « use » (attendu : chat, code, documents, unsure)."}}))
        with unknown_machine():
            self.assertEqual(get("/api/v1/models/recommendation?use=code"), (200, {"detected": False, "use": "code"}))

    def test_nothing_is_downloaded_by_asking(self):
        with known_machine(), mock.patch.object(A, "installer_modele") as install:
            get("/api/v1/models/recommendation?use=chat")
            get("/api/v1/models/catalog")
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
