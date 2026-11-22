"""`/api/v1/background-jobs` (docs/modernization/PARITY.md, item 13): documents processed in the background, on the real server of tests/test_api_v1.py.

Hermetic: the jobs live in the temporary data folder of test_api_v1 and point at its temporary project folder; no model is called (the worker that
processes documents is not started by these routes)."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import background_jobs, workspaces

A = V.A


def setUpModule():
    V.setUpModule()


class BackgroundJobs(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(workspaces, "entries", lambda cfg: [{"id": "t0000001", "nom": "Projet", "chemin": str(A.ROOT)}])          # the project folder is a work folder
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: [background_jobs.action(job["id"], "supprimer") for job in background_jobs.list_works()])

    def create(self, **more):
        body = dict({"name": "Factures", "folder": str(A.ROOT), "patterns": "*.pdf, *.txt", "instruction": "Donne le montant total."}, **more)
        return V.call("POST", "/api/v1/background-jobs", V.OWNER, body)

    def test_a_job_is_created_listed_and_acted_on(self):
        status, answer = self.create(trial=True)
        self.assertEqual(status, 201, answer)
        job = answer["jobs"][0]
        self.assertEqual((job["name"], job["patterns"], job["state"], job["validated"]), ("Factures", ["*.pdf", "*.txt"], "waiting", False))
        base = "/api/v1/background-jobs/" + job["id"]
        self.assertEqual(V.call("GET", "/api/v1/background-jobs", V.DEVICE)[1]["jobs"][0]["id"], job["id"])
        self.assertEqual(V.call("POST", base + "/pause", V.OWNER, {})[1]["jobs"][0]["state"], "paused")
        self.assertEqual(V.call("POST", base + "/resume", V.OWNER, {})[1]["jobs"][0]["state"], "waiting")
        self.assertTrue(V.call("POST", base + "/validate", V.OWNER, {})[1]["jobs"][0]["validated"])
        self.assertIn("# Factures", V.call("GET", base + "/report", V.DEVICE)[1]["text"])
        self.assertEqual(V.call("POST", base + "/explode", V.OWNER, {})[0], 404)
        self.assertEqual(V.call("DELETE", base, V.OWNER)[1]["jobs"], [])
        self.assertEqual(V.call("DELETE", base, V.OWNER)[0], 404)

    def test_only_this_machine_creates_and_acts(self):
        self.assertEqual(V.call("POST", "/api/v1/background-jobs", V.DEVICE, {"name": "x"})[0], 403)
        job = self.create()[1]["jobs"][0]
        self.assertEqual(V.call("POST", "/api/v1/background-jobs/%s/pause" % job["id"], V.DEVICE, {})[0], 403)

    def test_what_cannot_be_a_job_is_refused(self):
        for more in ({"instruction": ""}, {"folder": "C:/nowhere/at/all"}, {"patterns": "*.pdf; rm -rf /"}):
            status, answer = self.create(**more)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), more)


if __name__ == "__main__":
    unittest.main()
