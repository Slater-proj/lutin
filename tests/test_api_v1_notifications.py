"""`/api/v1/notification-channels`: where a finished task sends its message, on the real server of tests/test_api_v1.py. Nothing leaves the machine: the sending is replaced."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import notifications  # noqa: E402

TELEGRAM_TOKEN = "123456:" + "A" * 30


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Channels(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: [notifications.remove(channel["id"]) for channel in notifications.list_channels()])

    def test_a_channel_is_added_listed_tested_and_removed_and_its_secret_is_never_given_back(self):
        status, answer = call("POST", "/api/v1/notification-channels", {"name": "My phone", "type": "telegram", "params": {"chat_id": "42", "jeton": TELEGRAM_TOKEN}})
        self.assertEqual(status, 201)
        self.assertEqual(sorted(answer), ["channels", "types"])
        channel = answer["channels"][0]
        self.assertEqual((channel["name"], channel["type"], channel["params"]), ("My phone", "telegram", {"chat_id": "42"}))
        self.assertEqual(channel["secrets_set"], ["jeton"])
        self.assertNotIn(TELEGRAM_TOKEN, repr(call("GET", "/api/v1/notification-channels")[1]))
        self.assertEqual({kind["id"] for kind in answer["types"]}, {"gotify", "ntfy", "telegram", "webhook"})
        self.assertTrue(all({"key", "label", "required", "secret"} <= set(field) for kind in answer["types"] for field in kind["fields"]))
        sent = []
        with mock.patch.object(notifications, "_post", side_effect=lambda *args, **kwargs: sent.append(args) or True):
            self.assertEqual(call("POST", "/api/v1/notification-channels/%s/test" % channel["id"], {}), (200, {"ok": True}))
        self.assertEqual(len(sent), 1, "the test message goes through the channel")
        status, answer = call("DELETE", "/api/v1/notification-channels/" + channel["id"])
        self.assertEqual((status, answer["channels"]), (200, []))

    def test_a_channel_with_a_wrong_field_is_refused_with_what_to_correct(self):
        status, answer = call("POST", "/api/v1/notification-channels", {"name": "Bad", "type": "ntfy", "params": {"sujet": "no spaces allowed"}})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertTrue(answer["error"]["message"])
        self.assertEqual(call("POST", "/api/v1/notification-channels", {"name": "x"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(notifications.list_channels(), [])

    def test_a_channel_that_is_gone_is_a_404_and_a_service_that_refuses_is_a_400(self):
        self.assertEqual(call("DELETE", "/api/v1/notification-channels/nope")[0], 404)
        self.assertEqual(call("POST", "/api/v1/notification-channels/nope/test", {})[0], 404)
        call("POST", "/api/v1/notification-channels", {"name": "Server", "type": "ntfy", "params": {"sujet": "demo"}})
        identifier = notifications.list_channels()[0]["id"]
        with mock.patch.object(notifications, "_post", side_effect=OSError("down")):
            status, answer = call("POST", "/api/v1/notification-channels/%s/test" % identifier, {})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

    def test_a_paired_device_may_read_but_not_add_remove_or_test(self):
        self.assertEqual(call("GET", "/api/v1/notification-channels", who=V.DEVICE)[0], 200)
        for method, path in (("POST", "/api/v1/notification-channels"), ("DELETE", "/api/v1/notification-channels/abc"), ("POST", "/api/v1/notification-channels/abc/test")):
            self.assertEqual(call(method, path, {}, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


if __name__ == "__main__":
    unittest.main()
