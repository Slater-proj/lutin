"""The store of the conversations (lutin.store, docs/adr/0017-conversations-in-sqlite.md).

What is fixed here: the 0.x JSON files are imported once, after a zip backup, then moved (never deleted); a damaged file is taken from its copy
of the time before, or reported and left where it is; importing again changes nothing; the list is ordered as in 0.x; the search ignores accents;
the export writes the 0.x files back (the way back); and a reader never sees half a conversation while another thread writes it."""
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401

from lutin import core as A  # noqa: E402
from lutin import store  # noqa: E402


def conversation(ident, title, maj, messages=(), **fields):
    return dict({"id": ident, "titre": title, "date": maj, "maj": maj, "resume": "", "messages": [dict(m) for m in messages]}, **fields)


class Store(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="lutin-store-"))
        patch = mock.patch.object(A, "DONNEES", self.data)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(store.close)
        store.close()

    def write_files(self, *conversations, options=None):
        folder = self.data / "conversations"
        folder.mkdir(parents=True, exist_ok=True)
        for c in conversations:
            (folder / (c["id"] + ".json")).write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        for ident, fields in (options or {}).items():
            (self.data / "options").mkdir(exist_ok=True)
            (self.data / "options" / (ident + ".json")).write_text(json.dumps(fields), encoding="utf-8")

    def test_the_files_of_0x_are_imported_after_a_backup_and_kept(self):
        self.write_files(conversation("0000000a", "Rapport", "2026-01-02T10:00:00", [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut"}]),
                         conversation("0000000b", "Épinglée", "2026-01-01T10:00:00", epingle=True), options={"0000000a": {"web": True}})
        listed = A.conv_liste()
        self.assertEqual([entry["id"] for entry in listed], ["0000000b", "0000000a"], "pinned first, then the most recent, as in 0.x")
        self.assertEqual(sorted(listed[1]), ["epingle", "id", "maj", "memoire", "messages", "origine", "titre"])
        self.assertEqual(listed[1]["messages"], 2)
        self.assertEqual([m["content"] for m in A.conv_lire("0000000a")["messages"]], ["Bonjour", "Salut"])
        self.assertEqual(A.options_lire("0000000a"), {"web": True})
        self.assertEqual(list((self.data / "conversations").glob("*.json")), [], "imported: the folder is empty")
        kept = sorted(p.name for p in (self.data / "archives" / "avant-1.0" / "conversations").glob("*.json"))
        self.assertEqual(kept, ["0000000a.json", "0000000b.json"], "moved, never deleted")
        backups = list((self.data / "sauvegardes").glob("avant-import-*.zip"))
        self.assertEqual(len(backups), 1)
        with zipfile.ZipFile(backups[0]) as archive:
            self.assertEqual(sorted(archive.namelist()), ["conversations/0000000a.json", "conversations/0000000b.json", "options/0000000a.json"])

    def test_a_file_put_back_is_taken_as_it_is_and_the_same_one_twice_writes_nothing(self):
        same = conversation("0000000a", "Ancien", "2026-01-02T10:00:00", [{"role": "user", "content": "x"}])
        self.write_files(same)
        A.conv_liste()
        self.write_files(same)                                                                 # the same file dropped again
        self.assertEqual(store.import_files()["skipped"], 1, "nothing to write for the same conversation")
        c = A.conv_lire("0000000a")
        c["titre"] = "Changée ici"
        A.conv_ecrire(c)
        self.write_files(conversation("0000000a", "Remise par une restauration", "2026-01-01T00:00:00"))
        self.assertEqual(A.conv_lire("0000000a")["titre"], "Remise par une restauration", "a file put back (a restore, a person) is taken as it is")

    def test_a_damaged_file_is_taken_from_its_copy_or_reported_and_left(self):
        folder = self.data / "conversations"
        folder.mkdir(parents=True)
        (folder / "0000000c.json").write_text("{abîmé", encoding="utf-8")
        (folder / "0000000c.json.bak").write_text(json.dumps(conversation("0000000c", "Sauvée", "2026-01-01T00:00:00")), encoding="utf-8")
        (folder / "0000000d.json").write_text("{abîmé aussi", encoding="utf-8")
        A.conv_liste()
        self.assertEqual(A.conv_lire("0000000c")["titre"], "Sauvée")
        self.assertTrue((folder / "0000000d.json").is_file(), "unreadable and without a copy: left where it is")
        self.assertRaises(ValueError, A.conv_lire, "0000000d")

    def test_written_read_listed_searched_and_deleted(self):
        c = A.conv_nouvelle()
        c["titre"] = "Réglages du modèle"
        c["messages"] = [{"role": "user", "content": "Comment régler la température ?"}, {"role": "assistant", "content": "Avec le curseur.", "thinking": "facile"}]
        A.conv_ecrire(c)
        self.assertEqual(A.conv_lire(c["id"])["messages"][1]["thinking"], "facile", "a message keeps every field")
        found = store.search("reglages temperature")
        self.assertEqual([entry["id"] for entry in found], [c["id"]], "accents ignored, every word needed")
        self.assertEqual(store.search("absent"), [])
        A.options_ecrire(c["id"], {"web": True, "mode": "pas un mode"})
        self.assertEqual(A.options_lire(c["id"]), {"web": True}, "options are cleaned as before")
        A.conv_supprimer(c["id"])
        self.assertRaises(ValueError, A.conv_lire, c["id"])
        self.assertEqual(A.options_lire(c["id"]), {}, "its options go with it")
        self.assertRaises(ValueError, A.conv_lire, "../etc")

    def test_the_export_gives_back_the_files_of_0x(self):
        self.write_files(conversation("0000000a", "Rapport", "2026-01-02T10:00:00", [{"role": "user", "content": "Bonjour"}]), options={"0000000a": {"web": True}})
        A.conv_liste()
        target = Path(tempfile.mkdtemp(prefix="lutin-export-"))
        self.assertEqual(store.export_files(target), 1)
        back = json.loads((target / "conversations" / "0000000a.json").read_text(encoding="utf-8"))
        self.assertEqual((back["titre"], back["messages"]), ("Rapport", [{"role": "user", "content": "Bonjour"}]))
        self.assertEqual(json.loads((target / "options" / "0000000a.json").read_text(encoding="utf-8")), {"web": True})

    def test_a_reader_never_sees_half_a_conversation(self):
        c = A.conv_nouvelle()
        stop, torn, errors = threading.Event(), [], []

        def writer():
            n = 0
            while not stop.is_set():
                n += 1
                c["messages"] = [{"role": "user", "content": str(n)}] * (n % 50 + 1)
                c["titre"] = str(len(c["messages"]))
                try:
                    A.conv_ecrire(c)
                except Exception as error:  # noqa: BLE001
                    errors.append(error)
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for _ in range(400):
                read = A.conv_lire(c["id"])
                if read["titre"] != "Nouvelle conversation" and int(read["titre"]) != len(read["messages"]):
                    torn.append((read["titre"], len(read["messages"])))
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual((torn, errors), ([], []))


if __name__ == "__main__":
    unittest.main()
