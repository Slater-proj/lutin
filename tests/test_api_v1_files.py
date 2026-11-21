"""Uploads of `/api/v1`: images and documents sent with a message, on the real server of tests/test_api_v1.py and the fake engine of tests/test_moteur.py.

What is fixed here: a body that is a file (not JSON), the limits, the right that lets a browser tag read an image (the session cookie, no page token), and (in tests/test_api_v1_turns.py, which needs the fake engine) a turn that carries
what was uploaded to the model (that part is in tests/test_api_v1_turns.py: it needs the fake engine)."""
import http.client
import json
import unittest
import urllib.parse

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import api_v1  # noqa: E402

PNG = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]) + bytes(24)


def send(path, data, headers=None, method="POST", who=None):
    connection = http.client.HTTPConnection("127.0.0.1", V.PORT, timeout=30)
    sent = {"Host": "127.0.0.1:%d" % V.PORT}
    sent.update(V.OWNER if who is None else who)
    sent.update(headers or {})
    connection.request(method, path, body=data, headers=sent)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    try:
        return response.status, json.loads(body), dict(response.getheaders())
    except ValueError:
        return response.status, body, dict(response.getheaders())


def setUpModule():
    V.setUpModule()


class Images(unittest.TestCase):
    def test_an_image_is_uploaded_and_read_back_by_a_browser_tag(self):
        status, answer, _ = send("/api/v1/images", PNG)
        self.assertEqual((status, sorted(answer)), (201, ["id", "url"]))
        self.assertEqual(answer["url"], "/api/v1/images/" + answer["id"])
        self.assertRegex(answer["id"], r"^[0-9a-f]{20}\.png$")
        same = send("/api/v1/images", PNG)[1]
        self.assertEqual(same["id"], answer["id"], "the same image is kept once")
        status, data, headers = send(answer["url"], None, method="GET")
        self.assertEqual((status, data, headers["Content-Type"]), (200, PNG, "image/png"))
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'; sandbox")

    def test_reading_an_image_needs_a_session_but_not_the_page_token(self):
        identifier = send("/api/v1/images", PNG)[1]["id"]
        path = "/api/v1/images/" + identifier
        cookie = {"Cookie": V.OWNER["Cookie"]}
        connection = http.client.HTTPConnection("127.0.0.1", V.PORT, timeout=20)
        connection.request("GET", path, headers=dict({"Host": "127.0.0.1:%d" % V.PORT}, **cookie))
        self.assertEqual(connection.getresponse().status, 200, "a browser tag sends the cookie and nothing else")
        connection.close()
        self.assertEqual(send(path, None, method="GET", who=V.ELSEWHERE)[0], 401)
        for unknown in ("ffffffffffffffffffff.png", "..%2F..%2Fconfig", "x"):
            status, answer, _ = send("/api/v1/images/" + unknown, None, method="GET")
            self.assertEqual((status, answer["error"]["code"]), (404, "not_found"), unknown)

    def test_an_upload_is_refused_without_a_session_or_the_page_token_and_when_it_is_not_an_image(self):
        self.assertEqual(send("/api/v1/images", PNG, who=V.ELSEWHERE)[0], 401)
        self.assertEqual(send("/api/v1/images", PNG, who={"Cookie": V.OWNER["Cookie"]})[:2], (403, {"error": {"code": "page_token", "message": "Jeton de page invalide : recharge la page."}}))
        for data in (b"", b"just text", b"%PDF-1.4"):
            status, answer, _ = send("/api/v1/images", data)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), data)

    def test_an_upload_over_the_limit_is_read_then_refused_with_413(self):
        for attempt in range(2):
            status, answer, _ = send("/api/v1/images", PNG + b"\x00" * (api_v1._images.MAX_SIZE + 1))
            self.assertEqual((status, answer["error"]["code"]), (413, "too_large"), attempt)

    def test_the_only_routes_without_the_page_token_read_files_and_nothing_else_does(self):
        # The three of this machine (images, documents sent, files a tool produced: tests/test_api_v1_produced.py), and the same three for a conversation
        # held by a paired machine (ADR 0016, stage 7: relayed, read from that machine, with the same sandboxing headers). Any other route that skips the
        # page token fails here.
        entries = [entry for entry in api_v1.table() if entry["right"] == api_v1.READ]
        self.assertEqual([(entry["method"], entry["path"]) for entry in entries], [("GET", "/api/v1/attachments/{id}"), ("GET", "/api/v1/conversations/{id}/files/{file}"),
                                                                                  ("GET", "/api/v1/images/{id}"),
                                                                                  ("GET", "/api/v1/machines/{id}/attachments/{attachment}"),
                                                                                  ("GET", "/api/v1/machines/{id}/conversations/{conversation}/files/{file}"),
                                                                                  ("GET", "/api/v1/machines/{id}/images/{image}")])


class Attachments(unittest.TestCase):
    def upload(self, data, name, who=None):
        return send("/api/v1/attachments", data, {"X-Name": urllib.parse.quote(name)}, who=who)

    def test_a_text_file_is_uploaded_with_its_name_and_its_text_is_counted(self):
        status, answer, _ = self.upload("Marly est une ville.\nLe Tonnerre est un son grave.\n".encode("utf-8"), "résumé notes.txt")
        self.assertEqual((status, sorted(answer)), (201, ["characters", "id", "name"]))
        self.assertEqual((answer["name"], answer["characters"]), ("résumé notes.txt", 50), "the characters of the extracted text, trimmed")

    def test_a_document_is_downloaded_as_it_was_sent_and_never_displayed(self):
        content = "Marly est une ville.\n".encode("utf-8")
        identifier = self.upload(content, "notes été.txt")[1]["id"]
        status, data, headers = send("/api/v1/attachments/" + identifier + "?name=" + urllib.parse.quote("notes été.txt"), None, method="GET")
        self.assertEqual((status, data), (200, content))
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(headers["Content-Disposition"], "attachment; filename*=UTF-8''notes%20%C3%A9t%C3%A9.txt")
        self.assertEqual((headers["Content-Security-Policy"], headers["X-Content-Type-Options"]), ("default-src 'none'; sandbox", "nosniff"))
        self.assertEqual(send("/api/v1/attachments/" + identifier, None, method="GET", who=V.ELSEWHERE)[0], 401)
        for unknown in ("ffffffffffffffffffff.txt", "..%2F..%2Fconfig", "x"):
            status, answer, _ = send("/api/v1/attachments/" + unknown, None, method="GET")
            self.assertEqual((status, answer["error"]["code"]), (404, "not_found"), unknown)

    def test_refusals_carry_a_code(self):
        for data, name in ((b"", "empty.txt"), (b"\x00\x01\x02\xff" * 50, "binary.bin")):
            status, answer, _ = self.upload(data, name)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), name)
        self.assertEqual(self.upload(b"text", "a.txt", V.ELSEWHERE)[0], 401)
        status, answer, _ = send("/api/v1/attachments", b"x" * (api_v1._pieces.MAX_SIZE + 1), {"X-Name": "big.txt"})
        self.assertEqual((status, answer["error"]["code"]), (413, "too_large"))


if __name__ == "__main__":
    unittest.main()
