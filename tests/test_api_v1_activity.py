"""`/api/v1/activity`: what Lutin is downloading or installing, in one list for the bar at the top of every screen (engine tasks, downloads of Ollama), on the real server of
tests/test_api_v1.py and a FAKE engine (nothing is installed or started)."""
import time
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, engines  # noqa: E402

A = V.A


class Fake(engines.Moteur):
    id, nom, genre, gere_modeles, description = "fake", "Fake engine", "openai", True, "An engine for the tests."


def setUpModule():
    V.setUpModule()


def items():
    status, body = V.call("GET", "/api/v1/activity", V.OWNER)
    assert status == 200, (status, body)
    return {item["id"]: item for item in body["items"]}


class Activity(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(engines.ENGINES, {"fake": Fake()})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: engines.TASKS.pop("fake", None))
        pulls = mock.patch.dict(api_v1._m.PULLS, clear=True)
        pulls.start()
        self.addCleanup(pulls.stop)

    def test_a_running_task_of_an_engine_is_listed_with_its_progress(self):
        engines.TASKS["fake"] = {"action": "installer", "statut": "en cours", "texte": "Downloading the model: 3 / 14 GB", "fait": 3, "total": 14, "erreur": "", "debut": time.time()}
        item = items()["engine:fake"]
        self.assertEqual((item["kind"], item["name"], item["action"], item["state"], item["done"], item["total"]), ("engine", "Fake engine", "install", "running", 3, 14))
        self.assertEqual(item["text"], "Downloading the model: 3 / 14 GB")

    def test_a_download_of_a_model_by_the_engine_names_the_model_and_the_engine(self):
        """Reported with ExLlamaV3: the progress of the download of a model was only on the page of the engines, nothing said where to look."""
        engines.TASKS["fake"] = {"action": "telecharger:turboderp/Qwen-exl3@4.0bpw", "statut": "en cours", "texte": "Downloading: 3,2 / 14,8 GB (21 %)", "fait": 3_200_000_000,
                                 "total": 14_800_000_000, "erreur": "", "debut": time.time()}
        item = items()["engine:fake"]
        self.assertEqual((item["action"], item["name"], item["done"], item["total"]), ("download", "turboderp/Qwen-exl3 (Fake engine)", 3_200_000_000, 14_800_000_000))

    def test_a_real_download_by_exllamav3_reaches_the_bar_with_its_progress(self):
        """Maintainer, 2026-11-21: « no status bar, no progress » for an ExLlamaV3 download. From the button of the models page to the bar: the engine task
        of ExLlamaV3 (an engine of its own, ADR 0020), the progress its downloader measures, the name of the model. Only the downloader is replaced."""
        import threading
        from lutin import exllamav3, managed_models
        gate = threading.Event()

        def download(depot, revision, dossiers, dire, annule=None, progres=None, **kwargs):
            progres(4_000_000_000, 16_000_000_000)
            dire("Téléchargement : 4,0 / 16,0 Go (25 %)")
            gate.wait(10)
        self.addCleanup(gate.set)
        self.addCleanup(lambda: engines.TASKS.pop("exllamav3", None))
        with mock.patch.object(exllamav3, "download_model", download), mock.patch.object(managed_models, "chosen", lambda kind: kind == "exllamav3"),                 mock.patch.dict(engines.CONTEXT, hors_ligne=lambda: False):
            managed_models.download("exllamav3", "turboderp/Qwen3.6-27B-exl3", "4.0bpw")
            for _ in range(100):
                item = items().get("engine:exllamav3")
                if item and item["done"]:
                    break
                time.sleep(0.05)
            gate.set()
            for _ in range(100):          # the task ends before the test cleans up after it
                if engines.TASKS.get("exllamav3", {}).get("statut") != "en cours":
                    break
                time.sleep(0.05)
        self.assertEqual((item["state"], item["action"], item["name"]), ("running", "download", "turboderp/Qwen3.6-27B-exl3 (ExLlamaV3)"))
        self.assertEqual((item["done"], item["total"]), (4_000_000_000, 16_000_000_000))
        self.assertIn("25 %", item["text"])

    def test_what_ended_stays_a_moment_and_then_goes(self):
        now = time.time()
        engines.TASKS["fake"] = {"action": "installer", "statut": "termine", "resultat": "Installed: Fake 1.0", "texte": "", "fait": 0, "total": 0, "fin": now}
        item = items()["engine:fake"]
        self.assertEqual((item["state"], item["text"]), ("done", "Installed: Fake 1.0"))
        engines.TASKS["fake"]["fin"] = now - engines.END_RESULT_S - 5
        self.assertNotIn("engine:fake", items(), "a success is kept 25 s")
        engines.TASKS["fake"].update(statut="erreur", erreur="No space left on the disk", fin=now - 60)
        item = items()["engine:fake"]
        self.assertEqual((item["state"], item["text"]), ("failed", "No space left on the disk"))
        engines.TASKS["fake"]["fin"] = now - engines.END_ERROR_S - 5
        self.assertNotIn("engine:fake", items(), "an error is kept longer, and then it goes too")

    def test_stopping_a_server_is_not_an_activity(self):
        engines.TASKS["fake"] = {"action": "arreter", "statut": "en cours", "texte": "", "fait": 0, "total": 0, "erreur": "", "debut": time.time()}
        self.assertNotIn("engine:fake", items())

    def test_a_download_of_a_model_by_ollama_is_listed_while_it_runs_or_when_it_failed(self):
        api_v1._m.PULLS.update({"qwen3:8b": {"statut": "en cours", "texte": "pulling", "fait": 5, "total": 10},
                                "old:1b": {"statut": "termine", "texte": "", "fait": 10, "total": 10},
                                "broken:7b": {"statut": "erreur", "texte": "no such model", "fait": 0, "total": 0}})
        listed = items()
        self.assertEqual((listed["model:qwen3:8b"]["state"], listed["model:qwen3:8b"]["done"], listed["model:qwen3:8b"]["total"]), ("running", 5, 10))
        self.assertEqual((listed["model:broken:7b"]["state"], listed["model:broken:7b"]["text"]), ("failed", "no such model"))
        self.assertNotIn("model:old:1b", listed, "a finished download is on the Models screen, not in the bar")

    def test_nothing_running_is_an_empty_list_and_a_visitor_without_session_is_refused(self):
        self.assertEqual([item for item in items() if item.startswith(("engine:fake", "model:"))], [])
        self.assertEqual(V.call("GET", "/api/v1/activity", {})[0], 401)


if __name__ == "__main__":
    unittest.main()
