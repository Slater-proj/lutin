"""`/api/v1/addons`: the shipped add-ons, on the real server of tests/test_api_v1.py. Nothing leaves the machine: an add-on that lacks a setting is not even contacted."""
import unittest

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import addons  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


def with_a_secret():
    """The first shipped add-on that asks for a secret, and the key of that secret."""
    for identifier in addons.ids():
        for field in addons.manifest(identifier)["reglages"]:
            if field.get("secret"):
                return identifier, field["cle"]
    raise AssertionError("no shipped add-on asks for a secret")


class Addons(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: (addons.secrets_write({}), addons.write_state({})))

    def test_every_shipped_addon_is_described_in_english_keys_and_none_is_active(self):
        status, answer = call("GET", "/api/v1/addons")
        self.assertEqual(status, 200)
        self.assertEqual([entry["id"] for entry in answer["addons"]], addons.ids())
        for entry in answer["addons"]:
            self.assertEqual(sorted(entry), ["active", "check", "description", "doc", "hosts", "id", "missing", "name", "settings", "state", "steps", "stream_modified"])
            self.assertFalse(entry["active"], "an add-on is off until it has been set up and checked")
            self.assertTrue(all({"key", "secret", "label", "multiline"} <= set(field) for field in entry["settings"]))
        self.assertEqual(answer["alerts"], [])

    def test_a_secret_is_kept_and_never_given_back_and_an_unknown_setting_is_refused(self):
        identifier, key = with_a_secret()
        status, answer = call("PATCH", "/api/v1/addons/" + identifier, {"settings": {key: "zzz-secret-value"}})
        self.assertEqual(status, 200)
        self.assertNotIn("zzz-secret-value", repr(answer))
        self.assertNotIn("zzz-secret-value", repr(call("GET", "/api/v1/addons")[1]))
        field = next(item for entry in answer["addons"] if entry["id"] == identifier for item in entry["settings"] if item["key"] == key)
        self.assertEqual((field["set"], "value" in field), (True, False))
        self.assertEqual(addons.settings(identifier)[key], "zzz-secret-value", "the add-on itself has it")
        call("PATCH", "/api/v1/addons/" + identifier, {"settings": {key: ""}})
        self.assertEqual(addons.settings(identifier)[key], "zzz-secret-value", "an empty secret keeps the old one")
        status, answer = call("PATCH", "/api/v1/addons/" + identifier, {"settings": {"no_such_key": "x"}})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

    def test_an_addon_that_is_not_set_up_is_not_started_and_the_check_says_what_is_missing(self):
        identifier, _key = with_a_secret()
        status, answer = call("POST", "/api/v1/addons/%s/check" % identifier, {})
        self.assertEqual(status, 200)
        self.assertFalse(answer["ok"])
        self.assertTrue(answer["steps"][0]["message"])
        status, answer = call("PATCH", "/api/v1/addons/" + identifier, {"active": True})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertTrue(answer["error"]["message"])
        self.assertFalse(next(entry for entry in call("GET", "/api/v1/addons")[1]["addons"] if entry["id"] == identifier)["active"])

    def test_refused_requests_say_why(self):
        self.assertEqual(call("PATCH", "/api/v1/addons/nope", {"active": False})[0], 404)
        self.assertEqual(call("POST", "/api/v1/addons/nope/check", {})[0], 404)
        identifier = addons.ids()[0]
        for body in ({}, {"active": "yes"}, {"settings": "x"}, {"colour": 1}):
            self.assertEqual(call("PATCH", "/api/v1/addons/" + identifier, body)[1]["error"]["code"], "invalid_request", body)

    def test_a_paired_device_may_read_but_not_set_up_start_or_check_an_addon(self):
        self.assertEqual(call("GET", "/api/v1/addons", who=V.DEVICE)[0], 200)
        for method, path in (("PATCH", "/api/v1/addons/abc"), ("POST", "/api/v1/addons/abc/check")):
            self.assertEqual(call(method, path, {}, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


if __name__ == "__main__":
    unittest.main()
