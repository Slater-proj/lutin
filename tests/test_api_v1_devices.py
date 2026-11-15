"""`/api/v1/devices`: the paired devices and the pairing code, on the real server of tests/test_api_v1.py (level « network »). What is checked first is who may ask:
the code is for the person in front of the machine, never for a paired device; revoking ends a session for real."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import security as S  # noqa: E402

A = V.A


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Devices(unittest.TestCase):
    def test_the_list_shows_the_paired_devices_without_anything_that_opens_a_session(self):
        status, answer = call("GET", "/api/v1/devices")
        self.assertEqual((status, sorted(answer)), (200, ["address", "devices", "level", "pairing_possible"]))
        self.assertEqual((answer["level"], answer["pairing_possible"]), ("network", True))
        self.assertTrue(answer["devices"], "the session of the test is a paired device")
        for device in answer["devices"]:
            self.assertEqual(sorted(device), ["id", "name", "paired_at", "seen_at"])
            self.assertRegex(device["id"], r"^[0-9a-f]{10}$", "ten characters of a digest: not enough to be a token, and a token is never stored")
        self.assertEqual(call("GET", "/api/v1/devices", who=V.ELSEWHERE)[0], 401)

    def test_the_pairing_code_is_given_to_this_machine_only_and_pairs_a_device(self):
        status, answer = call("POST", "/api/v1/devices/pairing-code", {}, who=V.DEVICE)
        self.assertEqual((status, answer["error"]["code"]), (403, "local_only"), "a paired phone cannot mint a code for another device")
        self.assertEqual(call("POST", "/api/v1/devices/pairing-code", {}, who=V.ELSEWHERE)[0], 401)
        status, answer = call("POST", "/api/v1/devices/pairing-code", {})
        self.assertEqual((status, sorted(answer)), (201, ["address", "code", "qr", "valid_seconds"]))
        self.assertRegex(answer["code"], r"^\d{6,}$")
        self.assertEqual(answer["valid_seconds"], S.DURATION_PIN_S)
        self.assertEqual(len(answer["qr"]["rows"]), answer["qr"]["size"])
        self.assertTrue(all(len(row) == answer["qr"]["size"] and set(row) <= {"0", "1"} for row in answer["qr"]["rows"]), "a square of 0 and 1")
        self.assertTrue(answer["address"].startswith("http://"))
        before = len(A.APPAREILS.liste())
        self.assertIsNone(A.APPAREILS.appairer("000000" if answer["code"] != "000000" else "111111", "Wrong"), "a wrong code pairs nothing")
        token = A.APPAREILS.appairer(answer["code"], "Phone of the test")
        self.assertTrue(token and A.APPAREILS.valide(token))
        self.assertEqual(len(A.APPAREILS.liste()), before + 1)
        self.assertIsNone(A.APPAREILS.appairer(answer["code"], "Again"), "a code serves once")
        identifier = next(device["id"] for device in call("GET", "/api/v1/devices")[1]["devices"] if device["name"] == "Phone of the test")
        self.assertEqual(call("DELETE", "/api/v1/devices/" + identifier, who=V.DEVICE)[1]["error"]["code"], "configurator", "a paired device does not revoke another")
        status, answer = call("DELETE", "/api/v1/devices/" + identifier)
        self.assertEqual(status, 200)
        self.assertNotIn(identifier, [device["id"] for device in answer["devices"]])
        self.assertFalse(A.APPAREILS.valide(token), "revoked: the session is over for real")
        for unknown in ("0000000000", "x", "..%2Fx"):
            self.assertEqual(call("DELETE", "/api/v1/devices/" + unknown)[1]["error"]["code"], "not_found", unknown)

    def test_at_the_level_local_no_code_is_made(self):
        with mock.patch.object(A, "SECURITE", S.Securite(niveau=S.LOCAL)):
            self.assertEqual(call("GET", "/api/v1/devices")[1]["pairing_possible"], False)
            status, answer = call("POST", "/api/v1/devices/pairing-code", {})
            self.assertEqual((status, answer["error"]["code"]), (409, "local_only"))

    def test_revoking_everything_ends_every_session(self):
        spare = S.Appareils()
        with mock.patch.object(A, "APPAREILS", spare):
            token = spare.appairer(spare.nouveau_pin(), "One")
            self.assertTrue(spare.valide(token))
            spare.revoquer(None)
            self.assertFalse(spare.valide(token))
        self.assertEqual(call("DELETE", "/api/v1/devices", who=V.DEVICE)[1]["error"]["code"], "configurator")


if __name__ == "__main__":
    unittest.main()
