"""`/api/v1/addons/{id}/panel`: the live panel of the add-ons (Telegram, mail, X) on the real server of tests/test_api_v1.py. Nothing is sent: the calls out are replaced."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import addons, addons_mail, addons_telegram, addons_x  # noqa: E402


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Panels(unittest.TestCase):
    def setUp(self):
        for module in (addons_telegram, addons_mail, addons_x):
            self.addCleanup(module.write, module.read())

    def test_telegram_shows_its_code_its_phones_and_its_drafts_and_acts_on_them(self):
        state = addons_telegram.read()
        state.update(code="123456", autorises=[{"id": 42, "nom": "Phone"}],
                     brouillons=[{"id": "d1", "chat_id": 7, "de": "Ann", "demande": "Are you there?", "texte": "Yes.", "date": 1700000000},
                                 {"id": "d2", "chat_id": 7, "de": "Ann", "demande": "And now?", "texte": "Still.", "date": 1700000100}])
        addons_telegram.write(state)
        status, answer = call("GET", "/api/v1/addons/telegram/panel")
        self.assertEqual(status, 200)
        panel = answer["panel"]
        self.assertEqual((panel["pairing_code"], panel["devices"], panel["listening"]), ("123456", [{"id": "42", "name": "Phone"}], False))
        self.assertEqual(panel["drafts"][0], {"id": "d1", "device": 7, "from": "Ann", "request": "Are you there?", "text": "Yes.", "at": 1700000000})
        with mock.patch.object(addons_telegram, "send", return_value=(True, "")) as sent:
            answer = call("POST", "/api/v1/addons/telegram/panel/send_draft", {"draft": "d1", "text": "Yes, I am."})[1]
        sent.assert_called_once_with(7, "Yes, I am.")
        self.assertEqual([draft["id"] for draft in answer["panel"]["drafts"]], ["d2"])
        answer = call("POST", "/api/v1/addons/telegram/panel/discard_draft", {"draft": "d2"})[1]
        self.assertEqual(answer["panel"]["drafts"], [])
        answer = call("POST", "/api/v1/addons/telegram/panel/forget_device", {"device": "42"})[1]
        self.assertEqual(answer["panel"]["devices"], [])
        self.assertNotEqual(answer["panel"]["pairing_code"], "123456", "forgetting a phone changes the code")
        before = answer["panel"]["pairing_code"]
        self.assertNotEqual(call("POST", "/api/v1/addons/telegram/panel/new_pairing_code", {})[1]["panel"]["pairing_code"], before)

    def test_a_refused_action_says_why(self):
        status, answer = call("POST", "/api/v1/addons/telegram/panel/send_draft", {"draft": "nope"})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))
        self.assertTrue(answer["error"]["message"])
        self.assertEqual(call("POST", "/api/v1/addons/telegram/panel/send_draft", {"colour": 1})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/api/v1/addons/telegram/panel/no_such_action", {})[0], 404)
        self.assertEqual(call("POST", "/api/v1/addons/nope/panel/send_draft", {})[0], 404)
        self.assertEqual(call("GET", "/api/v1/addons/nope/panel")[0], 404)

    def test_mail_drafts_are_sent_with_the_text_given_or_dropped(self):
        state = addons_mail.read()
        state["brouillons"] = [{"id": "m1", "de": "Bob", "adresse": "bob@example.org", "sujet": "Hello", "extrait": "Hi", "texte": "Hi back", "message_id": "<1@x>", "references": "", "date": 1700000000},
                               {"id": "m2", "de": "Bob", "adresse": "bob@example.org", "sujet": "Again", "extrait": "Hi", "texte": "Hello", "message_id": "<2@x>", "references": "", "date": 1700000100}]
        addons_mail.write(state)
        panel = call("GET", "/api/v1/addons/mail/panel")[1]["panel"]
        self.assertEqual((panel["drafts"][0]["subject"], panel["drafts"][0]["address"]), ("Hello", "bob@example.org"))
        with mock.patch.object(addons_mail, "send") as sent:
            answer = call("POST", "/api/v1/addons/mail/panel/send_draft", {"draft": "m1", "text": "Edited."})[1]
        self.assertEqual(sent.call_args[0][1], "Edited.")
        self.assertEqual([draft["id"] for draft in answer["panel"]["drafts"]], ["m2"])
        self.assertEqual(call("POST", "/api/v1/addons/mail/panel/discard_draft", {"draft": "m2"})[1]["panel"]["drafts"], [])

    def test_x_posts_are_written_edited_scheduled_published_and_deleted(self):
        with mock.patch.object(addons_x, "drafting", return_value="A first post."):
            answer = call("POST", "/api/v1/addons/x/panel/write_posts", {"brief": "Say hello", "count": 1})[1]
        post = answer["panel"]["posts"][0]
        self.assertEqual((post["text"], post["state"]), ("A first post.", "draft"))
        path = "/api/v1/addons/x/panel/"
        self.assertEqual(call("POST", path + "edit_post", {"post": post["id"], "text": "A better post."})[1]["panel"]["posts"][0]["text"], "A better post.")
        answer = call("POST", path + "schedule_post", {"post": post["id"], "at": 4102444800})[1]
        self.assertEqual((answer["panel"]["posts"][0]["state"], answer["panel"]["posts"][0]["scheduled_for"]), ("scheduled", 4102444800))
        with mock.patch.object(addons_x, "publish", return_value="tweet-1") as published:
            answer = call("POST", path + "publish_post", {"post": post["id"]})[1]
        published.assert_called_once_with("A better post.")
        self.assertEqual((answer["panel"]["posts"][0]["state"], answer["panel"]["posts"][0]["detail"]), ("published", "tweet-1"))
        self.assertEqual(call("POST", path + "delete_post", {"post": post["id"]})[1]["panel"]["posts"], [])
        self.assertEqual(call("POST", path + "write_posts", {"brief": " "})[0], 400)

    def test_an_addon_without_a_panel_here_says_so_and_a_paired_device_is_refused(self):
        self.assertEqual(call("GET", "/api/v1/addons/comfyui/panel")[1], {"panel": None})
        self.assertEqual(call("GET", "/api/v1/addons/telegram/panel", who=V.DEVICE)[1]["error"]["code"], "configurator", "the pairing code is the key to the add-on")
        self.assertEqual(call("POST", "/api/v1/addons/telegram/panel/new_pairing_code", {}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertIn("comfyui", addons.ids())


if __name__ == "__main__":
    unittest.main()
