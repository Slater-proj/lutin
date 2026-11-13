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
    if method == "POST":
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


def setUpModule():
    global SERVER, PORT, DEVICE
    patches = [mock.patch.object(A, "SECURITE", S.Securite(niveau=S.RESEAU)), mock.patch.object(A, "APPAREILS", S.Appareils()), mock.patch.object(A, "LIMITEUR_PIN", S.LimiteurDebit(10_000, 60)),
               mock.patch.object(power, "programmer_extinction", marker("shutdown")), mock.patch.object(access, "mettre_a_jour", marker("update")),
               mock.patch.object(access, "redemarrer", marker("restart")), mock.patch.object(access, "restaurer_flux", marker("restore")), mock.patch.object(access, "appliquer", marker("access level"))]
    for patch in patches:
        patch.start()
        unittest.addModuleCleanup(patch.stop)
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()
    unittest.addModuleCleanup(SERVER.shutdown)
    PORT = SERVER.server_address[1]
    session = A.APPAREILS.appairer(A.APPAREILS.nouveau_pin(), "phone")
    DEVICE = {"Cookie": "{}={}".format(S.NOM_COOKIE, session), "X-Token": A.JETON}


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
        self.assertNotIn(A.JETON, page, "the page token is only in the page given to a signed-in device")
        self.assertIn(A.JETON, request("GET", "/", {"Cookie": DEVICE["Cookie"]})[1])


class PairedDevice(unittest.TestCase):
    def test_the_device_is_signed_in_but_cannot_configure(self):
        status, text = request("GET", "/api/etat", DEVICE)
        self.assertEqual(status, 200, text[:200])

    def test_every_route_reserved_to_the_configurator_refuses_a_paired_device(self):
        REACHED.clear()
        called, wrong = 0, []
        for method in ("GET", "POST"):
            for path, right in sorted(CONTRACT["rights"][method].items()):
                if right.endswith(":conditional"):
                    continue                              # depends on what is asked: covered by the tests of each feature, not by a blind call
                address = path + "x" if path in CONTRACT[method]["prefix"] else path
                status, text = request(method, address, DEVICE)
                called += 1
                if status != 403:
                    wrong.append((method, address, status, text[:120]))
        self.assertEqual(wrong, [], "routes reserved to the configurator that answered a paired device")
        self.assertGreater(called, 55, "the inventory lists the reserved routes (the reader may have stopped seeing them)")
        self.assertEqual(REACHED, [], "a refused request reached an action")

    def test_the_guarded_actions_are_among_the_reserved_routes(self):
        """The markers only prove something if the dangerous routes are in the list that is called."""
        reserved = CONTRACT["rights"]["POST"]
        for path in ("/api/acces", "/api/mettre-a-jour", "/api/redemarrer", "/api/admin-distance", "/api/mcp-", "/api/travaux-ajouter"):
            self.assertIn(path, reserved, path)
            self.assertFalse(reserved[path].endswith(":conditional"), path)


if __name__ == "__main__":
    unittest.main()
