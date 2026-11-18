"""Documents, notes and the search by meaning in `/api/v1` (docs/modernization/PARITY.md, item 14), on the real server of tests/test_api_v1.py.

Hermetic: MEMOIRE.md lives in the temporary memory folder of test_api_v1; the index of the documents and the embeddings model are replaced."""
import os
import unittest
import urllib.parse
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import embeddings, recall

A = V.A


def setUpModule():
    V.setUpModule()


class Notes(unittest.TestCase):
    def setUp(self):
        path = A.MEMOIRE / "MEMOIRE.md"
        before = path.read_bytes() if path.is_file() else None
        self.addCleanup(lambda: path.write_bytes(before) if before is not None else path.unlink(missing_ok=True))
        path.unlink(missing_ok=True)

    def test_a_note_is_added_listed_and_deleted_one_by_one(self):
        status, answer = V.call("POST", "/api/v1/notes", V.DEVICE, {"text": "Le client préfère le tutoiement."})
        self.assertEqual(status, 201, answer)
        V.call("POST", "/api/v1/notes", V.DEVICE, {"text": "Livraison le 3 décembre."})
        notes = V.call("GET", "/api/v1/notes", V.DEVICE)[1]["notes"]
        self.assertEqual([n["text"] for n in notes], ["Le client préfère le tutoiement.", "Livraison le 3 décembre."])
        self.assertRegex(notes[0]["date"], r"^\d{4}-\d{2}-\d{2}$")
        status, answer = V.call("DELETE", "/api/v1/notes?line=" + urllib.parse.quote(notes[0]["line"]), V.DEVICE)
        self.assertEqual([n["text"] for n in answer["notes"]], ["Livraison le 3 décembre."])
        self.assertEqual(V.call("DELETE", "/api/v1/notes?line=" + urllib.parse.quote(notes[0]["line"]), V.DEVICE)[0], 404)
        self.assertEqual(V.call("POST", "/api/v1/notes", V.DEVICE, {"text": "   "})[0], 400)


class Documents(unittest.TestCase):
    def test_the_documents_and_their_search(self):
        seen = {"dossiers": ["documents/"], "formats": [".pdf", ".md"], "fichiers": [{"nom": "contrat.pdf", "passages": 12}], "erreurs": [], "max": 200}
        found = [{"source": "documents/contrat.pdf", "titre": "contrat.pdf", "extrait": "… la TVA …", "conversation": False}]
        with mock.patch.object(recall, "documents_state", lambda: seen), mock.patch.object(recall, "search_documents", lambda words: found):
            status, answer = V.call("GET", "/api/v1/documents", V.DEVICE)
            self.assertEqual((answer["files"], answer["max"]), ([{"name": "contrat.pdf", "passages": 12}], 200))
            status, answer = V.call("GET", "/api/v1/documents/search?q=" + urllib.parse.quote("taux de TVA"), V.DEVICE)
            self.assertEqual(answer["passages"][0]["title"], "contrat.pdf")
            self.assertEqual(V.call("GET", "/api/v1/documents/search?q=a", V.DEVICE)[0], 400)


class SearchByMeaning(unittest.TestCase):
    def test_its_model_is_installed_from_this_machine_with_the_network(self):
        started = []
        state = {"actif": False, "modele": "nomic-embed-text", "installe": False, "installation": {"etat": "", "fait": 0, "total": 0, "erreur": "", "texte": ""}}
        with mock.patch.object(embeddings, "state", lambda: state), mock.patch.object(embeddings, "start_installation", lambda: started.append(1)):
            status, answer = V.call("GET", "/api/v1/search-by-meaning", V.DEVICE)
            self.assertEqual((answer["model"], answer["installed"], answer["installation"]["state"]), ("nomic-embed-text", False, "idle"))
            self.assertEqual(V.call("POST", "/api/v1/search-by-meaning/install", V.DEVICE, {})[0], 403)
            self.assertEqual(V.call("POST", "/api/v1/search-by-meaning/install", V.OWNER, {})[1]["error"]["code"], "offline")
            with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": ""}):
                self.assertEqual(V.call("POST", "/api/v1/search-by-meaning/install", V.OWNER, {})[0], 202)
        self.assertEqual(started, [1])


if __name__ == "__main__":
    unittest.main()
