"""`/api/v1/access` (docs/modernization/PARITY.md, item 9): the access level saved for the next start and the remote administration, on the real
server of tests/test_api_v1.py (level « network »). Both open the machine: only this machine changes them, never a paired device.

Hermetic: config.json is the temporary one of test_api_v1, put back as it was after each test; nothing restarts."""
import os
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import access

A = V.A


def setUpModule():
    V.setUpModule()


class Access(unittest.TestCase):
    def setUp(self):
        path = A.chemin_config()
        before = path.read_bytes() if path.is_file() else None
        self.addCleanup(lambda: path.write_bytes(before) if before is not None else path.unlink(missing_ok=True))
        cfg = A.config_lue()
        cfg["securite"] = dict(vars(A.SECURITE), proxy_ips=list(A.SECURITE.proxy_ips))          # the level saved is the one running
        cfg.pop("admin_a_distance", None)
        A.config_ecrire(cfg)

    def view(self, who=None):
        status, answer = V.call("GET", "/api/v1/access", who or V.OWNER)
        self.assertEqual(status, 200, answer)
        return answer

    def test_the_level_running_and_saved_and_who_may_change_it(self):
        answer = self.view()
        self.assertEqual((answer["level"], answer["saved"]["level"], answer["restart_needed"]), ("network", "network", False))
        self.assertEqual([level["id"] for level in answer["levels"]], ["local", "network", "proxy"])
        self.assertTrue(answer["warnings"]["network"])
        self.assertEqual((answer["can_change"], answer["remote_admin"]), (True, {"active": False, "can_change": True}))
        device = self.view(V.DEVICE)
        self.assertEqual((device["can_change"], device["remote_admin"]["can_change"]), (False, False))

    def test_a_level_is_saved_for_the_next_start(self):
        status, answer = V.call("PATCH", "/api/v1/access", V.OWNER, {"level": "local"})
        self.assertEqual(status, 200, answer)
        self.assertEqual((answer["level"], answer["saved"]["level"], answer["restart_needed"]), ("network", "local", True), "running until the restart")
        self.assertTrue(V.call("GET", "/api/v1/status", V.OWNER)[1]["restart"]["needed"], "the shell's banner asks for it")

    def test_opening_needs_the_risks_understood_and_a_valid_proxy(self):
        V.call("PATCH", "/api/v1/access", V.OWNER, {"level": "local"})
        for body in ({"level": "network"}, {"level": "network", "understood": "yes"}, {"level": "proxy", "understood": True, "public_url": "http://example.org"},
                     {"level": "everyone", "understood": True}, {"level": "proxy", "understood": True, "proxy_ips": "10.0.0.1"}):
            status, answer = V.call("PATCH", "/api/v1/access", V.OWNER, body)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), body)
        self.assertEqual(self.view()["saved"]["level"], "local", "nothing saved by a refusal")
        status, answer = V.call("PATCH", "/api/v1/access", V.OWNER, {"level": "network", "understood": True})
        self.assertEqual((status, answer["saved"]["level"], answer["restart_needed"]), (200, "network", False))

    def test_a_paired_device_changes_neither(self):
        status, answer = V.call("PATCH", "/api/v1/access", V.DEVICE, {"level": "local"})
        self.assertEqual((status, answer["error"]["code"]), (403, "local_only"))
        status, answer = V.call("PATCH", "/api/v1/access/remote-admin", V.DEVICE, {"active": True})
        self.assertEqual((status, answer["error"]["code"]), (403, "local_only"))
        self.assertFalse(self.view()["remote_admin"]["active"])

    def test_the_remote_administration_opens_configuration_but_not_access(self):
        status, answer = V.call("PATCH", "/api/v1/access/remote-admin", V.OWNER, {"active": True})
        self.assertEqual((status, answer["remote_admin"]["active"]), (200, True))
        self.assertTrue(A.config_lue()["admin_a_distance"])
        self.assertTrue(V.call("GET", "/api/v1/status", V.DEVICE)[1]["access"]["can_configure"], "an admitted device may now configure")
        status, answer = V.call("PATCH", "/api/v1/access/remote-admin", V.DEVICE, {"active": False})
        self.assertEqual(status, 403, "but never take it back or widen it through itself")
        self.assertEqual(V.call("PATCH", "/api/v1/access", V.DEVICE, {"level": "local"})[0], 403)
        self.assertEqual(V.call("PATCH", "/api/v1/access/remote-admin", V.OWNER, {"active": "no"})[0], 400)
        status, answer = V.call("PATCH", "/api/v1/access/remote-admin", V.OWNER, {"active": False})
        self.assertEqual((status, answer["remote_admin"]["active"]), (200, False))
        self.assertFalse(V.call("GET", "/api/v1/status", V.DEVICE)[1]["access"]["can_configure"])

    def test_in_docker_both_come_from_the_container(self):
        with mock.patch.object(access, "in_docker", lambda: True), mock.patch.dict(os.environ, {"LUTIN_ADMIN_TOUS": ""}):
            self.assertFalse(self.view()["can_change"])
            status, answer = V.call("PATCH", "/api/v1/access", V.OWNER, {"level": "local"})
            self.assertEqual((status, answer["error"]["code"]), (409, "in_docker"))
            status, answer = V.call("PATCH", "/api/v1/access/remote-admin", V.OWNER, {"active": True})
            self.assertEqual((status, answer["error"]["code"]), (409, "in_docker"))


if __name__ == "__main__":
    unittest.main()
