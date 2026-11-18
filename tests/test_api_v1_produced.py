"""What a tool produced in a conversation, in `/api/v1`: the files it created and the images it generated, on the real server of tests/test_api_v1.py.

What is fixed here: a produced file is downloaded with the session cookie alone (a link), never displayed; opening it and deleting it, or a generated
image, act on this machine's disk and need `configurator`, as on the old page; nothing is deleted while an answer runs; a file outside the allowed
folders is never read nor deleted. The system's « open » is replaced: no application is launched by these tests."""
import http.client
import json
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1, images, produced_files  # noqa: E402

A = V.A
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def send(method, path, who, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", V.PORT, timeout=20)
    headers = dict({"Host": "127.0.0.1:%d" % V.PORT}, **who)
    data = None if body is None else json.dumps(body).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    try:
        return response.status, json.loads(raw), dict(response.getheaders())
    except ValueError:
        return response.status, raw, dict(response.getheaders())


def setUpModule():
    V.setUpModule()


class Produced(unittest.TestCase):
    def setUp(self):
        self.conversation = A.conv_nouvelle()["id"]
        self.addCleanup(lambda: A.conv_supprimer(self.conversation))
        self.report = A.RACINE / "rapport été.pdf"
        self.report.write_bytes(b"%PDF-1.4 the report")
        self.addCleanup(lambda: self.report.unlink(missing_ok=True))
        self.image = images.save(PNG)
        self.entry = produced_files.entree(self.report)
        stored = A.conv_lire(self.conversation)
        stored["messages"] += [{"role": "user", "content": "Make a report and a picture"},
                               {"role": "tool", "tool_name": "generer_image", "content": "Done.", "medias": [self.image], "medias_fichiers": {self.image: ""},
                                "fichiers_joints": [self.entry]}]
        A.conv_ecrire_telle_quelle(stored)
        self.base = "/api/v1/conversations/" + self.conversation

    def tool_message(self):
        return [m for m in A.conv_lire(self.conversation)["messages"] if m["role"] == "tool"][0]

    def test_a_produced_file_is_downloaded_with_the_session_cookie_alone_and_never_displayed(self):
        path = "{}/files/{}".format(self.base, self.entry["id"])
        status, data, headers = send("GET", path, {"Cookie": V.OWNER["Cookie"]})
        self.assertEqual((status, data), (200, b"%PDF-1.4 the report"), "a link sends the cookie and nothing else")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(headers["Content-Disposition"], "attachment; filename*=UTF-8''rapport%20%C3%A9t%C3%A9.pdf")
        self.assertEqual((headers["Content-Security-Policy"], headers["X-Content-Type-Options"]), ("default-src 'none'; sandbox", "nosniff"))
        self.assertEqual(send("GET", path, V.ELSEWHERE)[0], 401)
        for unknown in ("ffffffffffff", "..%2F..%2Fconfig"):
            status, answer, _ = send("GET", "{}/files/{}".format(self.base, unknown), V.OWNER)
            self.assertEqual((status, answer["error"]["code"]), (404, "not_found"), unknown)
        self.assertEqual(send("GET", "/api/v1/conversations/0123abcd/files/" + self.entry["id"], V.OWNER)[0], 404, "an unknown conversation")
        self.report.unlink()
        status, answer, _ = send("GET", path, V.OWNER)
        self.assertEqual((status, answer["error"]["code"]), (404, "not_found"), "the file is gone from the disk")

    def test_a_file_outside_the_allowed_folders_is_not_read(self):
        stored = A.conv_lire(self.conversation)
        outside = dict(self.entry, id="0000aaaa1111", chemin=str(V._TEMP / "config.json"))
        stored["messages"][-1]["fichiers_joints"].append(outside)
        A.conv_ecrire_telle_quelle(stored)
        status, answer, _ = send("GET", "{}/files/{}".format(self.base, outside["id"]), V.OWNER)
        self.assertEqual((status, answer["error"]["code"]), (404, "not_found"))

    def test_a_produced_file_is_opened_by_this_machine_only(self):
        path = "{}/files/{}/open".format(self.base, self.entry["id"])
        launched = []
        with mock.patch.object(produced_files, "_launch", launched.append), mock.patch.object(produced_files, "opening_possible", lambda: True):
            self.assertEqual(send("POST", path, V.DEVICE, {})[0], 403, "a paired phone opens nothing on this machine")
            self.assertEqual(send("POST", path, V.OWNER, {})[:2], (200, {"opened": True}))
            self.assertEqual(launched, [self.report.resolve()])
            script = A.RACINE / "outil.py"
            script.write_text("print(1)", encoding="utf-8")
            self.addCleanup(script.unlink)
            stored = A.conv_lire(self.conversation)
            stored["messages"][-1]["fichiers_joints"].append(produced_files.entree(script))
            A.conv_ecrire_telle_quelle(stored)
            status, answer, _ = send("POST", "{}/files/{}/open".format(self.base, produced_files.identifier(script)), V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "cannot_open"), "only documents and media are opened")
            self.assertEqual(len(launched), 1)
        with mock.patch.object(produced_files, "_launch", launched.append), mock.patch.object(produced_files, "opening_possible", lambda: False):
            status, answer, _ = send("POST", path, V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "cannot_open"), "a machine without a screen")
        self.assertEqual(len(launched), 1)

    def test_a_produced_file_is_deleted_from_the_conversation_and_the_disk(self):
        path = "{}/files/{}".format(self.base, self.entry["id"])
        self.assertEqual(send("DELETE", path, V.DEVICE)[0], 403)
        with mock.patch.dict(A.TOURS_ACTIFS, {self.conversation: object()}):
            status, answer, _ = send("DELETE", path, V.OWNER)
        self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))
        self.assertTrue(self.report.is_file(), "nothing is deleted while an answer runs")
        self.assertEqual(send("DELETE", path, V.OWNER)[:2], (200, {"deleted": True, "file_deleted": True}))
        self.assertFalse(self.report.exists())
        self.assertNotIn("fichiers_joints", self.tool_message())
        self.assertEqual(self.tool_message()["medias"], [self.image], "the image stays")
        self.assertEqual(send("DELETE", path, V.OWNER)[0], 404)

    def test_a_generated_image_is_deleted_from_the_conversation_and_its_copy(self):
        path = "{}/media/{}".format(self.base, self.image)
        status, data, _ = send("GET", "/api/v1/images/" + self.image, V.OWNER)
        self.assertEqual((status, data), (200, PNG), "a generated image is read as the images sent")
        self.assertEqual(send("DELETE", path, V.DEVICE)[0], 403)
        self.assertEqual(send("DELETE", path, V.OWNER)[:2], (200, {"deleted": True, "file_deleted": False}), "no ComfyUI folder: only the copy kept by Lutin")
        self.assertNotIn("medias", self.tool_message())
        self.assertEqual([entry["id"] for entry in self.tool_message()["fichiers_joints"]], [self.entry["id"]], "the file stays")
        self.assertRaises(ValueError, images.path_of, self.image)          # the copy is gone
        self.assertEqual(send("DELETE", path, V.OWNER)[0], 404)
        self.assertEqual(send("DELETE", self.base + "/media/..%2Fx", V.OWNER)[0], 404)

    def test_the_status_says_whether_this_page_may_open_a_file(self):
        with mock.patch.object(produced_files, "opening_possible", lambda: True):
            self.assertTrue(send("GET", "/api/v1/status", V.OWNER)[1]["can_open_files"])
            self.assertFalse(send("GET", "/api/v1/status", V.DEVICE)[1]["can_open_files"], "a phone cannot ask this machine to open a file")
        with mock.patch.object(produced_files, "opening_possible", lambda: False):
            self.assertFalse(send("GET", "/api/v1/status", V.OWNER)[1]["can_open_files"])

    def test_the_routes_are_declared_with_their_rights(self):
        table = {(entry["method"], entry["path"]): entry["right"] for entry in api_v1.table()}
        self.assertEqual(table[("GET", "/api/v1/conversations/{id}/files/{file}")], api_v1.READ)
        for key in (("POST", "/api/v1/conversations/{id}/files/{file}/open"), ("DELETE", "/api/v1/conversations/{id}/files/{file}"),
                    ("DELETE", "/api/v1/conversations/{id}/media/{image}")):
            self.assertEqual(table[key], api_v1.CONFIGURATOR, key)


if __name__ == "__main__":
    unittest.main()
