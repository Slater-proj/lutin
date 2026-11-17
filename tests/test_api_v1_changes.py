"""The changes of the last request in `/api/v1` (docs/modernization/PARITY.md, item 1), on a real server with the fake engine of tests/test_moteur.py.

A request makes the fake engine change a file (the tool « modifier », approved): the review shows it with its differences, undoing puts it back as
it was, the model is told, and a refusal (an answer running, nothing left to undo, a wrong value) comes before any effect."""
import unittest

import test_api_v1_turns as U  # its callers and the fake engine of tests/test_moteur.py (imported as a module: its tests do not run here)

T, A, api = U.T, U.A, U.api
FILE = T.PROJET / "appli" / "moteur" / "code.py"


class Changes(unittest.TestCase):
    def setUp(self):
        self.before = FILE.read_text(encoding="utf-8")
        self.addCleanup(lambda: FILE.write_text(self.before, encoding="utf-8"))
        self.conversation = U.new_conversation()
        call = T.appel_outil("modifier", chemin="appli/moteur/code.py", ancien="return 1", nouveau="return 2")
        status, _, events = U.turn(self.conversation, {"message": "Change it"}, [[call], [{"content": "Done."}]], approve=lambda event: True)
        self.assertEqual((status, events[-1]["type"]), (200, "end"))
        self.assertIn("return 2", FILE.read_text(encoding="utf-8"), "the request changed the file")

    def test_the_review_shows_each_file_with_its_differences(self):
        status, review = api("GET", "/api/v1/conversations/%s/changes" % self.conversation)
        self.assertEqual((status, sorted(review), review["undoable"]), (200, ["files", "undoable"], True))
        entry = review["files"][0]
        self.assertEqual((sorted(entry), entry["path"], entry["state"], entry["added"], entry["removed"], entry["changed_since"]),
                         (["added", "binary", "changed_since", "diff", "path", "removed", "state"], "appli/moteur/code.py", "modified", 1, 1, False))
        self.assertIn("+    return 2", entry["diff"])
        self.assertEqual(api("GET", "/api/v1/conversations/0123abcd/changes")[0], 404)

    def test_undoing_puts_the_file_back_and_tells_the_model(self):
        path = "/api/v1/conversations/%s/changes/undo" % self.conversation
        for body in ({"path": ""}, {"path": 1}, {"everything": True}):
            self.assertEqual(api("POST", path, body)[1]["error"]["code"], "invalid_request", body)
        self.assertIn("return 2", FILE.read_text(encoding="utf-8"), "refusals change nothing")
        A.TOURS_ACTIFS[self.conversation] = object()
        try:
            self.assertEqual(api("POST", path, {})[1]["error"]["code"], "turn_running")
        finally:
            A.TOURS_ACTIFS.pop(self.conversation, None)
        status, answer = api("POST", path, {"path": "appli/moteur/code.py"})
        self.assertEqual((status, answer["restored"], answer["skipped"], answer["undoable"]), (200, ["appli/moteur/code.py"], [], False))
        self.assertEqual(FILE.read_text(encoding="utf-8"), self.before, "as it was before the request")
        last = A.conv_lire(self.conversation)["messages"][-1]
        self.assertIn("annulé", last["content"], "the model is told the change was undone")
        self.assertEqual(api("POST", path, {})[1]["error"]["code"], "nothing_to_undo")


if __name__ == "__main__":
    unittest.main()
