"""`/api/v1/skills` and `/api/v1/memory`: the sheets of your own and the two notes the model always has, on the real server of tests/test_api_v1.py (temporary folders)."""
import unittest

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import core as _m  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Skills(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: [call("DELETE", "/api/v1/skills/" + entry["name"]) for entry in call("GET", "/api/v1/skills")[1]["skills"]])

    def test_a_skill_is_added_listed_read_changed_and_deleted(self):
        status, answer = call("POST", "/api/v1/skills", {"name": "my notes.md", "text": "# My notes\nÀ lire quand je parle de cuisine.\nSalt first."})
        self.assertEqual((status, answer["name"]), (201, "my notes.md"))
        listed = call("GET", "/api/v1/skills")[1]["skills"]
        self.assertEqual(listed, [{"name": "my notes.md", "title": "My notes", "read_when": "je parle de cuisine"}])
        self.assertEqual(call("GET", "/api/v1/skills/my%20notes.md")[1]["text"], "# My notes\nÀ lire quand je parle de cuisine.\nSalt first.")
        status, answer = call("PATCH", "/api/v1/skills/my%20notes.md", {"text": "# Renamed\nPepper."})
        self.assertEqual((status, answer["text"]), (200, "# Renamed\nPepper."))
        self.assertEqual(call("GET", "/api/v1/skills")[1]["skills"][0]["title"], "Renamed")
        self.assertEqual(call("DELETE", "/api/v1/skills/my%20notes.md")[1], {"skills": []})

    def test_refused_requests_say_why(self):
        call("POST", "/api/v1/skills", {"name": "one.md", "text": "# One"})
        status, answer = call("POST", "/api/v1/skills", {"name": "one.md", "text": "# Again"})
        self.assertEqual((status, answer["error"]["code"]), (409, "exists"))
        self.assertEqual(call("POST", "/api/v1/skills", {"name": "../escape.md", "text": "x"})[0], 400)
        self.assertEqual(call("POST", "/api/v1/skills", {"name": "two", "text": "x"})[0], 400, "a skill name ends with .md")
        self.assertEqual(call("POST", "/api/v1/skills", {"name": "two.md", "text": "x" * 60001})[0], 400)
        self.assertEqual(call("POST", "/api/v1/skills", {"name": "two.md"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("GET", "/api/v1/skills/nope.md")[0], 404)
        self.assertEqual(call("PATCH", "/api/v1/skills/nope.md", {"text": "x"})[0], 404)
        self.assertEqual(call("DELETE", "/api/v1/skills/nope.md")[0], 404)
        self.assertEqual(call("PATCH", "/api/v1/skills/one.md", {"colour": 1})[1]["error"]["code"], "invalid_request")

    def test_a_paired_device_may_read_but_not_write(self):
        call("POST", "/api/v1/skills", {"name": "one.md", "text": "# One"})
        self.assertEqual(call("GET", "/api/v1/skills", who=V.DEVICE)[0], 200)
        self.assertEqual(call("GET", "/api/v1/skills/one.md", who=V.DEVICE)[0], 200)
        for method, path, body in (("POST", "/api/v1/skills", {"name": "two.md", "text": "x"}), ("PATCH", "/api/v1/skills/one.md", {"text": "x"}), ("DELETE", "/api/v1/skills/one.md", None),
                                   ("PATCH", "/api/v1/memory", {"memory": "x"})):
            self.assertEqual(call(method, path, body, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


class Memory(unittest.TestCase):
    def setUp(self):
        before = {key: _m.lire_memoire(name) for key, name in (("context", "CONTEXTE.md"), ("memory", "MEMOIRE.md"))}
        self.addCleanup(lambda: call("PATCH", "/api/v1/memory", before))

    def test_the_two_notes_are_read_and_replaced_one_at_a_time(self):
        self.assertEqual(sorted(call("GET", "/api/v1/memory")[1]), ["context", "memory"])
        status, answer = call("PATCH", "/api/v1/memory", {"context": "I write games."})
        self.assertEqual((status, answer["context"]), (200, "I write games."))
        memory_before = answer["memory"]
        answer = call("PATCH", "/api/v1/memory", {"memory": "Likes tea."})[1]
        self.assertEqual((answer["context"], answer["memory"]), ("I write games.", "Likes tea."))
        self.assertNotEqual(memory_before, answer["memory"])

    def test_refused_requests_say_why(self):
        for body in ({}, {"colour": "x"}, {"context": 3}, {"context": "x" * 60001}):
            status, answer = call("PATCH", "/api/v1/memory", body)
            self.assertEqual(status, 400, body)
            self.assertTrue(answer["error"]["message"])


if __name__ == "__main__":
    unittest.main()
