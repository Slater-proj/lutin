"""`/api/v1/projects`: the working folders, on the real server of tests/test_api_v1.py. The folders are temporary ones; the configuration file is the test one."""
import tempfile
import urllib.parse
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
        self.assertEqual(Path(A.ROOT).resolve(), Path(path).resolve(), "the working folder of the next conversations is the one chosen")
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

    def test_the_folder_browser_lists_sub_folders_only_and_goes_up(self):
        path = self.folder()
        (Path(path) / "beta").mkdir()
        (Path(path) / "Alpha").mkdir()
        (Path(path) / "a file.txt").write_text("x", encoding="utf-8")
        status, answer = call("GET", "/api/v1/projects/folders?path=" + urllib.parse.quote(path))
        self.assertEqual(status, 200)
        self.assertEqual([entry["name"] for entry in answer["folders"]], ["Alpha", "beta"], "folders only, sorted without regard to case")
        self.assertEqual(Path(answer["parent"]).resolve(), Path(path).resolve().parent)
        self.assertIn("path", answer["folders"][0])
        status, answer = call("GET", "/api/v1/projects/folders")
        self.assertEqual((status, answer["parent"]), (200, None), "no path: the starting points, nothing above")
        self.assertTrue(answer["folders"])
        status, answer = call("GET", "/api/v1/projects/folders?path=" + urllib.parse.quote(str(Path(path) / "missing")))
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

    def test_a_paired_device_may_not_browse_the_disk(self):
        self.assertEqual(call("GET", "/api/v1/projects/folders", who=V.DEVICE)[1]["error"]["code"], "configurator")

    def test_a_paired_device_may_read_and_choose_but_not_add_or_remove(self):
        self.assertEqual(call("GET", "/api/v1/projects", who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/api/v1/projects", {"path": self.folder()}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/projects/x", who=V.DEVICE)[1]["error"]["code"], "configurator")


class ClaudeProjects(unittest.TestCase):
    """`/api/v1/projects/claude` and `/api/v1/projects/import-claude`: a folder made for Claude (CLAUDE.md, `.claude/`) taken up in place or as a copy."""

    setUp = Projects.setUp
    clean = Projects.clean
    folder = Projects.folder

    def claude_folder(self):
        path = self.folder()
        Path(path, "CLAUDE.md").write_text("# Notes\nUse tabs.\n", encoding="utf-8")
        skill = Path(path, ".claude", "skills", "review")
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: review\ndescription: Review a change\n---\nLook at the diff.\n", encoding="utf-8")
        command = Path(path, ".claude", "commands")
        command.mkdir(parents=True)
        (command / "ship.md").write_text("Ship it.\n", encoding="utf-8")
        return path

    def test_a_claude_folder_is_looked_at_without_writing_anything(self):
        path = self.claude_folder()
        status, answer = call("GET", "/api/v1/projects/claude?path=" + urllib.parse.quote(path))
        self.assertEqual(status, 200)
        self.assertEqual((answer["is_claude_project"], answer["found"]["context"]), (True, ["CLAUDE.md"]))
        self.assertEqual([(skill["name"], skill["description"]) for skill in answer["found"]["skills"]], [("review", "Review a change")])
        self.assertEqual([command["name"] for command in answer["found"]["commands"]], ["ship"])
        self.assertEqual(sorted(answer["found"]), ["agents", "commands", "context", "rules", "skills"])
        self.assertIn("CLAUDE.md", answer["summary"])
        self.assertNotIn(Path(path).resolve(), [Path(entry["path"]).resolve() for entry in call("GET", "/api/v1/projects")[1]["projects"]], "looking adds nothing to the list")
        plain = call("GET", "/api/v1/projects/claude?path=" + urllib.parse.quote(self.folder()))[1]
        self.assertEqual((plain["is_claude_project"], plain["summary"]), (False, ""))
        self.assertEqual(call("GET", "/api/v1/projects/claude")[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("GET", "/api/v1/projects/claude?path=" + urllib.parse.quote(str(Path(path) / "missing")))[1]["error"]["code"], "invalid_request")

    def test_it_is_taken_up_in_place_and_becomes_the_current_folder(self):
        path = self.claude_folder()
        status, answer = call("POST", "/api/v1/projects/import-claude", {"path": path, "mode": "in_place", "name": "Claude one"})
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["mode"], answer["selected"]), ("in_place", True))
        self.assertEqual(Path(answer["path"]).resolve(), Path(path).resolve())
        self.assertIn("CLAUDE.md", answer["summary"])
        mine = [entry for entry in answer["projects"] if Path(entry["path"]).resolve() == Path(path).resolve()]
        self.assertEqual([entry["name"] for entry in mine], ["Claude one"])
        self.assertEqual(answer["current"], mine[0]["id"])

    def test_a_copy_leaves_the_original_alone(self):
        path = self.claude_folder()
        target = Path(self.folder(), "copy")
        status, answer = call("POST", "/api/v1/projects/import-claude", {"path": path, "mode": "copy", "to": str(target)})
        self.assertEqual(status, 200, answer)
        self.folders.append(str(target))
        self.assertEqual(Path(answer["path"]).resolve(), target.resolve())
        self.assertTrue((target / "CLAUDE.md").is_file() and (target / ".claude" / "skills" / "review" / "SKILL.md").is_file())
        self.assertEqual(Path(path, "CLAUDE.md").read_text(encoding="utf-8"), "# Notes\nUse tabs.\n")
        self.assertNotIn(Path(path).resolve(), [Path(entry["path"]).resolve() for entry in answer["projects"]], "the original does not join the list")
        status, answer = call("POST", "/api/v1/projects/import-claude", {"path": path, "mode": "copy", "to": str(target)})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "a destination that is not empty is refused")

    def test_refused_requests_say_why_and_a_device_may_do_neither(self):
        plain = self.folder()
        status, answer = call("POST", "/api/v1/projects/import-claude", {"path": plain, "mode": "in_place"})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "not a Claude project")
        for body in ({}, {"path": plain}, {"path": plain, "mode": "elsewhere"}, {"path": plain, "mode": "copy", "colour": 1}, {"path": 3, "mode": "copy"}):
            self.assertEqual(call("POST", "/api/v1/projects/import-claude", body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(call("GET", "/api/v1/projects/claude?path=x", who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("POST", "/api/v1/projects/import-claude", {"path": plain, "mode": "copy"}, who=V.DEVICE)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
