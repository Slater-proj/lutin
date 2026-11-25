"""The English names of the environment variables (lutin.environment): they fill the original names, and an original name that is set always wins."""
import subprocess
import sys
import unittest

import context  # noqa: F401

from lutin import environment  # noqa: E402


class Aliases(unittest.TestCase):
    def test_an_english_name_fills_the_original_one(self):
        environ = {"LUTIN_ROOT": "/work", "LUTIN_OFFLINE": "1"}
        self.assertEqual(sorted(environment.apply(environ)), ["LUTIN_HORS_LIGNE", "LUTIN_RACINE"])
        self.assertEqual((environ["LUTIN_RACINE"], environ["LUTIN_HORS_LIGNE"]), ("/work", "1"))
        self.assertEqual(environ["LUTIN_ROOT"], "/work", "nothing is removed: a program started by Lutin sees both")

    def test_an_original_name_that_is_set_wins(self):
        environ = {"LUTIN_ROOT": "/new", "LUTIN_RACINE": "/old"}
        self.assertEqual(environment.apply(environ), [])
        self.assertEqual(environ["LUTIN_RACINE"], "/old")

    def test_nothing_set_nothing_done_and_every_name_is_distinct(self):
        self.assertEqual(environment.apply({}), [])
        names = list(environment.ALIASES) + list(environment.ALIASES.values())
        self.assertEqual(len(set(names)), len(names), "an alias never points to a name that is itself an alias or a double")

    def test_the_package_applies_them_when_it_starts(self):
        code = "import os; import lutin; print(os.environ.get('LUTIN_SANS_DEMARRAGE'))"
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"LUTIN_NO_STARTUP": "1", "PYTHONPATH": str(context.SRC), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
        self.assertEqual(done.stdout.strip(), "1", done.stderr)


if __name__ == "__main__":
    unittest.main()
