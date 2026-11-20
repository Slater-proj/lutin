"""The tools of one conversation in `/api/v1` (docs/modernization/PARITY.md, item 12): its memory mode and progress sheet, the handover document, its
folders, the project's Git and the actions log, on the real server of tests/test_api_v1.py.

Hermetic: the conversation and its sheet live in the temporary data folder of test_api_v1; the model, Git and the file explorer are replaced."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import change_review, produced_files, progress_sheet

A = V.A


def setUpModule():
    V.setUpModule()


class ConversationTools(unittest.TestCase):
    def setUp(self):
        conversation = A.conv_nouvelle()
        conversation["messages"] = [{"role": "user", "content": "Réécrire la facturation."}, {"role": "assistant", "content": "D'accord."}]
        A.conv_ecrire(conversation)
        self.id = conversation["id"]
        self.addCleanup(lambda: (progress_sheet.delete(self.id), A.conv_supprimer(self.id)))
        self.base = "/api/v1/conversations/%s" % self.id

    def test_the_sheet_is_read_and_edited_and_the_old_modes_are_accepted(self):
        """ADR 0019: every conversation keeps its thread with the progress sheet. `mode` is still accepted (older clients) and changes nothing."""
        status, answer = V.call("GET", self.base + "/memory", V.DEVICE)
        self.assertEqual((status, answer["mode"], answer["own_mode"], answer["general_mode"]), (200, "sheet", None, "sheet"), answer)
        for mode in ("summary", "sheet", None):
            status, answer = V.call("PATCH", self.base + "/memory", V.DEVICE, {"mode": mode})
            self.assertEqual((status, answer["mode"], answer["own_mode"]), (200, "sheet", None), mode)
        self.assertNotIn("memoire_longue", A.conv_lire(self.id), "nothing is stored in the conversation")
        status, answer = V.call("PATCH", self.base + "/memory", V.DEVICE, {"sheet": "## Objectif\n- Réécrire la facturation\n## Décisions\n- Garder l'API"})
        self.assertEqual((answer["sections"]["objective"], answer["sections"]["decisions"]), (["Réécrire la facturation"], ["Garder l'API"]))
        self.assertIn("## Objectif", answer["text"])
        status, answer = V.call("DELETE", self.base + "/memory/sheet", V.DEVICE)
        self.assertEqual((status, answer["sections"]["objective"]), (200, []))
        self.assertEqual(V.call("PATCH", self.base + "/memory", V.DEVICE, {"mode": "forever"})[0], 400)
        self.assertEqual(V.call("PATCH", self.base + "/memory", V.DEVICE, {"mode": "forever", "sheet": "## Objectif\n- Autre chose"})[0], 400)
        self.assertEqual(V.call("GET", self.base + "/memory", V.DEVICE)[1]["sections"]["objective"], [], "a refused request writes nothing")
        self.assertEqual(V.call("GET", "/api/v1/conversations/0123456789ab/memory", V.DEVICE)[0], 404)

    def test_nothing_changes_during_an_answer(self):
        with mock.patch.dict(A.TOURS_ACTIFS, {self.id: object()}):
            status, answer = V.call("PATCH", self.base + "/memory", V.DEVICE, {"mode": "summary"})
        self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))

    def test_a_handover_document_is_written_by_the_model(self):
        with mock.patch.object(A, "document_de_reprise", lambda conversation, settings: "## Objectif\nRéécrire la facturation."):
            status, answer = V.call("POST", self.base + "/handover", V.DEVICE, {})
        self.assertEqual(status, 200, answer)
        self.assertIn("## Objectif", answer["text"])

    def test_the_folders_are_for_this_machine(self):
        opened = []
        with mock.patch.object(produced_files, "folders_conversation", lambda identifier: [{"chemin": "C:/work", "role": "travail"}]), \
                mock.patch.object(produced_files, "opening_possible", lambda: True), mock.patch.object(produced_files, "open_folder_conversation", lambda i, p: opened.append(p)):
            self.assertEqual(V.call("GET", self.base + "/folders", V.DEVICE)[0], 403)
            status, answer = V.call("GET", self.base + "/folders", V.OWNER)
            self.assertEqual(answer, {"folders": [{"path": "C:/work", "role": "work"}], "can_open": True})
            self.assertEqual(V.call("POST", self.base + "/folders/open", V.OWNER, {"path": "C:/work"})[0], 200)
        self.assertEqual(opened, ["C:/work"])

    def test_git_reads_proposes_and_commits_from_this_machine_only(self):
        state = {"dispo": True, "branche": "main", "total": 2, "modifies": [{"chemin": "a.py", "etat": " M"}, {"chemin": "b.py", "etat": "??"}]}
        committed = []
        with mock.patch.object(change_review, "git_state", lambda: state), mock.patch.object(change_review, "git_message_of", lambda files: {"message": "fix: a"}), \
                mock.patch.object(change_review, "git_commit", lambda message, files: committed.append((message, files)) or {"ok": True, "sortie": "1 file changed"}):
            status, answer = V.call("GET", "/api/v1/git", V.DEVICE)
            self.assertEqual(answer["files"], [{"path": "a.py", "state": "modified"}, {"path": "b.py", "state": "untracked"}])
            self.assertEqual(V.call("POST", "/api/v1/git/message", V.DEVICE, {"files": ["a.py"]})[1], {"message": "fix: a"})
            self.assertEqual(V.call("POST", "/api/v1/git/commit", V.DEVICE, {"message": "fix: a", "files": ["a.py"]})[0], 403)
            status, answer = V.call("POST", "/api/v1/git/commit", V.OWNER, {"message": "fix: a", "files": ["a.py"]})
            self.assertEqual((status, answer["output"]), (200, "1 file changed"))
        self.assertEqual(committed, [("fix: a", ["a.py"])])
        with mock.patch.object(change_review, "git_state", lambda: {"dispo": False, "raison": "pas un dépôt"}):
            self.assertEqual(V.call("GET", "/api/v1/git", V.DEVICE)[1]["available"], False)

    def test_the_actions_log_never_holds_contents(self):
        entries = [{"ts": "2026-11-18T10:00:00", "conversation": self.id, "dossier": "C:/work", "outil": "ecrire", "cible": "a.py", "issue": "ok", "accord": "manuel", "qui": "moi"}]
        with mock.patch.object(A, "lire_journal", lambda n: entries):
            status, answer = V.call("GET", "/api/v1/actions-log?n=5", V.DEVICE)
        self.assertEqual(answer["entries"], [{"at": "2026-11-18T10:00:00", "conversation": self.id, "folder": "C:/work", "tool": "ecrire", "target": "a.py", "outcome": "ok",
                                              "approval": "manuel", "who": "moi"}])
        self.assertEqual(V.call("GET", "/api/v1/actions-log?n=x", V.DEVICE)[0], 400)


if __name__ == "__main__":
    unittest.main()
