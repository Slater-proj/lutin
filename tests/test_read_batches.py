"""Read-only batches (plan step 5, item 4): the calls of one step that only read run together; everything else stays sequential, and the order is kept."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-read-batches-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir()

from lutin import core as _core  # noqa: E402,F401  (core first: agent is one of its parts)
from lutin import agent, tool_table  # noqa: E402


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


ALL = set(tool_table.TABLE)


class Batches(unittest.TestCase):
    def run_batches(self, calls, allowed=ALL, delay=0.0):
        running, most, done = [0], [0], []
        lock = threading.Lock()

        def execute(name, arguments):
            with lock:
                running[0] += 1
                most[0] = max(most[0], running[0])
            time.sleep(delay)
            with lock:
                running[0] -= 1
                done.append(name)
            if arguments.get("fail"):
                raise agent._m.ToolError("no such file")
            return "%s:%s" % (name, arguments.get("chemin", ""))

        futures = agent.lectures_groupees(calls, lambda name, raw: dict(raw or {}), execute, allowed)
        return futures, most, done

    def test_reads_that_follow_each_other_run_together_and_keep_their_place(self):
        calls = [call("lire", chemin="a"), call("lire", chemin="b"), call("chercher", chemin="c")]
        started = time.monotonic()
        futures, most, _ = self.run_batches(calls, delay=0.3)
        results = [futures[position].result() for position in sorted(futures)]
        self.assertEqual(results, ["lire:a", "lire:b", "chercher:c"], "each result is the one of ITS call")
        self.assertLess(time.monotonic() - started, 0.75, "three reads of 0.3 s took less than their sum")
        self.assertGreaterEqual(most[0], 2)

    def test_a_write_or_a_command_is_never_run_ahead_and_cuts_the_batch(self):
        calls = [call("lire", chemin="a"), call("ecrire", chemin="x"), call("lire", chemin="b"), call("lire", chemin="c"), call("executer", commande="x"), call("lire", chemin="d")]
        futures, _, done = self.run_batches(calls)
        self.assertEqual(sorted(futures), [2, 3], "only the two reads that follow each other; a read alone gains nothing")
        for future in futures.values():
            future.result()
        self.assertEqual(sorted(done), ["lire", "lire"])
        self.assertNotIn("ecrire", done)
        self.assertNotIn("executer", done)

    def test_what_is_not_a_plain_local_read_is_never_batched(self):
        for name in ("web_lire", "web_chercher", "rappeler", "memoriser", "taches", "apercu_page", "comfy_modeles"):
            self.assertEqual(self.run_batches([call(name), call(name)])[0], {}, name)
        self.assertEqual(self.run_batches([call("lire"), call("lire")], allowed={"chercher"})[0], {}, "a tool the mode does not allow is not run ahead")
        self.assertEqual(self.run_batches([])[0], {})
        self.assertEqual(self.run_batches([call("lire")])[0], {})

    def test_an_error_of_one_read_is_its_own_and_the_others_still_answer(self):
        futures, _, _ = self.run_batches([call("lire", chemin="a", fail=True), call("lire", chemin="b")])
        with self.assertRaises(agent._m.ToolError):
            futures[0].result()
        self.assertEqual(futures[1].result(), "lire:b")

    def test_at_most_four_reads_at_a_time(self):
        futures, most, _ = self.run_batches([call("lire", chemin=str(i)) for i in range(10)], delay=0.05)
        for future in futures.values():
            future.result()
        self.assertLessEqual(most[0], agent.LECTURES_ENSEMBLE)


if __name__ == "__main__":
    unittest.main()
