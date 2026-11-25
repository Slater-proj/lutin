"""`/api/v1/mcp-connectors`: the connectors of other programs, on the real server of tests/test_api_v1.py. The demonstration server of Lutin (`lutin.mcp_demo`) is really started to list its tools."""
import os
import sys
import unittest
from pathlib import Path

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import mcp, mcp_catalog  # noqa: E402

SRC = str(Path(__file__).resolve().parent.parent / "src")


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Connectors(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self.clean)

    def clean(self):
        mcp.close()
        for identifier in list(mcp.read()["serveurs"]):
            mcp.remove(identifier)

    def demo(self):
        status, answer = call("POST", "/api/v1/mcp-connectors", {"name": "Demo", "command": [sys.executable, "-m", "lutin.mcp_demo"], "env": {"PYTHONPATH": SRC, "SECRET_KEY": "s3cret-value"}})
        self.assertEqual(status, 201)
        return answer["connectors"][0]

    def test_a_connector_is_added_refreshed_allowed_and_removed_and_its_secrets_are_never_given_back(self):
        connector = self.demo()
        self.assertEqual((connector["name"], connector["kind"], connector["active"], connector["read_only"], connector["tools"]), ("Demo", "command", True, True, []), "nothing is started, nothing is allowed")
        self.assertEqual(connector["env_names"], ["PYTHONPATH", "SECRET_KEY"])
        self.assertNotIn("s3cret-value", repr(call("GET", "/api/v1/mcp-connectors")[1]))
        status, answer = call("POST", "/api/v1/mcp-connectors/%s/refresh" % connector["id"], {})
        self.assertEqual(status, 200)
        self.assertGreater(answer["tool_count"], 0, "the demonstration program was started and listed its tools")
        tools = call("GET", "/api/v1/mcp-connectors")[1]["connectors"][0]["tools"]
        self.assertEqual(len(tools), answer["tool_count"])
        self.assertFalse(any(tool["allowed"] for tool in tools), "a tool is given to the model only when it is allowed")
        name = tools[0]["name"]
        status, answer = call("PATCH", "/api/v1/mcp-connectors/" + connector["id"], {"tool": name, "allowed": True})
        self.assertEqual(status, 200)
        self.assertEqual([tool["name"] for tool in answer["connectors"][0]["tools"] if tool["allowed"]], [name])
        status, answer = call("PATCH", "/api/v1/mcp-connectors/" + connector["id"], {"active": False, "read_only": False})
        self.assertEqual((answer["connectors"][0]["active"], answer["connectors"][0]["read_only"]), (False, False))
        status, answer = call("DELETE", "/api/v1/mcp-connectors/" + connector["id"])
        self.assertEqual((status, answer["connectors"]), (200, []))

    def test_a_server_by_address_is_added_without_a_command_and_both_at_once_is_refused(self):
        status, answer = call("POST", "/api/v1/mcp-connectors", {"name": "Remote", "url": "https://example.invalid/mcp", "headers": {"Authorization": "Bearer abc"}})
        self.assertEqual(status, 201)
        remote = answer["connectors"][0]
        self.assertEqual((remote["kind"], remote["url"], remote["header_names"]), ("http", "https://example.invalid/mcp", ["Authorization"]))
        self.assertNotIn("Bearer abc", repr(answer))
        for body in ({"name": "Both", "command": "prog", "url": "https://example.invalid/x"}, {"name": "Neither"}, {"name": "Bad", "url": "ftp://example.invalid"}):
            status, answer = call("POST", "/api/v1/mcp-connectors", body)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), body)
        self.assertEqual(len(mcp.read()["serveurs"]), 1)

    def test_refused_requests_say_why(self):
        self.assertEqual(call("POST", "/api/v1/mcp-connectors", {"name": "x", "colour": "red"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("DELETE", "/api/v1/mcp-connectors/nope")[0], 404)
        self.assertEqual(call("POST", "/api/v1/mcp-connectors/nope/refresh", {})[0], 404)
        connector = self.demo()
        for body in ({}, {"tool": "x"}, {"allowed": True}, {"active": "yes"}, {"colour": 1}, {"env": {"A": 1}}):
            self.assertEqual(call("PATCH", "/api/v1/mcp-connectors/" + connector["id"], body)[1]["error"]["code"], "invalid_request", body)
        status, answer = call("PATCH", "/api/v1/mcp-connectors/" + connector["id"], {"tool": "unknown", "allowed": True})
        self.assertEqual(status, 400, "a tool that was never listed cannot be allowed: refresh first")

    def test_a_paired_device_may_read_but_not_add_change_remove_or_start_one(self):
        self.assertEqual(call("GET", "/api/v1/mcp-connectors", who=V.DEVICE)[0], 200)
        for method, path in (("POST", "/api/v1/mcp-connectors"), ("PATCH", "/api/v1/mcp-connectors/abc"), ("DELETE", "/api/v1/mcp-connectors/abc"), ("POST", "/api/v1/mcp-connectors/abc/refresh")):
            self.assertEqual(call(method, path, {}, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


class Catalog(unittest.TestCase):
    """`/api/v1/mcp-catalog`: the shipped connectors, and their one-click installation (the program that runs a server is replaced by Lutin's demonstration server)."""

    def setUp(self):
        self.addCleanup(self.clean)

    def clean(self):
        mcp.close()
        mcp.write({"serveurs": {}})

    def test_the_catalogue_is_listed_with_english_field_types_and_marks_what_is_installed(self):
        status, answer = call("GET", "/api/v1/mcp-catalog")
        self.assertEqual(status, 200)
        entries = answer["entries"]
        self.assertEqual([entry["id"] for entry in entries], [entry["id"] for entry in mcp_catalog.load()])
        for entry in entries:
            self.assertEqual(sorted(entry), ["category", "description", "fields", "id", "installed", "name", "prerequisite", "runner", "version"])
            for field in entry["fields"]:
                self.assertIn(field["type"], ("folder", "file", "url", "secret"), entry["id"])
                self.assertEqual(sorted(field), ["example", "key", "label", "multiple", "required", "type"])
        self.assertFalse(any(entry["installed"] for entry in entries))
        files = next(entry for entry in entries if entry["id"] == "files" or entry["id"] == "fichiers")
        self.assertEqual((files["runner"], files["fields"][0]["type"], files["fields"][0]["multiple"]), ("npx", "folder", True))

    def test_an_entry_is_installed_tried_and_only_its_read_only_tools_are_allowed(self):
        entry = {"id": "demo", "nom": {"fr": "Demo", "en": "Demo"}, "execution": "uvx", "paquet": "lutin.mcp_demo", "version": "1", "champs": [], "arguments": [],
                 "description": {"fr": "x", "en": "x"}, "categorie": "test"}
        before = (mcp_catalog.load, mcp_catalog.program, mcp_catalog.build)
        original_build = mcp_catalog.build
        mcp_catalog.load = lambda: [entry]
        mcp_catalog.program = lambda execution, chercher=None: sys.executable
        mcp_catalog.build = lambda e, saisie, chercher=None: ([sys.executable, "-m", "lutin.mcp_demo"],) + original_build(e, saisie, chercher)[1:]
        old_path = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = SRC + (os.pathsep + old_path if old_path else "")
        try:
            status, answer = call("POST", "/api/v1/mcp-catalog/demo/install", {"input": {}})
            self.assertEqual(status, 200, answer)
            self.assertGreaterEqual(answer["tool_count"], 1)
            stored = mcp.read()["serveurs"][answer["connector"]]
            self.assertEqual(stored["catalogue"], "demo")
            self.assertTrue(stored["lecture_seule"])
            self.assertEqual(answer["allowed_count"], len([name for name, tool in stored["outils"].items() if tool["autorise"]]))
            self.assertTrue(call("GET", "/api/v1/mcp-catalog")[1]["entries"][0]["installed"])
            self.assertEqual(call("GET", "/api/v1/mcp-connectors")[1]["connectors"][0]["id"], answer["connector"])
            status, answer = call("POST", "/api/v1/mcp-catalog/demo/install", {"input": {}})
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "an entry is plugged in once")
        finally:
            mcp_catalog.load, mcp_catalog.program, mcp_catalog.build = before
            if old_path is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old_path

    def test_a_download_waits_for_a_confirmation_and_the_values_are_checked_before_it(self):
        before = mcp_catalog.program
        mcp_catalog.program = lambda execution, chercher=None: ""        # the program that runs the server is missing
        try:
            entry = next(e for e in call("GET", "/api/v1/mcp-catalog")[1]["entries"] if e["runner"] == "uvx" and e["fields"])
            status, answer = call("POST", "/api/v1/mcp-catalog/%s/install" % entry["id"], {"input": {}})
            self.assertEqual((status, answer["error"]["code"]), (400, "confirmation_required"))
            self.assertEqual(answer["error"]["message"], entry["prerequisite"])
            status, answer = call("POST", "/api/v1/mcp-catalog/%s/install" % entry["id"], {"input": {entry["fields"][0]["key"]: "/does/not/exist"}, "confirm": True})
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "a wrong value is refused before anything is downloaded")
        finally:
            mcp_catalog.program = before
        self.assertEqual(mcp.read()["serveurs"], {})

    def test_refused_requests_say_why_and_a_device_may_look_but_not_install(self):
        self.assertEqual(call("POST", "/api/v1/mcp-catalog/nope/install", {})[0], 404)
        for body in ({"colour": 1}, {"input": "x"}, {"confirm": "yes"}):
            self.assertEqual(call("POST", "/api/v1/mcp-catalog/git/install", body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(call("GET", "/api/v1/mcp-catalog", who=V.DEVICE)[0], 200)
        self.assertEqual(call("POST", "/api/v1/mcp-catalog/git/install", {}, who=V.DEVICE)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
