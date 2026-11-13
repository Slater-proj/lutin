"""`/api/v1` (lutin.api_v1): the contract of the versioned English API, checked on a real server at the « network » level.

What is fixed here: the table of routes and the right each one declares (tests/fixtures/api_v1_routes.json), the shape of every answer field by field,
the shape of every error ({"error": {"code", "message"}}), and the refusals. A field renamed or a right loosened fails a test."""
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-api-v1-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_CONFIG": str(_TEMP / "config.json"),
                   "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9", "LUTIN_HORS_LIGNE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir(exist_ok=True)

from lutin import api_v1  # noqa: E402
from lutin import core as A  # noqa: E402
from lutin import security as S  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "api_v1_routes.json"
ELSEWHERE = {"X-Forwarded-For": "203.0.113.7"}          # relayed from another device: never « this machine's browser »


def call(method, path, headers=None, body=None, raw=None):
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    sent = {"Host": "127.0.0.1:%d" % PORT}
    sent.update(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if data is not None:
        sent["Content-Type"] = "application/json"
    connection.request(method, path, body=data, headers=sent)
    response = connection.getresponse()
    text = response.read().decode("utf-8", "replace")
    connection.close()
    try:
        return response.status, json.loads(text)
    except ValueError:
        return response.status, text


def setUpModule():
    global SERVER, PORT, OWNER, DEVICE
    for patch in (mock.patch.object(A, "SECURITE", S.Securite(niveau=S.RESEAU)), mock.patch.object(A, "APPAREILS", S.Appareils()), mock.patch.object(A, "LIMITEUR_PIN", S.LimiteurDebit(10_000, 60))):
        patch.start()
        unittest.addModuleCleanup(patch.stop)
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()
    unittest.addModuleCleanup(SERVER.shutdown)
    PORT = SERVER.server_address[1]
    session = {"Cookie": "{}={}".format(S.NOM_COOKIE, A.APPAREILS.appairer(A.APPAREILS.nouveau_pin(), "browser")), "X-Token": A.JETON}
    OWNER = dict(session)                              # the browser of this machine: may configure
    DEVICE = dict(session, **ELSEWHERE)                # a paired phone: a session, no right to configure


def sample(template):
    return template.replace("{id}", "0123abcd")


class Table(unittest.TestCase):
    def test_the_route_table_is_the_recorded_contract(self):
        recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(api_v1.table(), recorded, "the v1 contract changed. Intended? Update tests/fixtures/api_v1_routes.json in the same commit.")

    def test_every_route_declares_a_known_right_and_an_english_path(self):
        for entry in api_v1.table():
            self.assertIn(entry["right"], api_v1.RIGHTS)
            self.assertRegex(entry["path"], r"^/api/v1(/[a-z][a-z0-9-]*|/\{[a-z_]+\})+$", "kebab-case segments and {parameters}")

    def test_no_route_is_declared_twice(self):
        keys = [(entry["method"], entry["path"]) for entry in api_v1.table()]
        self.assertEqual(len(keys), len(set(keys)))


class Rights(unittest.TestCase):
    """Checked by the dispatcher from the table, for every route, with empty requests: nothing is executed by a refused call."""

    def test_without_a_session_every_route_answers_401_with_a_code(self):
        for entry in api_v1.table():
            if entry["right"] == api_v1.PUBLIC:
                continue
            status, answer = call(entry["method"], sample(entry["path"]), ELSEWHERE, body={} if entry["method"] in api_v1.WITH_BODY else None)
            self.assertEqual((status, answer["error"]["code"]), (401, "no_session"), entry)

    def test_a_session_without_the_page_token_answers_403(self):
        for entry in api_v1.table():
            if entry["right"] == api_v1.PUBLIC:
                continue
            status, answer = call(entry["method"], sample(entry["path"]), {"Cookie": DEVICE["Cookie"]}, body={} if entry["method"] in api_v1.WITH_BODY else None)
            self.assertEqual((status, answer["error"]["code"]), (403, "page_token"), entry)

    def test_routes_reserved_to_the_configurator_refuse_a_paired_device(self):
        for entry in api_v1.table():
            if entry["right"] in (api_v1.CONFIGURATOR, api_v1.LOCAL):
                status, answer = call(entry["method"], sample(entry["path"]), DEVICE, body={} if entry["method"] in api_v1.WITH_BODY else None)
                self.assertEqual(status, 403, entry)
                self.assertIn(answer["error"]["code"], ("configurator", "local_only"), entry)

    def test_an_unknown_address_tells_nothing_without_a_session(self):
        self.assertEqual(call("GET", "/api/v1/nothing-here", ELSEWHERE)[0], 401)
        self.assertEqual(call("GET", "/api/v1/nothing-here", DEVICE), (404, {"error": {"code": "not_found", "message": "Route inconnue."}}))

    def test_a_write_from_another_site_is_refused_before_anything(self):
        status, _ = call("POST", "/api/v1/conversations", dict(OWNER, Origin="https://evil.example"), body={})
        self.assertEqual(status, 403)
        status, _ = call("DELETE", "/api/v1/conversations/0123abcd", dict(OWNER, Origin="https://evil.example"))
        self.assertEqual(status, 403)

    def test_patch_and_delete_exist_only_under_v1(self):
        self.assertEqual(call("DELETE", "/api/supprimer", OWNER)[0], 404)
        self.assertEqual(call("PATCH", "/api/reglages", OWNER, body={})[0], 404)


class Errors(unittest.TestCase):
    def test_wrong_method_unreadable_body_and_oversize(self):
        self.assertEqual(call("DELETE", "/api/v1/status", OWNER)[1]["error"]["code"], "method_not_allowed")
        self.assertEqual(call("DELETE", "/api/v1/status", OWNER)[0], 405)
        for raw in (b"{not json", b"[1, 2]", b'"text"'):
            self.assertEqual(call("POST", "/api/v1/conversations", OWNER, raw=raw), (400, {"error": {"code": "invalid_json", "message": "Le corps de la requête doit être un objet JSON."}}), raw)
        status, answer = call("POST", "/api/v1/conversations", OWNER, raw=b'{"x": "' + b"a" * (api_v1.BODY_MAX + 10) + b'"}')
        self.assertEqual((status, answer["error"]["code"]), (413, "too_large"))

    def test_a_body_that_is_not_used_is_read_before_the_answer(self):
        """An answer sent with the body unread resets the caller's connection and the answer is lost (WinError 10053 on Windows, most of the time)."""
        big = b"a" * (api_v1.BODY_MAX + 10)
        for attempt in range(3):
            status, answer = call("POST", "/api/v1/conversations", OWNER, raw=big)
            self.assertEqual((status, answer["error"]["code"]), (413, "too_large"), attempt)
            status, answer = call("DELETE", "/api/v1/status", OWNER, raw=big)
            self.assertEqual((status, answer["error"]["code"]), (405, "method_not_allowed"), attempt)

    def test_a_refused_body_has_been_read_to_its_end(self):
        """The same rule without a socket: the test above depends on timing (the reset does not happen every time), this one does not."""
        class Caller:
            close_connection = False

            def __init__(self, announced, sent):
                self.announced, self.rfile = announced, io.BytesIO(b"a" * sent)

            def _taille_corps(self):
                return self.announced

        caller = Caller(api_v1.BODY_MAX + 10, api_v1.BODY_MAX + 10)
        with self.assertRaises(api_v1.ApiError) as refused:
            api_v1._read_body(caller)
        self.assertEqual((refused.exception.status, caller.rfile.read(), caller.close_connection), (413, b"", False))
        caller = Caller(100, 100)
        api_v1._discard_body(caller)
        self.assertEqual(caller.rfile.read(), b"", "a body sent with a method that takes none")
        caller = Caller(api_v1.DISCARD_MAX + 1, 100)
        with self.assertRaises(api_v1.ApiError):
            api_v1._read_body(caller)
        self.assertEqual((caller.rfile.tell(), caller.close_connection), (0, True), "beyond the bound nothing is read, and the connection is closed")

    def test_a_length_that_is_not_a_number_is_refused_without_waiting_for_a_body(self):
        status, answer = call("POST", "/api/v1/conversations", dict(OWNER, **{"Content-Length": "abc"}))
        self.assertEqual((status, answer["error"]["code"]), (413, "too_large"))
        status, answer = call("POST", "/api/v1/conversations", dict(OWNER, **{"Content-Length": "-5"}))
        self.assertEqual((status, answer["error"]["code"]), (413, "too_large"))

    def test_messages_follow_the_language_and_codes_do_not(self):
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            self.assertEqual(call("GET", "/api/v1/status", ELSEWHERE), (401, {"error": {"code": "no_session", "message": "Sign-in required."}}))
            self.assertEqual(call("GET", "/api/v1/conversations/ffffffff", OWNER), (404, {"error": {"code": "not_found", "message": "Unknown conversation."}}))
        self.assertEqual(call("GET", "/api/v1/conversations/ffffffff", OWNER), (404, {"error": {"code": "not_found", "message": "Conversation inconnue."}}))

    def test_an_identifier_cannot_leave_the_conversations_folder(self):
        for identifier in ("..%2F..%2Fconfig", "%2e%2e", "0123abcd.json", "A" * 8):
            status, answer = call("GET", "/api/v1/conversations/" + identifier, OWNER)
            self.assertEqual((status, answer["error"]["code"]), (404, "not_found"), identifier)


class Status(unittest.TestCase):
    def test_the_shape_of_the_status(self):
        status, answer = call("GET", "/api/v1/status", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(sorted(answer), ["access", "active_turns", "engine", "installed_models", "language", "model", "offline", "pending_approvals", "version", "workspace"])
        self.assertEqual(answer["access"], {"level": "network", "can_configure": True})
        self.assertEqual(sorted(answer["engine"]), ["id", "name", "running"])
        self.assertEqual((answer["engine"]["id"], answer["engine"]["running"]), ("ollama", False), "no engine answers in this test")
        self.assertEqual((answer["language"], answer["offline"], answer["version"]), ("fr", True, A.VERSION))
        self.assertEqual(answer["workspace"], {"path": str(A.RACINE)})
        self.assertEqual((answer["active_turns"], answer["pending_approvals"], answer["installed_models"]), ([], [], []))
        self.assertIsInstance(answer["model"], str)

    def test_a_paired_device_reads_the_status_and_learns_it_cannot_configure(self):
        status, answer = call("GET", "/api/v1/status", DEVICE)
        self.assertEqual((status, answer["access"]), (200, {"level": "network", "can_configure": False}))


class Conversations(unittest.TestCase):
    def test_life_of_a_conversation(self):
        status, created = call("POST", "/api/v1/conversations", OWNER, body={})
        self.assertEqual(status, 201)
        self.assertEqual(sorted(created), ["created_at", "id", "messages", "pinned", "summary", "title", "updated_at"])
        self.assertEqual((created["messages"], created["pinned"], created["summary"]), ([], False, ""))
        identifier = created["id"]
        self.addCleanup(lambda: call("DELETE", "/api/v1/conversations/" + identifier, OWNER))

        status, listed = call("GET", "/api/v1/conversations", OWNER)
        self.assertEqual(status, 200)
        entry = next(c for c in listed["conversations"] if c["id"] == identifier)
        self.assertEqual(sorted(entry), ["id", "message_count", "origin_machine", "pinned", "title", "updated_at"])
        self.assertEqual((entry["message_count"], entry["pinned"]), (0, False))

        status, updated = call("PATCH", "/api/v1/conversations/" + identifier, OWNER, body={"title": "  Budget 2027  ", "pinned": True})
        self.assertEqual((status, updated["title"], updated["pinned"]), (200, "Budget 2027", True))
        self.assertEqual(call("GET", "/api/v1/conversations/" + identifier, OWNER)[1]["title"], "Budget 2027")
        self.assertEqual(A.conv_lire(identifier)["titre"], "Budget 2027", "the same state as the French routes")

        for wrong in ({}, {"title": ""}, {"title": 3}, {"pinned": "yes"}, {"titre": "x"}, {"title": "x", "other": 1}):
            status, answer = call("PATCH", "/api/v1/conversations/" + identifier, OWNER, body=wrong)
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), wrong)

        self.assertEqual(call("POST", "/api/v1/conversations/" + identifier + "/stop", OWNER, body={}), (200, {"was_running": False}))
        self.assertEqual(call("DELETE", "/api/v1/conversations/" + identifier, OWNER), (200, {"deleted": True}))
        self.assertEqual(call("GET", "/api/v1/conversations/" + identifier, OWNER)[0], 404)
        self.assertEqual(call("DELETE", "/api/v1/conversations/" + identifier, OWNER)[0], 404)

    def test_a_conversation_that_is_answering_cannot_be_renamed_or_deleted(self):
        identifier = call("POST", "/api/v1/conversations", OWNER, body={})[1]["id"]
        stop = threading.Event()
        A.TOURS_ACTIFS[identifier] = stop
        try:
            for method, body in (("PATCH", {"title": "x"}), ("DELETE", None)):
                status, answer = call(method, "/api/v1/conversations/" + identifier, OWNER, body=body)
                self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"), method)
            self.assertIn(identifier, call("GET", "/api/v1/status", OWNER)[1]["active_turns"])
            self.assertEqual(call("POST", "/api/v1/conversations/" + identifier + "/stop", OWNER, body={}), (200, {"was_running": True}))
            self.assertTrue(stop.is_set(), "the running turn was told to stop")
        finally:
            A.TOURS_ACTIFS.pop(identifier, None)
        self.assertEqual(call("DELETE", "/api/v1/conversations/" + identifier, OWNER)[0], 200)

    def test_a_paired_device_may_use_its_conversations(self):
        status, created = call("POST", "/api/v1/conversations", DEVICE, body={})
        self.assertEqual(status, 201)
        self.assertEqual(call("DELETE", "/api/v1/conversations/" + created["id"], DEVICE)[0], 200)


class Approvals(unittest.TestCase):
    def test_an_approval_is_answered_once(self):
        pending = A.Attente("Run a command", "git push", conv="c0ffee00")
        self.addCleanup(lambda: A.Attente.EN_COURS.pop(pending.id, None))
        self.assertIn("c0ffee00", call("GET", "/api/v1/status", OWNER)[1]["pending_approvals"])
        for wrong in ({}, {"approved": "yes"}, {"ok": True}):
            self.assertEqual(call("POST", "/api/v1/approvals/" + pending.id, OWNER, body=wrong)[0], 400, wrong)
        self.assertFalse(pending.evenement.is_set())
        self.assertEqual(call("POST", "/api/v1/approvals/" + pending.id, OWNER, body={"approved": True, "restore_auto_approval": True}), (200, {"approved": True}))
        self.assertTrue(pending.evenement.is_set() and pending.ok and pending.reactiver)
        status, answer = call("POST", "/api/v1/approvals/unknown", OWNER, body={"approved": False})
        self.assertEqual((status, answer["error"]["code"]), (404, "not_found"))


if __name__ == "__main__":
    unittest.main()
