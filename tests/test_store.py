"""The store of the conversations (lutin.store, docs/adr/0017-conversations-in-sqlite.md).

What is fixed here: the 0.x JSON files are imported once, after a zip backup, then moved (never deleted); a damaged file is taken from its copy
of the time before, or reported and left where it is; importing again changes nothing; the list is ordered as in 0.x; the search ignores accents;
the export writes the 0.x files back (the way back) without changing anything; a damaged database is set aside, never replaced in silence; a data
folder on a network share is said; and a reader never sees half a conversation while another thread writes it."""
import contextlib
import io
import json
import shutil
import sqlite3
import sys
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
        listed = A.conv_list()
        self.assertEqual([entry["id"] for entry in listed], ["0000000b", "0000000a"], "pinned first, then the most recent, as in 0.x")
        self.assertEqual(sorted(listed[1]), ["epingle", "id", "maj", "memoire", "messages", "origine", "titre"])
        self.assertEqual(listed[1]["messages"], 2)
        self.assertEqual([m["content"] for m in A.conv_read("0000000a")["messages"]], ["Bonjour", "Salut"])
        self.assertEqual(A.options_read("0000000a"), {"web": True})
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
        A.conv_list()
        self.write_files(same)                                                                 # the same file dropped again
        self.assertEqual(store.import_files()["skipped"], 1, "nothing to write for the same conversation")
        c = A.conv_read("0000000a")
        c["titre"] = "Changée ici"
        A.conv_write(c)
        self.write_files(conversation("0000000a", "Remise par une restauration", "2026-01-01T00:00:00"))
        self.assertEqual(A.conv_read("0000000a")["titre"], "Remise par une restauration", "a file put back (a restore, a person) is taken as it is")

    def test_a_damaged_file_is_taken_from_its_copy_or_reported_and_left(self):
        folder = self.data / "conversations"
        folder.mkdir(parents=True)
        (folder / "0000000c.json").write_text("{abîmé", encoding="utf-8")
        (folder / "0000000c.json.bak").write_text(json.dumps(conversation("0000000c", "Sauvée", "2026-01-01T00:00:00")), encoding="utf-8")
        (folder / "0000000d.json").write_text("{abîmé aussi", encoding="utf-8")
        A.conv_list()
        self.assertEqual(A.conv_read("0000000c")["titre"], "Sauvée")
        self.assertTrue((folder / "0000000d.json").is_file(), "unreadable and without a copy: left where it is")
        self.assertRaises(ValueError, A.conv_read, "0000000d")

    def test_written_read_listed_searched_and_deleted(self):
        c = A.conv_new()
        c["titre"] = "Réglages du modèle"
        c["messages"] = [{"role": "user", "content": "Comment régler la température ?"}, {"role": "assistant", "content": "Avec le curseur.", "thinking": "facile"}]
        A.conv_write(c)
        self.assertEqual(A.conv_read(c["id"])["messages"][1]["thinking"], "facile", "a message keeps every field")
        found = store.search("reglages temperature")
        self.assertEqual([entry["id"] for entry in found], [c["id"]], "accents ignored, every word needed")
        self.assertEqual(store.search("absent"), [])
        A.options_write(c["id"], {"web": True, "mode": "pas un mode"})
        self.assertEqual(A.options_read(c["id"]), {"web": True}, "options are cleaned as before")
        A.conv_delete(c["id"])
        self.assertRaises(ValueError, A.conv_read, c["id"])
        self.assertEqual(A.options_read(c["id"]), {}, "its options go with it")
        self.assertRaises(ValueError, A.conv_read, "../etc")

    def test_the_export_gives_back_the_files_of_0x(self):
        self.write_files(conversation("0000000a", "Rapport", "2026-01-02T10:00:00", [{"role": "user", "content": "Bonjour"}]), options={"0000000a": {"web": True}})
        A.conv_list()
        target = Path(tempfile.mkdtemp(prefix="lutin-export-"))
        self.assertEqual(store.export_files(target), 1)
        back = json.loads((target / "conversations" / "0000000a.json").read_text(encoding="utf-8"))
        self.assertEqual((back["titre"], back["messages"]), ("Rapport", [{"role": "user", "content": "Bonjour"}]))
        self.assertEqual(json.loads((target / "options" / "0000000a.json").read_text(encoding="utf-8")), {"web": True})

    def test_the_export_command_reads_only(self):
        """ADR 0017, item 6: `lutin export --conversations` writes the 0.x files of what the database holds, and changes nothing: a 0.x file waiting
        in donnees/conversations/ is neither imported nor moved, and an empty target is required."""
        from lutin import cli
        self.write_files(conversation("0000000a", "Rapport", "2026-01-02T10:00:00", [{"role": "user", "content": "Bonjour"}]), options={"0000000a": {"web": True}})
        A.conv_list()
        store.close()
        waiting = conversation("0000000c", "En attente", "2026-01-03T10:00:00")
        self.write_files(waiting)
        target = Path(tempfile.mkdtemp(prefix="lutin-export-")) / "out"
        home = self.data.parent / (self.data.name + "-home")
        (home / "donnees").mkdir(parents=True)
        shutil.copy(self.data / "lutin.db", home / "donnees" / "lutin.db")
        shutil.copytree(self.data / "conversations", home / "donnees" / "conversations")
        with mock.patch.dict("os.environ", {"LUTIN_HOME": str(home)}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["export", "--conversations", str(target)]), 0)
        self.assertIn("1 conversation(s)", out.getvalue())
        self.assertEqual(sorted(p.name for p in (target / "conversations").iterdir()), ["0000000a.json"], "only what the database holds")
        self.assertEqual(json.loads((target / "options" / "0000000a.json").read_text(encoding="utf-8")), {"web": True})
        self.assertTrue((home / "donnees" / "conversations" / "0000000c.json").is_file(), "the waiting 0.x file is not imported nor moved")
        with mock.patch.dict("os.environ", {"LUTIN_HOME": str(home)}), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["export", "--conversations", str(target)]), 1, "a folder that is not empty is refused")
            self.assertEqual(cli.main(["export"]), 2, "say what to export")
        self.assertIn("--conversations", err.getvalue())
        self.assertRaises(ValueError, store.export_database, target / "other", home / "donnees" / "absent.db")

    def test_the_cleanup_keeps_what_goes_with_the_conversations_of_the_database(self):
        """The cleanup of the data listed the 0.x folder conversations/, empty once imported: it took away the archive, the progress sheet, the
        meaning index and the options of every conversation of the database, at the start and every 30 minutes. It lists the database now, and
        removes nothing when the database cannot be read."""
        from lutin import tools
        A.conv_write(conversation("0000000a", "Gardée", "2026-01-02T10:00:00", [{"role": "user", "content": "Bonjour"}]))
        A.options_write("0000000a", {"web": True})
        A.options_write("0000000c", {"web": True})
        self.write_files(conversation("0000000d", "Pas encore importée", "2026-01-03T10:00:00"))
        for folder, suffix in (("archives", ".jsonl"), ("suivis", ".md"), ("embeddings", ".json")):
            (self.data / folder).mkdir(parents=True, exist_ok=True)
            for ident in ("0000000a", "0000000c", "0000000d"):
                (self.data / folder / (ident + suffix)).write_text("{}", encoding="utf-8")
        with mock.patch.object(store, "ids", side_effect=sqlite3.DatabaseError("file is not a database")):
            self.assertFalse(tools.clean_orphans(), "the database cannot be read: nothing is removed")
        self.assertEqual(len(list((self.data / "archives").glob("*.jsonl"))), 3)
        self.assertTrue(tools.clean_orphans())
        for folder, suffix in (("archives", ".jsonl"), ("suivis", ".md"), ("embeddings", ".json")):
            left = sorted(p.stem for p in (self.data / folder).glob("*" + suffix))
            self.assertEqual(left, ["0000000a", "0000000d"], "{}: the conversation of the database and the 0.x file keep theirs, the one gone loses its".format(folder))
        self.assertEqual(A.options_read("0000000a"), {"web": True})
        self.assertEqual(store.options_ids(), ["0000000a"], "the options of a conversation gone are removed")

    def test_a_damaged_database_is_set_aside_never_replaced_in_silence(self):
        """ADR 0017, item 8: a database that cannot be read is moved aside, said, and Lutin goes on with an empty one."""
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "lutin.db").write_bytes(b"this is not a database at all, but it is somebody's data" * 100)
        self.assertEqual(A.conv_list(), [], "an empty database to go on")
        copies = store.set_aside_copies()
        self.assertEqual(len(copies), 1)
        self.assertTrue((copies[0] / "lutin.db").read_bytes().startswith(b"this is not a database"), "the damaged file is kept as it was")
        notices = store.notices()
        self.assertEqual([level for level, _ in notices], ["erreur"])
        self.assertIn(str(copies[0]), notices[0][1])
        self.assertIn("sauvegardes", notices[0][1])
        c = A.conv_new()
        A.conv_write(c)
        self.assertEqual([entry["id"] for entry in A.conv_list()], [c["id"]], "the new database works")

    def test_a_locked_database_is_not_set_aside(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "lutin.db").write_bytes(b"x" * 100)
        with mock.patch.object(store, "_open", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertRaises(sqlite3.OperationalError, store.connection)
        self.assertEqual(store.set_aside_copies(), [], "locked or full is not damaged: nothing moves")
        self.assertEqual(store.notices(), [], "and nothing is said about a damaged database")

    def test_a_network_share_is_recognised(self):
        """ADR 0017, item 7: the data folder on a network share is said at start, in `lutin doctor` and in the health screen."""
        mounts = ("/dev/sda1 / ext4 rw 0 0\n"
                  "server:/export /mnt/nas nfs4 rw 0 0\n"
                  "//box/share /mnt/my\\040share cifs rw 0 0\n"
                  "/dev/sdb1 /mnt/nas/local ext4 rw 0 0\n")
        self.assertEqual(store.mount_type("/home/me/.lutin/donnees", mounts), "ext4")
        self.assertEqual(store.mount_type("/mnt/nas/lutin/donnees", mounts), "nfs4")
        self.assertEqual(store.mount_type("/mnt/my share/donnees", mounts), "cifs", "a space is written \\040")
        self.assertEqual(store.mount_type("/mnt/nas/local/donnees", mounts), "ext4", "the longest mount point wins")
        self.assertEqual(store.mount_type("/mnt/nasty", mounts), "ext4", "a prefix of the name is not a parent folder")
        self.assertFalse(store.on_network_share(self.data), "a temporary folder is on a local disk")
        self.assertEqual(store.notices(), [])
        with mock.patch.object(store, "on_network_share", return_value=True):
            self.assertEqual([level for level, _ in store.notices()], ["attention"])
            from lutin import health
            with mock.patch.object(health, "assess_health", return_value={"niveau": "ok", "items": []}), \
                    mock.patch.object(health, "model_size", return_value=0), mock.patch.object(A, "ps_modele", return_value=None), \
                    mock.patch.object(A, "mesures_systeme", return_value={}):
                state = health.health_state(A.reglages())
            self.assertEqual((state["niveau"], [i["id"] for i in state["items"]]), ("attention", ["base"]))
        if sys.platform == "win32":
            self.assertTrue(store.on_network_share("\\\\server\\share\\donnees"))
            self.assertTrue(store.on_network_share("\\\\?\\UNC\\server\\share\\donnees"))
            self.assertFalse(store.on_network_share("\\\\?\\C:\\donnees"))

    def test_the_doctor_checks_the_database_read_only(self):
        from lutin import cli
        self.assertEqual([level for level, _ in cli.diagnostic_base(self.data)], ["info"], "no database yet")
        A.conv_write(A.conv_new())
        lines = cli.diagnostic_base(self.data)
        self.assertEqual([level for level, _ in lines], ["ok"])
        self.assertIn("1 conversation(s)", lines[0][1])

    def test_a_reader_never_sees_half_a_conversation(self):
        c = A.conv_new()
        stop, torn, errors = threading.Event(), [], []

        def writer():
            n = 0
            while not stop.is_set():
                n += 1
                c["messages"] = [{"role": "user", "content": str(n)}] * (n % 50 + 1)
                c["titre"] = str(len(c["messages"]))
                try:
                    A.conv_write(c)
                except Exception as error:  # noqa: BLE001
                    errors.append(error)
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for _ in range(400):
                read = A.conv_read(c["id"])
                if read["titre"] != "Nouvelle conversation" and int(read["titre"]) != len(read["messages"]):
                    torn.append((read["titre"], len(read["messages"])))
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual((torn, errors), ([], []))


if __name__ == "__main__":
    unittest.main()
