"""Who may call what (contract test, plan step 2): every route of the inventory is called for real, on a real server at the « network » level.

Two callers, both from another device (a forwarding header says the request does not come from this machine's browser):
  - nobody: no session, no token. Every route must refuse (401 or 403), except the few that exist to obtain an access.
  - a paired device: a valid session and the page token, but no right to configure. Every route the inventory marks as reserved to the configurator
    (tests/fixtures/api_contract.json, `rights`) must answer 403.

The actions that would hurt the machine running the tests (shutdown, update, restart, restore, access level) are replaced by markers: the test also proves
that a refused request never reached them."""
import http.client
import json
import os
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-api-access-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_CONFIG": str(_TEMP / "config.json"),
                   "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9", "LUTIN_HORS_LIGNE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir(exist_ok=True)

from lutin import access, power  # noqa: E402
from lutin import core as A  # noqa: E402
from lutin import security as S  # noqa: E402

CONTRACT = json.loads((Path(__file__).resolve().parent / "fixtures" / "api_contract.json").read_text(encoding="utf-8"))
ELSEWHERE = {"X-Forwarded-For": "203.0.113.7"}          # the request was relayed from another device: never « this machine's browser »
# Routes that exist to obtain an access, or that answer with their own kind of token (another machine's): what « nobody » gets is written here, on purpose.
OPEN_TO_NOBODY = {
    ("POST", "/api/appairer"): (403,),               # the pairing itself: a wrong code is refused
    ("POST", "/api/noeud/appairer"): (400, 403),     # another machine exchanging a code: no code, no token
    ("GET", "/"): (200,),                            # the sign-in page (see test_the_page_itself_is_the_sign_in_page)
    ("GET", "/index.html"): (200,),
    ("GET", "/manifest.webmanifest"): (200,),        # what a phone needs to offer « add to home screen »: a name and icons, nothing of the user's
    ("GET", "/icone.svg"): (200,),
    ("GET", "/logo.svg"): (200,),
}
REACHED = []


def marker(name):
    def reached(*args, **kwargs):
        REACHED.append(name)
        raise ValueError("test marker: " + name)
    return reached


def request(method, path, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    sent = {"Host": "127.0.0.1:%d" % PORT}
    sent.update(ELSEWHERE)
    sent.update(headers or {})
    data = None
    if method in ("POST", "PATCH"):
        data = json.dumps(body or {}).encode("utf-8")
        sent["Content-Type"] = "application/json"
    connection.request(method, path, body=data, headers=sent)
    response = connection.getresponse()
    text = response.read().decode("utf-8", "replace")
    connection.close()
    return response.status, text


def routes(method):
    """Every exact route of the method, and one address under each prefix."""
    entry = CONTRACT[method]
    return sorted(entry["exact"]) + sorted(prefix + "x" for prefix in entry["prefix"] if prefix.startswith("/api/") and prefix != "/api/")


def v1_routes(*rights):
    """Every route of /api/v1 with one of these rights, its parameters filled with « x » (the rights are checked before the parameters)."""
    from lutin import api_v1
    return [(r["method"], re.sub(r"\{[a-z_]+\}", "x", r["path"])) for r in api_v1.table() if r["right"] in rights]


def setUpModule():
    global SERVER, PORT, DEVICE
    patches = [mock.patch.object(A, "SECURITY", S.Security(niveau=S.RESEAU)), mock.patch.object(A, "DEVICES", S.Devices()), mock.patch.object(A, "PIN_LIMITER", S.RateLimiter(10_000, 60)),
               mock.patch.object(power, "schedule_shutdown", marker("shutdown")), mock.patch.object(access, "update", marker("update")),
               mock.patch.object(access, "restart", marker("restart")), mock.patch.object(access, "restore_stream", marker("restore")), mock.patch.object(access, "apply", marker("access level"))]
    for patch in patches:
        patch.start()
        unittest.addModuleCleanup(patch.stop)
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()
    unittest.addModuleCleanup(SERVER.shutdown)
    PORT = SERVER.server_address[1]
    session = A.DEVICES.appairer(A.DEVICES.nouveau_pin(), "phone")
    DEVICE = {"Cookie": "{}={}".format(S.NAME_COOKIE, session), "X-Token": A.TOKEN}


class Nobody(unittest.TestCase):
    def test_every_route_refuses_a_caller_without_a_session(self):
        REACHED.clear()
        wrong = []
        for method in ("GET", "POST"):
            for path in routes(method):
                status, _ = request(method, path)
                allowed = OPEN_TO_NOBODY.get((method, path), (401, 403))
                if status not in allowed:
                    wrong.append((method, path, status))
        self.assertEqual(wrong, [], "routes that answered a caller with no session (expected 401 or 403)")
        self.assertEqual(REACHED, [], "a refused request reached an action")

    def test_a_session_without_the_page_token_reads_nothing(self):
        """The session cookie alone is what another site could make the browser send: the page token is required on top of it."""
        wrong = []
        for path in routes("GET"):
            if ("GET", path) in OPEN_TO_NOBODY:
                continue
            status, _ = request("GET", path, {"Cookie": DEVICE["Cookie"]})
            if status not in (401, 403):
                wrong.append((path, status))
        self.assertEqual(wrong, [])

    def test_the_page_itself_is_the_sign_in_page(self):
        status, page = request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(A.TOKEN, page, "the page token is only in the page given to a signed-in device")
        self.assertIn(A.TOKEN, request("GET", "/", {"Cookie": DEVICE["Cookie"]})[1])


class NobodyOnV1(unittest.TestCase):
    def test_every_route_of_v1_refuses_a_caller_without_a_session(self):
        REACHED.clear()
        wrong = [(method, path, status) for method, path in v1_routes("session", "configurator", "local", "read") for status in [request(method, path)[0]] if status != 401]
        self.assertEqual(wrong, [], "routes of /api/v1 that answered a caller with no session (expected 401)")
        self.assertEqual(REACHED, [], "a refused request reached an action")


class PairedDevice(unittest.TestCase):
    def test_the_device_is_signed_in_but_cannot_configure(self):
        status, text = request("GET", "/api/v1/status", DEVICE)
        self.assertEqual(status, 200, text[:200])
        self.assertFalse(json.loads(text)["access"]["can_configure"])

    def test_every_route_reserved_to_the_configurator_refuses_a_paired_device(self):
        REACHED.clear()
        called, wrong = 0, []
        for method, path in v1_routes("configurator", "local"):
            status, text = request(method, path, DEVICE)
            called += 1
            if status != 403:
                wrong.append((method, path, status, text[:120]))
        self.assertEqual(wrong, [], "routes reserved to the configurator that answered a paired device")
        self.assertGreater(called, 100, "the table lists the reserved routes")
        self.assertEqual(REACHED, [], "a refused request reached an action")

    def test_the_guarded_actions_are_among_the_reserved_routes(self):
        """The markers only prove something if the dangerous routes are in the list that is called."""
        reserved = set(v1_routes("configurator", "local"))
        for route in (("PATCH", "/api/v1/access"), ("POST", "/api/v1/lutin/update"), ("POST", "/api/v1/lutin/restart"), ("PATCH", "/api/v1/access/remote-admin"),
                      ("POST", "/api/v1/mcp-connectors"), ("POST", "/api/v1/projects"), ("POST", "/api/v1/backup/restore")):
            self.assertIn(route, reserved, route)


if __name__ == "__main__":
    unittest.main()
