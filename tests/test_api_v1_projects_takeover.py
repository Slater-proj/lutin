"""`/api/v1/projects/{id}/preview`, `…/move`, `PATCH /projects/{id}` and `/api/v1/takeover*`: what Lutin finds in a work folder, moving it, giving it the path it
was moved to by hand, and taking over the data of another assistant (parity with the old page, 2026-11-22). On the real server of tests/test_api_v1.py, in
temporary folders: nothing outside them is read or written."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import core as A  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, "/api/v1" + path, V.OWNER if who is None else who, body=body)


def old_assistant(base):
    """A folder left by another assistant: one conversation, one memory file, one skill."""
    (base / "donnees" / "conversations").mkdir(parents=True)
    (base / "memoire").mkdir()
    (base / "skills").mkdir()
    conversation = {"id": "0000abcd", "titre": "Old budget", "date": "2026-01-02T10:00:00", "maj": "2026-01-02T10:00:00", "messages": [{"role": "user", "content": "Hello"}]}
    (base / "donnees" / "conversations" / "0000abcd.json").write_text(json.dumps(conversation), encoding="utf-8")
    (base / "memoire" / "MEMOIRE.md").write_text("I like short answers.", encoding="utf-8")
    (base / "skills" / "resume.md").write_text("# Summarise\nIn three lines.", encoding="utf-8")


class Projects(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lutin-projects-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "site").mkdir()
        (self.root / "site" / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        (self.root / "site" / "CLAUDE.md").write_text("Rules.", encoding="utf-8")
        status, view = call("POST", "/projects", {"path": str(self.root / "site"), "name": "Site"})
        self.assertEqual(status, 201, view)
        self.project = next(p for p in view["projects"] if p["name"] == "Site")
        self.addCleanup(lambda: call("DELETE", "/projects/" + self.project["id"]))

    def test_the_preview_says_what_lutin_finds_and_writes_nothing(self):
        status, seen = call("GET", "/projects/%s/preview" % self.project["id"])
        self.assertEqual(status, 200, seen)
        self.assertEqual((seen["error"], seen["git"], seen["previous_assistant"]), ("", False, None))
        self.assertGreaterEqual(seen["files"], 2)
        self.assertTrue(any("CLAUDE.md" in line for line in seen["reads"]), seen["reads"])
        self.assertEqual(sorted(p.name for p in (self.root / "site").iterdir()), ["CLAUDE.md", "index.html"], "nothing written")

    def test_the_preview_finds_another_assistant_to_take_over(self):
        old_assistant(self.root / "site")
        previous = call("GET", "/projects/%s/preview" % self.project["id"])[1]["previous_assistant"]
        self.assertEqual((previous["conversations"], previous["memory"], previous["skills"], previous["to_take_over"]), (1, ["MEMOIRE.md"], 1, True), previous)

    def test_a_folder_is_moved_with_its_files_then_given_a_path_by_hand(self):
        (self.root / "elsewhere").mkdir()
        status, view = call("POST", "/projects/%s/move" % self.project["id"], {"parent": str(self.root / "elsewhere"), "name": "site2"})
        self.assertEqual(status, 200, view)
        moved = self.root / "elsewhere" / "site2"
        self.assertTrue((moved / "index.html").is_file(), "the files went with it")
        self.assertFalse((self.root / "site").exists())
        self.assertEqual(Path(next(p for p in view["projects"] if p["id"] == self.project["id"])["path"]), moved)
        shutil.move(str(moved), str(self.root / "by-hand"))
        status, view = call("PATCH", "/projects/" + self.project["id"], {"path": str(self.root / "by-hand")})
        self.assertEqual(status, 200, view)
        self.assertEqual(Path(next(p for p in view["projects"] if p["id"] == self.project["id"])["path"]), self.root / "by-hand")
        self.assertEqual(call("PATCH", "/projects/" + self.project["id"], {"chemin": "x"})[0], 400)

    def test_a_paired_device_may_look_but_not_move(self):
        self.assertEqual(call("GET", "/projects/%s/preview" % self.project["id"], who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/projects/%s/move" % self.project["id"], {"parent": str(self.root)}, who=V.DEVICE)[0], 403)


class Takeover(unittest.TestCase):
    def setUp(self):
        self.source = Path(tempfile.mkdtemp(prefix="lutin-old-assistant-"))
        self.addCleanup(shutil.rmtree, self.source, True)
        old_assistant(self.source)

    def test_what_can_be_taken_over_is_said_first_then_taken_after_a_confirmation(self):
        status, found = call("POST", "/takeover/detect", {"path": str(self.source)})
        self.assertEqual(status, 200, found)
        self.assertEqual((found["conversations"], found["memory"], found["skills"], found["settings"]), (1, ["MEMOIRE.md"], 1, False))
        self.assertTrue(found["target_skills"])
        body = {"path": str(self.source), "choices": ["conversations"]}
        status, refused = call("POST", "/takeover", body)
        self.assertEqual((status, refused["error"]["code"]), (400, "confirmation_required"))
        self.assertNotIn("0000abcd", [c["id"] for c in call("GET", "/conversations")[1]["conversations"]], "nothing taken before the confirmation")
        status, done = call("POST", "/takeover", dict(body, confirm=True))
        self.assertEqual(status, 200, done)
        self.assertTrue(done["summary"] and all(isinstance(line, str) for line in done["summary"]), done)
        self.addCleanup(lambda: call("DELETE", "/conversations/0000abcd"))
        self.assertEqual(A.conv_lire("0000abcd")["titre"], "Old budget")

    def test_refusals(self):
        self.assertEqual(call("POST", "/takeover/detect", {"path": str(self.source / "nowhere")})[0], 400)
        self.assertEqual(call("POST", "/takeover", {"path": str(self.source), "choices": ["everything"], "confirm": True})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/takeover/detect", {"path": str(self.source)}, who=V.DEVICE)[0], 403)


if __name__ == "__main__":
    unittest.main()
