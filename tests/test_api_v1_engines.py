"""`/api/v1/engines`: the state of the engines, the actions that are possible, and the tasks, on the real server of tests/test_api_v1.py and a FAKE engine (nothing is installed or started)."""
import threading
import time
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, engines  # noqa: E402

A = V.A


class Fake(engines.Moteur):
    id, nom, genre, gere_modeles, description = "fake", "Fake engine", "openai", True, "An engine for the tests."

    def __init__(self):
        self.done, self.gate = [], threading.Event()
        self.gate.set()

    def actif(self):
        return True

    def modeles(self):
        return {"actif": True, "installes": ["m1", "m2"], "tailles": {}}

    def statut(self):
        return {"installe": True, "actif": True, "version": "1.2.3", "detail": ""}

    def actions(self):
        return {"installer": {"possible": True, "raison": "Downloads 120 MB and installs it."}, "desinstaller": {"possible": True, "raison": "Removes it."},
                "reinstaller": {"possible": True, "raison": ""}, "demarrer": {"possible": True, "raison": ""}, "arreter": {"possible": False, "raison": "Nothing to stop."},
                "mettre_a_jour": {"possible": True, "raison": ""}}

    def faire(self, action, progression):
        progression("working", 1, 2)
        self.gate.wait(10)
        self.done.append(action)


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body=body)


class Engines(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        patch = mock.patch.dict(engines.MOTEURS, {"fake": self.fake})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: engines.TACHES.pop("fake", None))

    def listing(self):
        """The list of the fake engine alone: the real ones, which do not answer here, would make every reading wait 2 s."""
        with mock.patch.object(engines, "liste", return_value=[self.fake]):
            return call("GET", "/api/v1/engines")[1]["engines"]

    def finished(self):
        for _ in range(100):
            task = next(entry for entry in self.listing() if entry["id"] == "fake")["task"]
            if task and task["state"] != "running":
                return task
            time.sleep(0.05)
        self.fail("the task did not finish")

    def test_the_list_gives_each_engine_its_state_and_what_it_allows(self):
        status, answer = call("GET", "/api/v1/engines")
        self.assertEqual((status, sorted(answer), answer["current"]), (200, ["current", "engines"], A.moteur_actuel().id))
        fake = next(entry for entry in answer["engines"] if entry["id"] == "fake")
        self.assertEqual(sorted(fake), ["actions", "current", "description", "detail", "id", "installed", "kind", "manages_models", "models_count", "name", "running", "strengths", "task", "version", "weaknesses"])
        self.assertEqual((fake["name"], fake["running"], fake["installed"], fake["version"], fake["models_count"], fake["task"], fake["current"]), ("Fake engine", True, True, "1.2.3", 2, None, False))
        self.assertEqual(sorted(fake["actions"]), ["install", "reinstall", "start", "stop", "uninstall", "update"])
        self.assertEqual(fake["actions"]["stop"], {"possible": False, "reason": "Nothing to stop."})
        self.assertEqual(fake["actions"]["install"], {"possible": True, "reason": "Downloads 120 MB and installs it."})
        self.assertIn("ollama", [entry["id"] for entry in answer["engines"]])
        self.assertEqual([entry["id"] for entry in answer["engines"] if entry["current"]], [answer["current"]])

    def test_starting_runs_in_the_background_and_the_list_follows_it(self):
        self.fake.gate.clear()
        status, task = call("POST", "/api/v1/engines/fake/actions/start", {})
        self.assertEqual((status, task["action"], task["state"]), (202, "start", "running"))
        listed = next(entry for entry in self.listing() if entry["id"] == "fake")["task"]
        self.assertEqual((listed["state"], listed["text"], listed["done"], listed["total"]), ("running", "working", 1, 2))
        self.fake.gate.set()
        self.assertEqual(self.finished()["state"], "done")
        self.assertEqual(self.fake.done, ["demarrer"])

    def test_what_changes_the_machine_needs_an_explicit_confirmation(self):
        for action in ("install", "uninstall", "reinstall", "update"):
            status, answer = call("POST", "/api/v1/engines/fake/actions/" + action, {})
            self.assertEqual((status, answer["error"]["code"]), (400, "confirmation_required"), action)
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/install", {})[1]["error"]["message"], "Downloads 120 MB and installs it.", "what it does is said")
        self.assertEqual(self.fake.done, [], "nothing ran without the confirmation")
        with mock.patch.object(api_v1._offline, "is_active", return_value=False):          # the server of these tests is in strict offline mode, which refuses an install (next test)
            status, task = call("POST", "/api/v1/engines/fake/actions/install", {"confirm": True})
        self.assertEqual((status, task["action"]), (202, "install"))
        self.assertEqual(self.finished()["state"], "done")
        self.assertEqual(self.fake.done, ["installer"])

    def test_strict_offline_mode_refuses_what_needs_the_network_and_only_that(self):
        with mock.patch.object(api_v1._offline, "is_active", return_value=True):
            for action in ("install", "reinstall", "update"):
                status, answer = call("POST", "/api/v1/engines/fake/actions/" + action, {"confirm": True})
                self.assertEqual((status, answer["error"]["code"]), (409, "offline"), action)
            self.assertEqual(call("POST", "/api/v1/engines/fake/actions/start", {})[0], 202)
        self.assertEqual(self.finished()["state"], "done")
        self.assertEqual(self.fake.done, ["demarrer"])

    def test_refusals_carry_a_code(self):
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/stop", {}), (400, {"error": {"code": "action_impossible", "message": "Nothing to stop."}}))
        self.assertEqual(call("POST", "/api/v1/engines/nope/actions/start", {})[1]["error"]["code"], "not_found")
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/explode", {})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/start", {"confirm": "yes"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/start", {"force": True})[1]["error"]["code"], "invalid_request")
        self.assertEqual(self.fake.done, [])

    def test_one_task_at_a_time_and_a_task_can_be_cancelled(self):
        self.fake.gate.clear()
        self.assertEqual(call("DELETE", "/api/v1/engines/fake/task"), (200, {"cancelled": False}))
        call("POST", "/api/v1/engines/fake/actions/start", {})
        status, answer = call("POST", "/api/v1/engines/fake/actions/start", {})
        self.assertEqual((status, answer["error"]["code"]), (409, "task_running"))
        self.assertEqual(call("DELETE", "/api/v1/engines/fake/task"), (200, {"cancelled": True}))
        self.fake.gate.set()
        self.finished()
        self.assertEqual(call("DELETE", "/api/v1/engines/nope/task")[1]["error"]["code"], "not_found")

    def test_a_paired_device_may_read_but_not_act(self):
        self.assertEqual(call("GET", "/api/v1/engines", who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/api/v1/engines/fake/actions/start", {}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/engines/fake/task", who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(self.fake.done, [])

    def test_an_engine_that_cannot_be_read_does_not_hide_the_others(self):
        with mock.patch.object(self.fake, "statut", side_effect=OSError("down")):
            listed = call("GET", "/api/v1/engines")[1]["engines"]          # the real list: the other engines are there too
        fake = next(entry for entry in listed if entry["id"] == "fake")
        self.assertEqual((fake["running"], fake["installed"]), (False, False))
        self.assertGreater(len(listed), 2)


if __name__ == "__main__":
    unittest.main()
