"""`/api/v1/scheduled-tasks`: the scheduled tasks, on the real server of tests/test_api_v1.py. The task file is the one of the test data folder; nothing is run."""
import unittest
from datetime import datetime, timedelta
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import scheduled_tasks  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


NEW = {"name": "Morning summary", "request": "Summarise my notes", "time": "08:30", "days": [0, 1, 2]}


class Tasks(unittest.TestCase):
    def setUp(self):
        for task in scheduled_tasks.read():
            scheduled_tasks.remove(task["id"])
        self.addCleanup(lambda: [scheduled_tasks.remove(task["id"]) for task in scheduled_tasks.read()])

    def test_a_task_is_added_listed_changed_paused_and_deleted(self):
        status, task = call("POST", "/api/v1/scheduled-tasks", NEW)
        self.assertEqual(status, 201)
        self.assertEqual((task["name"], task["request"], task["time"], task["days"], task["active"], task["last_state"], task["running"]), ("Morning summary", "Summarise my notes", "08:30", [0, 1, 2], True, "never", False))
        self.assertRegex(task["next_run"], r"^\d{4}-\d\d-\d\dT08:30$")
        self.assertEqual([item["id"] for item in call("GET", "/api/v1/scheduled-tasks")[1]["tasks"]], [task["id"]])
        status, changed = call("PATCH", "/api/v1/scheduled-tasks/" + task["id"], {"time": "09:15", "name": "Later"})
        self.assertEqual((status, changed["time"], changed["name"], changed["request"], changed["days"]), (200, "09:15", "Later", "Summarise my notes", [0, 1, 2]), "what is not named stays")
        status, paused = call("PATCH", "/api/v1/scheduled-tasks/" + task["id"], {"active": False})
        self.assertEqual((status, paused["active"], paused["next_run"]), (200, False, ""), "a paused task has no next run")
        status, answer = call("DELETE", "/api/v1/scheduled-tasks/" + task["id"])
        self.assertEqual((status, answer), (200, {"tasks": []}))

    def test_a_single_run_on_a_date_and_the_refusals_that_say_why(self):
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        status, task = call("POST", "/api/v1/scheduled-tasks", {"name": "Once", "request": "Remind me", "time": "07:00", "date": tomorrow})
        self.assertEqual((status, task["date"], task["next_run"]), (201, tomorrow, tomorrow + "T07:00"))
        for body in ({}, {"name": "x", "request": "y", "time": "25:00", "days": [1]}, {"name": "x", "request": "y", "time": "08:00", "days": []},
                     {"name": "x", "request": "y", "time": "08:00", "date": "2001-01-01"}, dict(NEW, nope=1)):
            status, answer = call("POST", "/api/v1/scheduled-tasks", body)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), body)
        self.assertEqual(call("PATCH", "/api/v1/scheduled-tasks/" + task["id"], {})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("PATCH", "/api/v1/scheduled-tasks/" + task["id"], {"active": "yes"})[1]["error"]["code"], "invalid_request")
        for method, path in (("PATCH", ""), ("DELETE", ""), ("POST", "/run"), ("POST", "/stop")):
            self.assertEqual(call(method, "/api/v1/scheduled-tasks/nope" + path, {"active": True} if method == "PATCH" else None)[1]["error"]["code"], "not_found", method + path)

    def test_a_task_is_run_now_in_the_background_and_a_task_that_is_not_at_work_cannot_be_stopped(self):
        task = call("POST", "/api/v1/scheduled-tasks", NEW)[1]
        ran = []
        with mock.patch.object(scheduled_tasks, "execute", side_effect=lambda identifier: ran.append(identifier)):
            self.assertEqual(call("POST", "/api/v1/scheduled-tasks/%s/run" % task["id"], {}), (202, {"started": True}))
            for _ in range(100):
                if ran:
                    break
                __import__("time").sleep(0.02)
        self.assertEqual(ran, [task["id"]])
        status, answer = call("POST", "/api/v1/scheduled-tasks/%s/stop" % task["id"], {})
        self.assertEqual(status, 400, "it does not work now: refused with the reason")
        with mock.patch.dict(scheduled_tasks.RUNNING, {task["id"]: mock.Mock()}):
            self.assertEqual(call("POST", "/api/v1/scheduled-tasks/%s/run" % task["id"], {})[1]["error"]["code"], "busy")
            self.assertEqual(call("POST", "/api/v1/scheduled-tasks/%s/stop" % task["id"], {}), (200, {"stopped": True}))
            self.assertEqual(call("GET", "/api/v1/scheduled-tasks")[1]["tasks"][0]["running"], True)

    def test_the_states_of_a_run_are_translated_and_the_history_is_kept(self):
        task = call("POST", "/api/v1/scheduled-tasks", NEW)[1]
        scheduled_tasks.modify(task["id"], derniere_etat="erreur", derniere_erreur="boom", historique=[{"date": "2026-01-01T08:30:00", "etat": "arretee", "duree_s": 4, "erreur": ""}])
        shown = call("GET", "/api/v1/scheduled-tasks")[1]["tasks"][0]
        self.assertEqual((shown["last_state"], shown["last_error"]), ("failed", "boom"))
        self.assertEqual(shown["history"], [{"at": "2026-01-01T08:30:00", "state": "stopped", "seconds": 4, "error": ""}])
        scheduled_tasks.modify(task["id"], derniere_etat="en_cours")
        self.assertEqual(call("GET", "/api/v1/scheduled-tasks")[1]["tasks"][0]["last_state"], "interrupted", "a run that was cut by a stop of Lutin says so")

    def test_a_paired_device_may_read_but_not_manage(self):
        self.assertEqual(call("GET", "/api/v1/scheduled-tasks", who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/api/v1/scheduled-tasks", NEW, who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/scheduled-tasks/x", who=V.DEVICE)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
