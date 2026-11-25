"""`/api/v1/missions`: the long jobs, on the real server of tests/test_api_v1.py. The loop that carries a mission on is not started in tests: only the list and the actions are checked."""
import shutil
import tempfile
import unittest

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import mission  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Missions(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp(prefix="lutin-mission-folder-")
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        self.project = call("POST", "/api/v1/projects", {"path": folder, "name": "Mission folder"})[1]["projects"][-1]["id"]
        self.addCleanup(lambda: call("DELETE", "/api/v1/projects/" + self.project))
        self.addCleanup(lambda: [call("DELETE", "/api/v1/missions/" + entry["id"]) for entry in call("GET", "/api/v1/missions")[1]["missions"]])

    def start(self, **more):
        body = dict({"name": "Build a game", "brief": "Write a small game and test it.", "project": self.project}, **more)
        status, answer = call("POST", "/api/v1/missions", body)
        self.assertEqual(status, 201, answer)
        return answer

    def test_a_mission_is_started_listed_in_english_keys_and_its_brief_is_kept(self):
        started = self.start(hours=2, autonomous=False)
        self.assertEqual(sorted(started), ["actions", "autonomous", "brief", "conversation", "ended_at", "hours", "id", "log", "message", "name", "project_path", "question", "report", "started_at", "state", "turns"])
        self.assertEqual((started["state"], started["hours"], started["autonomous"], started["turns"]), ("running", 2, False, 0))
        listed = call("GET", "/api/v1/missions")[1]["missions"]
        self.assertEqual([entry["id"] for entry in listed], [started["id"]])
        self.assertEqual(listed[0]["brief"], "Write a small game and test it.")

    def test_pause_resume_reply_and_stop(self):
        identifier = self.start()["id"]

        def state(answer):
            return next(entry for entry in answer["missions"] if entry["id"] == identifier)["state"]

        self.assertEqual(state(call("POST", "/api/v1/missions/%s/pause" % identifier, {})[1]), "paused")
        self.assertEqual(state(call("POST", "/api/v1/missions/%s/resume" % identifier, {})[1]), "running")
        mission.modify(identifier, etat="bloquee", question="Which colour?")
        listed = call("GET", "/api/v1/missions")[1]["missions"][0]
        self.assertEqual((listed["state"], listed["question"]), ("blocked", "Which colour?"))
        answer = call("POST", "/api/v1/missions/%s/reply" % identifier, {"text": "Blue."})[1]
        self.assertEqual((state(answer), answer["missions"][0]["question"]), ("running", ""))
        answer = call("POST", "/api/v1/missions/%s/stop" % identifier, {})[1]
        self.assertEqual(state(answer), "done")
        self.assertTrue(answer["missions"][0]["report"])
        self.assertEqual(call("DELETE", "/api/v1/missions/" + identifier)[1], {"missions": []})

    def test_refused_requests_say_why(self):
        self.assertEqual(call("POST", "/api/v1/missions/nope/pause", {})[0], 404)
        self.assertEqual(call("DELETE", "/api/v1/missions/nope")[0], 404)
        identifier = self.start()["id"]
        self.assertEqual(call("POST", "/api/v1/missions/%s/reply" % identifier, {"text": "  "})[0], 400)
        self.assertEqual(call("POST", "/api/v1/missions/%s/reply" % identifier, {"words": "x"})[1]["error"]["code"], "invalid_request")
        for body in ({}, {"name": "x", "brief": "y"}, {"name": "x", "brief": "y", "project": self.project, "hours": "8"}, {"name": "x", "brief": "y", "project": self.project, "autonomous": "yes"},
                     {"name": "x", "brief": "y", "project": self.project, "colour": 1}):
            self.assertEqual(call("POST", "/api/v1/missions", body)[1]["error"]["code"], "invalid_request", body)
        status, answer = call("POST", "/api/v1/missions", {"name": "x", "brief": "y", "project": "no-such-project"})
        self.assertEqual(status, 400)
        self.assertTrue(answer["error"]["message"])
        status, answer = call("POST", "/api/v1/missions", {"name": "", "brief": "y", "project": self.project})
        self.assertEqual(status, 400)

    def test_at_most_five_unfinished_missions(self):
        for number in range(mission.MAX_MISSIONS):
            self.start(name="Mission %d" % number)
        status, answer = call("POST", "/api/v1/missions", {"name": "One too many", "brief": "y", "project": self.project})
        self.assertEqual(status, 400)
        self.assertTrue(answer["error"]["message"])

    def test_a_paired_device_may_follow_and_steer_but_not_start_or_delete(self):
        identifier = self.start()["id"]
        device = V.DEVICE
        self.assertEqual(call("GET", "/api/v1/missions", who=device)[0], 200)
        self.assertEqual(call("POST", "/api/v1/missions/%s/pause" % identifier, {}, who=device)[0], 200)
        self.assertEqual(call("POST", "/api/v1/missions", {"name": "x", "brief": "y", "project": self.project}, who=device)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/missions/" + identifier, who=device)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
