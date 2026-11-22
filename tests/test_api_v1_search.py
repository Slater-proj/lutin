"""Searching the conversations in `/api/v1` (docs/modernization/PARITY.md, item 4), on a real server: `GET /conversations?q=` goes through the full-text
index of the store (ADR 0017), ignores accents, needs every word, and gives an extract around what it found."""
import unittest
import urllib.parse

import test_api_v1_turns as U  # its callers and the fake engine of tests/test_moteur.py (imported as a module: its tests do not run here)

A, api = U.A, U.api


class Search(unittest.TestCase):
    def setUp(self):
        self.ids = []
        for title, text in (("Recette de cuisine", "La pâte brisée repose une heure au frais."), ("Réglages du modèle", "Baisse la température à 0,3.")):
            c = A.conv_new()
            c["titre"] = title
            c["messages"] = [{"role": "user", "content": text}]
            A.conv_write(c)
            self.ids.append(c["id"])
        self.addCleanup(lambda: [A.conv_delete(i) for i in self.ids])

    def search(self, words):
        return api("GET", "/api/v1/conversations?q=" + urllib.parse.quote(words))

    def test_the_words_are_found_accents_ignored_with_an_extract(self):
        status, answer = self.search("pate brisee")
        self.assertEqual((status, answer["query"], [c["id"] for c in answer["conversations"]]), (200, "pate brisee", [self.ids[0]]))
        found = answer["conversations"][0]
        self.assertEqual(sorted(found), ["extract", "id", "message_count", "origin_machine", "pinned", "title", "updated_at"])
        self.assertIn("brisée", found["extract"])
        self.assertEqual([c["id"] for c in self.search("reglages temperature")[1]["conversations"]], [self.ids[1]], "the title and the text both count")
        self.assertEqual(self.search("pâte température")[1]["conversations"], [], "every word is needed")
        self.assertEqual(self.search("x" * 201)[1]["error"]["code"], "invalid_request")
        self.assertNotIn("query", api("GET", "/api/v1/conversations")[1], "without q, the list as before")


if __name__ == "__main__":
    unittest.main()
