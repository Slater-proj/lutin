"""`/api/v1/projects`: the working folders, on the real server of tests/test_api_v1.py. The folders are temporary ones; the configuration file is the test one."""
import tempfile
import unittest
from pathlib import Path

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

A = V.A


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Projects(unittest.TestCase):
    def setUp(self):
        self.folders = []
        self.addCleanup(self.clean)

    def clean(self):
        for entry in call("GET", "/api/v1/projects")[1]["projects"]:
            if Path(entry["path"]).resolve() in [Path(f).resolve() for f in self.folders]:
                call("DELETE", "/api/v1/projects/" + entry["id"])

    def folder(self):
        path = tempfile.mkdtemp(prefix="lutin-project-")
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        self.folders.append(path)
        return path

    def test_a_folder_is_added_listed_selected_and_removed(self):
        path = self.folder()
        status, answer = call("POST", "/api/v1/projects", {"path": path, "name": "Demo"})
        self.assertEqual(status, 201)
        mine = [entry for entry in answer["projects"] if Path(entry["path"]).resolve() == Path(path).resolve()]
        self.assertEqual([(entry["name"], entry["usable"], entry["problem"]) for entry in mine], [("Demo", True, "")])
        identifier = mine[0]["id"]
        self.assertEqual(sorted(answer), ["current", "projects"])
        status, answer = call("POST", "/api/v1/projects/%s/select" % identifier, {})
        self.assertEqual((status, answer["current"]), (200, identifier))
        self.assertEqual(Path(A.RACINE).resolve(), Path(path).resolve(), "the working folder of the next conversations is the one chosen")
        status, answer = call("DELETE", "/api/v1/projects/" + identifier)
        self.assertEqual(status, 200)
        self.assertNotIn(Path(path).resolve(), [Path(entry["path"]).resolve() for entry in answer["projects"]])
        self.assertEqual(answer["copies_removed"], 0)
        self.assertTrue(Path(path).is_dir(), "taking a folder out of the list deletes nothing")

    def test_a_folder_that_does_not_exist_is_refused_with_the_reason(self):
        status, answer = call("POST", "/api/v1/projects", {"path": str(Path(tempfile.gettempdir()) / "lutin-nope-folder-xyz")})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertTrue(answer["error"]["message"])
        self.assertEqual(call("POST", "/api/v1/projects", {})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/api/v1/projects/nope/select", {})[1]["error"]["code"], "invalid_request")

    def test_a_paired_device_may_read_and_choose_but_not_add_or_remove(self):
        self.assertEqual(call("GET", "/api/v1/projects", who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/api/v1/projects", {"path": self.folder()}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/projects/x", who=V.DEVICE)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
