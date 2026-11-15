"""`/api/v1/mcp-connectors`: the connectors of other programs, on the real server of tests/test_api_v1.py. The demonstration server of Lutin (`lutin.mcp_demo`) is really started to list its tools."""
import sys
import unittest
from pathlib import Path

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import mcp  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
