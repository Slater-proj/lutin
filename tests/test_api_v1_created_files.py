"""`/api/v1/created-files` and `/api/v1/locations` (docs/modernization/PARITY.md, item 17), on the real server of tests/test_api_v1.py.

Hermetic: the registry of created files and the list of locations are replaced; nothing is deleted from the disk and no explorer opens."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import locations, produced_files

A = V.A


def setUpModule():
    V.setUpModule()


class CreatedFiles(unittest.TestCase):
    def test_the_files_are_listed_deleted_and_shown_in_their_folder_from_this_machine(self):
        listed = {"total": 2048, "liste": [{"id": "f1", "genre": "image", "nom": "chat.png", "chemin": "C:/data/chat.png", "taille": 2048, "date": 1700000000, "conversation": "c1",
                                            "conversation_existe": True}]}
        removed, opened = [], []
        with mock.patch.object(produced_files, "entries", lambda: listed), mock.patch.object(produced_files, "remove_selection", lambda ids: removed.append(ids) or {"supprimes": 1, "libere": 2048, "ignores": []}), \
                mock.patch.object(produced_files, "opening_possible", lambda: True), mock.patch.object(produced_files, "open_folder", lambda identifier: opened.append(identifier)):
            self.assertEqual(V.call("GET", "/api/v1/created-files", V.DEVICE)[0], 403, "paths of this machine")
            status, answer = V.call("GET", "/api/v1/created-files", V.OWNER)
            self.assertEqual((answer["total_bytes"], answer["files"][0]["kind"], answer["files"][0]["size_bytes"]), (2048, "image", 2048))
            self.assertEqual(V.call("POST", "/api/v1/created-files/delete", V.OWNER, {"ids": ["f1"]})[1], {"deleted": 1, "freed_bytes": 2048, "skipped": []})
            self.assertEqual(V.call("POST", "/api/v1/created-files/delete", V.OWNER, {"ids": []})[0], 400)
            self.assertEqual(V.call("POST", "/api/v1/created-files/f1/open-folder", V.OWNER, {})[1], {"opened": True})
        self.assertEqual((removed, opened), ([["f1"]], ["f1"]))

    def test_the_files_of_one_conversation(self):
        """The panel « This conversation » of the Chat lists what this conversation made, as the « ⋯ » menu of the old page did."""
        listed = {"total": 3072, "liste": [{"id": "f1", "genre": "image", "nom": "chat.png", "chemin": "C:/data/chat.png", "taille": 2048, "date": 1700000000, "conversation": "c1", "conversation_existe": True},
                                           {"id": "f2", "genre": "fichier", "nom": "devis.pdf", "chemin": "D:/w/devis.pdf", "taille": 1024, "date": 1700000100, "conversation": "c2", "conversation_existe": True}]}
        with mock.patch.object(produced_files, "entries", lambda: listed):
            answer = V.call("GET", "/api/v1/created-files?conversation=c2", V.OWNER)[1]
            self.assertEqual(([f["id"] for f in answer["files"]], answer["total_bytes"]), (["f2"], 1024))
            self.assertEqual(V.call("GET", "/api/v1/created-files?conversation=nowhere", V.OWNER)[1], {"files": [], "total_bytes": 0})
            self.assertEqual(len(V.call("GET", "/api/v1/created-files", V.OWNER)[1]["files"]), 2, "without the filter, every file")

    def test_the_locations_say_their_size_and_their_disk(self):
        seen = {"lignes": [{"cle": "donnees", "nom": "Données", "chemin": "C:/data", "explication": "Conversations…", "existe": True, "taille": 10 ** 6, "disque": {"libre": 5, "total": 10, "racine": "C:\\"}},
                           {"cle": "travail:1", "nom": "Dossier de travail : x", "chemin": "D:/x", "explication": "…", "existe": True, "taille": None, "disque": None}],
                "donnees_detail": [{"nom": "conversations", "taille": 900}]}
        with mock.patch.object(locations, "list_locations", lambda: seen):
            status, answer = V.call("GET", "/api/v1/locations", V.OWNER)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["locations"][0]["disk"], {"free": 5, "total": 10, "root": "C:\\"})
        self.assertIsNone(answer["locations"][1]["disk"])
        self.assertEqual(answer["data_detail"], [{"name": "conversations", "size_bytes": 900}])


if __name__ == "__main__":
    unittest.main()
