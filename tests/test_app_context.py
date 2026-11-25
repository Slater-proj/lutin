"""ADR 0014, stage 1: the environment is read once, by the application context, and the old module names (core.ROOT, core.OLLAMA, web.DDG_URL…)
read and write it. A patch, a plain assignment and a change of context leave the context, the module attribute and the bare name inside the module equal."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import app_context, core, web, web_search


def built(**environ):
    return app_context.AppContext.from_env(environ, cwd=tempfile.mkdtemp(prefix="lutin-ctx-"), home=tempfile.mkdtemp(prefix="lutin-home-"))


class ReadOnce(unittest.TestCase):
    def test_each_variable_is_read_into_its_setting(self):
        root = tempfile.mkdtemp(prefix="lutin-root-")
        s = app_context.Settings.from_env({"LUTIN_RACINE": root, "LUTIN_DONNEES": "/d/donnees", "LUTIN_MEMOIRE": "/m", "OLLAMA_URL": "http://o:1/",
                                           "LUTIN_OUTIL_URL": "http://t:2/", "LUTIN_PORT": "9001", "LUTIN_CATALOGUE": "/c.json", "LUTIN_MODELE": "x:1b",
                                           "LUTIN_SANS_GARDE": "1", "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_RECHERCHE_URL": "http://ddg/", "LUTIN_BRAVE_URL": "http://b/",
                                           "LUTIN_TAVILY_URL": "http://t/", "LUTIN_EXA_URL": "http://e/", "LUTIN_PERPLEXITY_URL": "http://p/"})
        self.assertEqual(s.root, Path(root).resolve())
        self.assertEqual((s.data, s.memory), (Path("/d/donnees"), Path("/m")))
        self.assertEqual((s.ollama_url, s.tool_url), ("http://o:1", "http://t:2"), "the trailing slash is dropped, as before")
        self.assertEqual((s.port, s.catalogue, s.default_model), (9001, "/c.json", "x:1b"))
        self.assertEqual((s.resource_guard, s.auto_start), (False, False))
        self.assertEqual((s.search_ddg_url, s.search_brave_url, s.search_tavily_url, s.search_exa_url, s.search_perplexity_url),
                         ("http://ddg/", "http://b/", "http://t/", "http://e/", "http://p/"))

    def test_the_defaults_are_those_of_before(self):
        cwd, home = tempfile.mkdtemp(prefix="lutin-cwd-"), tempfile.mkdtemp(prefix="lutin-home-")
        s = app_context.Settings.from_env({}, cwd=cwd, home=home)
        self.assertEqual(s.root, Path(cwd).resolve())
        self.assertEqual(s.data, Path(home) / ".lutin" / "donnees")
        self.assertEqual(s.memory, Path(home) / ".lutin" / "memoire")
        self.assertEqual((s.ollama_url, s.tool_url, s.port, s.catalogue, s.default_model), ("http://127.0.0.1:11434", "", 8777, None, "qwen3:8b"))
        self.assertEqual((s.resource_guard, s.auto_start), (True, True))
        self.assertEqual(s.search_ddg_url, "https://html.duckduckgo.com/html/")

    def test_the_memory_folder_follows_the_data_folder_when_it_is_not_given(self):
        self.assertEqual(app_context.Settings.from_env({"LUTIN_DONNEES": "/x/donnees"}).memory, Path("/x/memoire"))

    def test_the_settings_cannot_be_changed_in_place(self):
        with self.assertRaises(AttributeError):
            app_context.current().settings.port = 1          # a change goes through app_context.change, which keeps the mirrors right


class TheNamesReadTheContext(unittest.TestCase):
    def assertSame(self, name, value):
        self.assertEqual(getattr(core, name), value, "read through the module")
        self.assertEqual(core.__dict__[name], value, "the bare name inside core reads the same")

    def test_the_names_of_core_are_those_of_the_context(self):
        s = app_context.current().settings
        for name, value in (("ROOT", s.root), ("DATA", s.data), ("MEMORY", s.memory), ("OLLAMA", s.ollama_url), ("TOOL_URL", s.tool_url),
                            ("PORT", s.port), ("RESOURCE_GUARD", s.resource_guard), ("AUTO_START", s.auto_start)):
            self.assertSame(name, value)
        self.assertEqual(web.DDG_URL, s.search_ddg_url)
        self.assertEqual(web_search.BRAVE_URL, s.search_brave_url)

    def test_an_assignment_writes_the_context(self):
        before = core.OLLAMA
        try:
            core.OLLAMA = "http://127.0.0.1:1234"
            self.assertEqual(app_context.current().settings.ollama_url, "http://127.0.0.1:1234")
            self.assertSame("OLLAMA", "http://127.0.0.1:1234")
        finally:
            core.OLLAMA = before
        self.assertSame("OLLAMA", before)

    def test_a_patch_is_seen_everywhere_and_put_back(self):
        before = core.PORT
        with mock.patch.object(core, "PORT", 4321):
            self.assertEqual(app_context.current().settings.port, 4321)
            self.assertSame("PORT", 4321)
        self.assertEqual(app_context.current().settings.port, before)
        self.assertSame("PORT", before)
        with mock.patch.object(web_search, "EXA_URL", "http://127.0.0.1:5/"):
            self.assertEqual(app_context.current().settings.search_exa_url, "http://127.0.0.1:5/")
            self.assertEqual(web_search.__dict__["EXA_URL"], "http://127.0.0.1:5/")
        self.assertEqual(web_search.EXA_URL, app_context.current().settings.search_exa_url)

    def test_a_new_context_changes_every_name_and_the_old_one_comes_back(self):
        before = app_context.current()
        other = built(OLLAMA_URL="http://127.0.0.1:7", LUTIN_PORT="7000", LUTIN_DONNEES="/elsewhere/donnees", LUTIN_RECHERCHE_URL="http://127.0.0.1:8/")
        with app_context.scope(other):
            self.assertIs(app_context.current(), other)
            self.assertSame("OLLAMA", "http://127.0.0.1:7")
            self.assertSame("PORT", 7000)
            self.assertSame("MEMORY", Path("/elsewhere/memoire"))
            self.assertEqual(web.__dict__["DDG_URL"], "http://127.0.0.1:8/")
            self.assertIn(Path("/elsewhere/donnees"), core.lutin_folders(), "a function of core reads the new folders")
        self.assertIs(app_context.current(), before)
        self.assertSame("OLLAMA", before.settings.ollama_url)
        self.assertSame("PORT", before.settings.port)

    def test_another_thread_reads_the_same_context(self):
        seen = []
        with mock.patch.object(core, "OLLAMA", "http://127.0.0.1:2"):
            worker = threading.Thread(target=lambda: seen.append(core.OLLAMA))          # the server answers each request in a new thread
            worker.start()
            worker.join(5)
        self.assertEqual(seen, ["http://127.0.0.1:2"])

    def test_a_new_working_folder_goes_through_the_context(self):
        before = core.ROOT
        elsewhere = Path(tempfile.mkdtemp(prefix="lutin-root-"))
        try:
            core.set_root(elsewhere)
            self.assertEqual(app_context.current().settings.root, elsewhere.resolve())
            self.assertSame("ROOT", elsewhere.resolve())
        finally:
            core.set_root(before)
        self.assertSame("ROOT", before)

    def test_only_a_setting_can_be_bound(self):
        with self.assertRaises(ValueError):
            app_context.bind(__name__, {"X": "not_a_setting"})


if __name__ == "__main__":
    unittest.main()
