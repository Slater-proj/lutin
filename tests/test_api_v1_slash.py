"""What the « / » commands need from `/api/v1` (docs/modernization/PARITY.md, item 15): « /compact » now, and the commands of a Claude project, on the
real server of tests/test_api_v1.py.

Hermetic: the conversation lives in the temporary data folder; the compaction and the project's commands are replaced."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import claude_project

A = V.A


def setUpModule():
    V.setUpModule()


class Slash(unittest.TestCase):
    def test_compact_now(self):
        conversation = A.conv_new()
        A.conv_write(conversation)
        self.addCleanup(lambda: A.conv_delete(conversation["id"]))
        base = "/api/v1/conversations/%s/compact" % conversation["id"]
        with mock.patch.object(A, "compact_conversation", lambda identifier: {"ok": True, "avant": 30, "apres": 8, "jauge": {}, "fiche": False}):
            status, answer = V.call("POST", base, V.DEVICE, {})
            self.assertEqual((status, answer), (200, {"before": 30, "after": 8, "sheet": False}))
            with mock.patch.dict(A.ACTIVE_TURNS, {conversation["id"]: object()}):
                self.assertEqual(V.call("POST", base, V.DEVICE, {})[1]["error"]["code"], "turn_running")
        self.assertEqual(V.call("POST", "/api/v1/conversations/0123456789ab/compact", V.DEVICE, {})[0], 404)

    def test_the_commands_of_a_claude_project(self):
        found = {"contexte": [], "regles": [], "skills": [], "agents": [], "commandes": [{"nom": "review", "description": "Relis un fichier", "chemin": ".claude/commands/review.md"}]}

        def command(root, name, arguments=""):
            if name != "review":
                raise ValueError("Commande du projet inconnue : " + name)
            return "Relis " + arguments
        with mock.patch.object(claude_project, "detect", lambda root: found), mock.patch.object(claude_project, "command", command):
            self.assertEqual(V.call("GET", "/api/v1/project-commands", V.DEVICE)[1], {"commands": [{"name": "review", "description": "Relis un fichier"}]})
            self.assertEqual(V.call("GET", "/api/v1/project-commands/review?args=a.py", V.DEVICE)[1], {"text": "Relis a.py"})
            self.assertEqual(V.call("GET", "/api/v1/project-commands/other", V.DEVICE)[0], 404)


if __name__ == "__main__":
    unittest.main()
