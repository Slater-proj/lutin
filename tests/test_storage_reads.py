"""Reading a data file while another thread replaces it (lutin.storage).

On Windows, opening a file at the moment `os.replace` swaps it raises PermissionError. `lire_json` took that for a missing file and gave the default:
a list of missions, a registry or a settings file read as empty for an instant (measured: about five reads in a hundred during a burst of writes).
The CI saw it as a mission that « no longer exists » (tests/test_web_app_chat.py, test 5q). What is fixed here: a reader never sees the default
because of a concurrent replace, and a file that is missing, damaged or of the wrong type still gives the default."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

from lutin import core  # noqa: E402,F401  (storage is loaded through core: importing it first is a circular import)
from lutin import storage  # noqa: E402


class ReadsDuringReplaces(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="lutin-storage-reads-"))
        self.target = self.folder / "missions.json"

    def test_a_reader_never_sees_the_default_while_the_file_is_replaced(self):
        payload = json.dumps([{"id": "0123abcd", "nom": "x" * 200}] * 20)
        storage.ecrire_atomique(self.target, payload)
        stop = threading.Event()
        writes = [0]

        def writer():
            while not stop.is_set():
                storage.ecrire_atomique(self.target, payload)
                writes[0] += 1
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        self.addCleanup(lambda: (stop.set(), thread.join(5)))
        reads = empty = 0
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            reads += 1
            if storage.lire_json(self.target, []) == []:
                empty += 1
        stop.set()
        thread.join(5)
        self.assertGreater(writes[0], 5, "the file was replaced while it was read")
        self.assertEqual(empty, 0, "{} reads of {} gave the default".format(empty, reads))

    def test_missing_damaged_or_of_another_type_gives_the_default(self):
        self.assertEqual(storage.lire_json(self.folder / "none.json", []), [])
        (self.folder / "damaged.json").write_text("[{", encoding="utf-8")
        self.assertEqual(storage.lire_json(self.folder / "damaged.json", []), [])
        (self.folder / "object.json").write_text("{}", encoding="utf-8")
        self.assertEqual(storage.lire_json(self.folder / "object.json", []), [])

    def test_a_file_that_stays_locked_gives_the_default_without_a_long_wait(self):
        self.target.write_text("[1]", encoding="utf-8")
        start = time.monotonic()
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("locked")):
            self.assertEqual(storage.lire_json(self.target, []), [])
        self.assertLess(time.monotonic() - start, 1.5, "a reader waits a moment, not forever")


if __name__ == "__main__":
    unittest.main()
