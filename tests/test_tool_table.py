"""The tool table (lutin.tool_table): one entry per tool offered to the models, and the lists the code derives from it. Conformance, like the access test for routes."""
import inspect
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-tool-table-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir()

from lutin import addons_comfyui, addons_voicestudio, modes, page_preview, tool_table, tools  # noqa: E402

HISTORICAL_RESEARCH = {"lister", "lire", "chercher", "trouver", "calculer", "voix_liste", "voix_transcrire", "symboles", "lire_plusieurs", "rappeler", "web_chercher", "web_lire", "taches",
                       "memoriser", "suivi", "comfy_modeles"}          # the list written by hand in modes.py before the table
FUNCTIONS = {"ecrire": tools.outil_ecrire, "modifier_plusieurs": tools.outil_modifier_plusieurs, "creer_document": tools.outil_document, "executer": tools.outil_executer,
             "installer_module": tools.outil_installer_module, "apercu_page": page_preview.tool_preview, "voix_parler": addons_voicestudio.outil_parler,
             "voix_cloner": addons_voicestudio.outil_cloner, "comfy_generer": addons_comfyui.outil_generer,
             "lister": tools.outil_lister, "lire": tools.outil_lire, "chercher": tools.outil_chercher, "symboles": tools.outil_symboles, "lire_plusieurs": tools.outil_lire_plusieurs,
             "voix_transcrire": addons_voicestudio.outil_transcrire}


class ToolTable(unittest.TestCase):
    def test_every_tool_offered_to_the_models_has_an_entry_and_no_entry_is_orphan(self):
        offered = {tool["function"]["name"] for tool in tools.OUTILS}
        self.assertEqual(offered - set(tool_table.TABLE), set(), "a tool without an entry: the loop, the research mode and the approvals would not know what it does")
        self.assertEqual(set(tool_table.TABLE) - offered, set(), "an entry for a tool that does not exist")

    def test_every_entry_is_well_formed(self):
        for name, tool in tool_table.TABLE.items():
            self.assertIn(tool.effect, tool_table.EFFECTS, name)
            self.assertIsInstance(tool.asks, bool, name)
            self.assertIsInstance(tool.network, bool, name)
            if tool.effect in (tool_table.READ, tool_table.NOTES, tool_table.CONTROL):
                self.assertFalse(tool.asks, "%s only reads or notes: it has nothing to ask" % name)
            if tool.effect in (tool_table.FILES, tool_table.COMMAND):
                self.assertTrue(tool.asks, "%s changes the machine: it must ask" % name)

    def test_the_tools_left_out_on_a_small_window_exist_and_their_cover_stays(self):
        self.assertLessEqual(tool_table.SPARE_ON_SMALL_WINDOW, set(tool_table.TABLE))
        covers = {"lire_plusieurs": "lire", "modifier_plusieurs": "modifier", "symboles": "chercher", "apercu_page": "web_lire"}
        self.assertEqual(set(covers), set(tool_table.SPARE_ON_SMALL_WINDOW), "each spare tool says which one covers it")
        for spare, cover in covers.items():
            self.assertNotIn(cover, tool_table.SPARE_ON_SMALL_WINDOW, spare)
            self.assertEqual(tool_table.TABLE[spare].effect, tool_table.TABLE[cover].effect if spare != "apercu_page" else tool_table.EXTERNAL, spare)

    def test_on_a_tiny_window_each_tool_left_out_has_a_cover_still_sent_or_is_a_known_loss(self):
        """ADR 0018, 4,096 tokens: a core only. What it leaves out is either done by a tool still sent, or lost on purpose (maintainer's decision)."""
        tiny = tool_table.spare_tools(tool_table.TINY_WINDOW)
        self.assertLessEqual(tiny, set(tool_table.TABLE))
        self.assertLessEqual(tool_table.spare_tools(tool_table.SMALL_WINDOW), tiny, "what a small window leaves out, a tiny one leaves out too")
        covers = {"lire_plusieurs": "lire", "modifier_plusieurs": "modifier", "symboles": "chercher", "apercu_page": "lire",          # the source of the page, not its picture
                  "lister": "executer", "trouver": "executer", "calculer": "executer", "creer_document": "ecrire"}
        self.assertEqual(set(covers) | tool_table.LOST_ON_TINY_WINDOW, set(tiny), "each tool left out says which one covers it, or that it is lost")
        self.assertEqual(set(covers) & tool_table.LOST_ON_TINY_WINDOW, set())
        for spare, cover in covers.items():
            self.assertNotIn(cover, tiny, "%s: its cover %s must still be sent" % (spare, cover))
        self.assertEqual(tool_table.LOST_ON_TINY_WINDOW, {"taches", "web_chercher", "web_lire"}, "a new loss is a decision of the maintainer, not of a test")
        self.assertNotIn("memoriser", tiny, "nothing replaces the durable notes: they stay")

    def test_the_window_size_picks_the_tools_left_out(self):
        self.assertEqual(tool_table.spare_tools(4096), tool_table.SPARE_ON_TINY_WINDOW)
        self.assertEqual(tool_table.spare_tools(2048), tool_table.SPARE_ON_TINY_WINDOW)
        self.assertEqual(tool_table.spare_tools(4097), tool_table.SPARE_ON_SMALL_WINDOW)
        self.assertEqual(tool_table.spare_tools(8192), tool_table.SPARE_ON_SMALL_WINDOW)
        for unknown in (8193, 0, None, "", "abc"):
            self.assertEqual(tool_table.spare_tools(unknown), frozenset(), repr(unknown))

    def test_the_research_mode_keeps_exactly_what_it_kept(self):
        self.assertEqual(tool_table.research_tools(), HISTORICAL_RESEARCH, "no behaviour change: the derived list is the one written by hand before")
        self.assertEqual(modes.READ_TOOLS, tool_table.research_tools(), "modes reads the table")

    def test_a_tool_that_asks_really_asks_and_one_that_does_not_never_does(self):
        """Read in the source of each tool: the table cannot say « asks » for a tool that never calls the approval, nor the opposite."""
        for name, function in FUNCTIONS.items():
            source = inspect.getsource(function)
            calls = 'ctx["accord"]' in source or "outil_modifier_plusieurs" in source
            self.assertEqual(calls, tool_table.TABLE[name].asks, name)


if __name__ == "__main__":
    unittest.main()
