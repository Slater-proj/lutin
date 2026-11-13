"""`GET` and `PATCH /api/v1/settings`: the settings under their v1 names, on the real server of tests/test_api_v1.py (« network » level).

What is fixed here: one English name and one kind for every stored setting (the table is compared with `lutin.core.REGLAGES_DEFAUT`, so a setting added
without a v1 name fails a test), the words translated in both directions, and a write that is all or nothing."""
import os
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1  # noqa: E402
from lutin import modes  # noqa: E402

A = V.A
KIND_OF = {bool: "boolean", int: "integer", float: "number", str: "string", list: "strings", dict: "object"}


def setUpModule():
    V.setUpModule()


def invalid(name, expected):
    return 400, {"error": {"code": "invalid_request", "message": "Valeur invalide pour « {} » (attendu : {}).".format(name, expected)}}


class Table(unittest.TestCase):
    def test_every_stored_setting_has_one_v1_name(self):
        stored = [key for key, _ in api_v1.SETTINGS.values()]
        self.assertEqual(sorted(stored), sorted(A.REGLAGES_DEFAUT), "a setting without a v1 name, or a v1 name for a setting that no longer exists")
        self.assertEqual(len(stored), len(set(stored)))
        for name in api_v1.SETTINGS:
            self.assertRegex(name, r"^[a-z][a-z0-9_]*$")

    def test_the_declared_kind_is_the_kind_of_the_default_value(self):
        for name, (key, kind) in api_v1.SETTINGS.items():
            default = A.REGLAGES_DEFAUT[key]
            if default is None:
                self.assertTrue(kind.endswith("?"), "{}: null is its default, the kind must accept it".format(name))
            else:
                self.assertEqual(kind.rstrip("?"), KIND_OF[type(default)], name)
            self.assertIn(kind.rstrip("?"), api_v1.KINDS, name)

    def test_the_translated_words_cover_what_the_server_accepts(self):
        words = {name: sorted(table) for name, table in api_v1.SETTING_WORDS.items()}
        self.assertEqual(words, {"mode": sorted(set(modes.ids()) - {"mission"}), "thinking_steps": ["premier", "toujours"], "long_memory": ["demander", "fichier", "resume"],
                                 "auto_recall": sorted(A.CHOIX_RAPPELS)}, "« mission » is chosen conversation by conversation, never as a setting")
        for name, table in api_v1.SETTING_WORDS.items():
            self.assertEqual(len(set(table.values())), len(table), name)
            self.assertEqual(api_v1.SETTINGS[name][1], "string", name)


class Settings(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: (A.DONNEES / "reglages.json").unlink(missing_ok=True))

    def test_reading_gives_every_setting_under_its_v1_name(self):
        status, answer = V.call("GET", "/api/v1/settings", V.OWNER)
        self.assertEqual((status, sorted(answer)), (200, sorted(api_v1.SETTINGS)))
        self.assertEqual((answer["mode"], answer["long_memory"], answer["thinking_steps"], answer["auto_recall"]), ("general", "ask", "always", "scenario"))
        self.assertEqual((answer["temperature"], answer["web"], answer["top_p"], answer["cluster"], answer["disabled_tools"], answer["models_by_engine"]), (0.6, True, None, None, [], {}))
        self.assertEqual((answer["engine"], answer["max_steps"], answer["tool_command_timeout_s"]), ("ollama", 14, 240))

    def test_a_change_is_stored_under_the_french_names_and_bounded_by_the_server(self):
        status, answer = V.call("PATCH", "/api/v1/settings", V.OWNER, body={"temperature": 0.4, "web": False, "mode": "technical", "long_memory": "file", "top_p": 0.9, "max_steps": 99,
                                                                               "model": "qwen3:4b", "disabled_tools": ["calculer"], "thinking_steps": "first"})
        self.assertEqual((status, sorted(answer)), (200, sorted(api_v1.SETTINGS)))
        self.assertEqual((answer["temperature"], answer["web"], answer["mode"], answer["long_memory"], answer["top_p"], answer["model"], answer["disabled_tools"], answer["thinking_steps"]),
                         (0.4, False, "technical", "file", 0.9, "qwen3:4b", ["calculer"], "first"))
        self.assertEqual(answer["max_steps"], 40, "bounded by the server, as for the French route")
        stored = A.reglages()
        self.assertEqual((stored["temperature"], stored["web"], stored["mode"], stored["memoire_longue"], stored["tours_max"], stored["modele"], stored["reflexion_tours"]),
                         (0.4, False, "technique", "fichier", 40, "qwen3:4b", "premier"))
        self.assertEqual(V.call("GET", "/api/v1/settings", V.OWNER)[1], answer)
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"top_p": None})[1]["top_p"], None, "null: back to automatic")
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={})[1]["temperature"], 0.4, "nothing asked, nothing changed")

    def test_a_paired_device_reads_and_changes_them_as_with_the_french_route(self):
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.DEVICE, body={"web": False})[1]["web"], False)
        self.assertEqual(V.call("GET", "/api/v1/settings", V.DEVICE)[1]["web"], False)

    def test_a_write_is_all_or_nothing(self):
        before = V.call("GET", "/api/v1/settings", V.OWNER)[1]
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"web": False, "modele": "x", "auto": 1}),
                         (400, {"error": {"code": "invalid_request", "message": "Réglage inconnu : auto, modele."}}))
        refused = (({"web": "yes"}, "web", "boolean"), ({"temperature": True}, "temperature", "number"), ({"max_steps": 1.5}, "max_steps", "integer"),
                   ({"top_p": "x"}, "top_p", "number or null"), ({"cluster": 1}, "cluster", "boolean or null"), ({"model": None}, "model", "string"),
                   ({"disabled_tools": [1]}, "disabled_tools", "strings"), ({"models_by_engine": {"ollama": 3}}, "models_by_engine", "object"),
                   ({"mode": "polyvalent"}, "mode", "general, technical, scenario, research, chat"), ({"mode": "mission"}, "mode", "general, technical, scenario, research, chat"),
                   ({"long_memory": "resume"}, "long_memory", "summary, file, ask"), ({"auto_recall": 3}, "auto_recall", "scenario, always, never"))
        for body, name, expected in refused:
            self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body=dict({"web": False}, **body)), invalid(name, expected), body)
        self.assertEqual(V.call("GET", "/api/v1/settings", V.OWNER)[1], before, "nothing was written by a refused request")

    def test_what_the_server_refuses_underneath_is_an_error_with_a_code(self):
        before = V.call("GET", "/api/v1/settings", V.OWNER)[1]
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"model": "not a name!"}), (400, {"error": {"code": "invalid_request", "message": "Nom de modèle invalide."}}))
        self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"engine": "nope"}), (400, {"error": {"code": "invalid_request", "message": "Moteur inconnu."}}))
        status, answer = V.call("PATCH", "/api/v1/settings", V.OWNER, body={"commands_without_approval": ["rm -rf build"]})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "a dangerous command is refused, not silently dropped")
        status, answer = V.call("PATCH", "/api/v1/settings", V.OWNER, body={"disabled_tools": ["no_such_tool"]})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertEqual(V.call("GET", "/api/v1/settings", V.OWNER)[1], before)

    def test_messages_follow_the_language(self):
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"modele": "x"})[1]["error"]["message"], "Unknown setting: modele.")
            self.assertEqual(V.call("PATCH", "/api/v1/settings", V.OWNER, body={"web": 1})[1]["error"]["message"], "Invalid value for « web » (expected: boolean).")


if __name__ == "__main__":
    unittest.main()
