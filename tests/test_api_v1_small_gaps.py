"""The last gaps of docs/modernization/PARITY.md (item 18) on `/api/v1`: the demonstration connector, the helper programs, one message pinned and the
raw web results of « Verify », on the real server of tests/test_api_v1.py (strict offline mode, as set there).

Hermetic: the connectors live in the temporary data folder (the demonstration one is added, never started); the helper programs and the web search are
replaced; the conversation is a temporary one."""
import os
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import external_programs, mcp, outbound, web

A = V.A


def setUpModule():
    V.setUpModule()


class SmallGaps(unittest.TestCase):
    def test_the_demonstration_connector_is_added_from_this_machine(self):
        before = {c["id"] for c in mcp.view()}
        self.addCleanup(lambda: [mcp.remove(c["id"]) for c in mcp.view() if c["id"] not in before])
        self.assertEqual(V.call("POST", "/api/v1/mcp-connectors/demo", V.DEVICE, {})[0], 403)
        status, answer = V.call("POST", "/api/v1/mcp-connectors/demo", V.OWNER, {})
        self.assertEqual(status, 201, answer)
        added = [c for c in mcp.view() if c["id"] not in before]
        self.assertEqual(len(added), 1)
        self.assertIn("lutin.mcp_demo", " ".join(added[0].get("commande") or added[0].get("command") or []))

    def test_the_helper_programs_are_listed_installed_and_removed(self):
        state = [{"nom": "uv", "libelle": "uv", "aide": "Pour Python.", "installe": False, "par_lutin": False, "version": ""}]
        done = []
        with mock.patch.object(external_programs, "state", lambda *args, **kwargs: state), mock.patch.object(external_programs, "install", lambda name: done.append(("install", name))), \
                mock.patch.object(external_programs, "uninstall", lambda name: done.append(("uninstall", name))):
            self.assertEqual(V.call("GET", "/api/v1/helper-programs", V.DEVICE)[1]["programs"][0]["name"], "uv")
            self.assertEqual(V.call("POST", "/api/v1/helper-programs/uv/install", V.OWNER, {})[1]["error"]["code"], "offline")
            with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": ""}):
                self.assertEqual(V.call("POST", "/api/v1/helper-programs/uv/install", V.OWNER, {})[0], 200)
            self.assertEqual(V.call("DELETE", "/api/v1/helper-programs/uv", V.DEVICE)[0], 403)
            self.assertEqual(V.call("DELETE", "/api/v1/helper-programs/uv", V.OWNER)[0], 200)
        self.assertEqual(done, [("install", "uv"), ("uninstall", "uv")])

    def test_one_message_is_pinned_and_unpinned(self):
        conversation = A.conv_new()
        conversation["messages"] = [{"role": "user", "content": "Ne jamais toucher à la production."}, {"role": "assistant", "content": "Compris."}]
        A.conv_write(conversation)
        self.addCleanup(lambda: A.conv_delete(conversation["id"]))
        path = "/api/v1/conversations/%s/messages/0" % conversation["id"]
        self.assertEqual(V.call("PATCH", path, V.DEVICE, {"pinned": True})[1], {"pinned": True, "count": 1})
        self.assertTrue(A.conv_read(conversation["id"])["messages"][0].get("epingle"))
        self.assertEqual(V.call("PATCH", path, V.DEVICE, {"pinned": False})[1], {"pinned": False, "count": 0})
        # built, not path.replace("/0", "/9"): an id starting with 0 (token_hex, one in sixteen) became another conversation, 404 instead of 400
        self.assertEqual(V.call("PATCH", "/api/v1/conversations/%s/messages/9" % conversation["id"], V.DEVICE, {"pinned": True})[0], 400)
        self.assertEqual(V.call("PATCH", path, V.DEVICE, {"pinned": "yes"})[0], 400)

    def test_verify_shows_the_raw_results_and_takes_out_what_is_personal(self):
        self.assertEqual(V.call("POST", "/api/v1/web-search/preview", V.DEVICE, {"q": "prix du kWh"})[1]["error"]["code"], "offline")
        found = [{"titre": "Prix du kWh", "url": "https://example.org/kwh", "extrait": "0,25 €", "source": "duckduckgo"}]
        with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": ""}), mock.patch.object(web, "search_results", lambda query, count: (found, [])), \
                mock.patch.object(outbound, "clean_query", lambda query: (query.replace("jean@example.org", "").strip(), ["jean@example.org"])):
            status, answer = V.call("POST", "/api/v1/web-search/preview", V.DEVICE, {"q": "prix du kWh jean@example.org"})
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["query"], answer["removed"]), ("prix du kWh", ["jean@example.org"]))
        self.assertEqual((answer["results"][0]["domain"], answer["results"][0]["title"]), ("example.org", "Prix du kWh"))
        self.assertEqual(V.call("POST", "/api/v1/web-search/preview", V.DEVICE, {"q": "a"})[0], 400)


if __name__ == "__main__":
    unittest.main()
