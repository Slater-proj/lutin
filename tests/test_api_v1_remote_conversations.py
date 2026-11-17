"""Conversations led on another machine in `/api/v1` (ADR 0016, stages 6 and 7), on a real server with the fake engine of tests/test_moteur.py.

The server pairs with itself (as tests/test_api_v1_machines.py does): it is this machine and the host of the conversation, so each request goes
through the real relay (`/api/noeud/relais/…`, node token, the right « lead ») to the host's own legacy routes. What is fixed here: the answers in
the shapes of the local routes, the stream translated into English events, a distinct status for each refusal (404 unknown, 403 « lead » not
granted, 503 the host does not answer, 400 a wrong value, sent before anything reaches the host), and the files kept by the host. What the node
reads of this computer (network cards, autostart, memory) is replaced."""
import json
import unittest
import urllib.error
import urllib.request

import test_api_v1_machines as M  # its callers, the fake engine of tests/test_moteur.py and `until` (imported as a module: its tests do not run here)

from lutin import api_v1, machines  # noqa: E402
import quiet_node  # noqa: E402  (what a node reads of this computer, replaced)

T, A, api, until = M.T, M.A, M.api, M.until
UNKNOWN = "0" * 32
CONVERSATION_FIELDS = ["created_at", "id", "machine", "messages", "pinned", "summary", "title", "updated_at"]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def raw(method, path, data, content_type="application/octet-stream", headers=None):
    request = urllib.request.Request(T.BASE + path, method=method, data=data, headers=dict({"Content-Type": content_type, "X-Token": A.JETON}, **(headers or {})))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read()


def stream(path, body, scenario):
    """(status, events) of a relayed turn, or (status, error) when it is refused before the stream."""
    T.SCENARIO[:] = scenario
    request = urllib.request.Request(T.BASE + path, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "X-Token": A.JETON})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, [json.loads(line) for line in response if line.strip()]
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read().decode("utf-8"))


class RemoteConversations(unittest.TestCase):
    def setUp(self):
        quiet_node.quiet(self)
        for kept in (machines.SONDES, machines.DERNIER_ETAT, machines.CODES, machines.INFOS_NOEUD):
            kept.clear()
        machines.CARTES.update(t=-999.0, v=None)
        machines.CONVERSATIONS.update(t=0.0, v=[], en_cours=False)
        A.LIMITEUR_PIN.evenements.clear()
        machines.noeud_activer(True)
        self.host = machines.ajouter(T.BASE, machines.noeud_nouveau_code()["code"], "Bureau")
        machines.noeud_autoriser_piloter(True)
        self.conversation = A.conv_nouvelle()["id"]
        self.base = "/api/v1/machines/{}/conversations/{}".format(self.host["id"], self.conversation)

        def restore():
            machines._ecrire_registre([])
            machines.noeud_autoriser_piloter(False)
            for allowed in machines.noeud_vue()["autorisees"]:
                machines.noeud_revoquer(allowed["nom"])
            machines.noeud_activer(False)
            for kept in (machines.SONDES, machines.DERNIER_ETAT, machines.CODES):
                kept.clear()
            machines.CONVERSATIONS.update(t=0.0, v=[], en_cours=False)
            try:
                A.conv_supprimer(self.conversation)
            except (OSError, ValueError):
                pass
        self.addCleanup(restore)

    def test_the_conversations_of_the_host_are_listed_under_its_name(self):
        A.conv_renommer(self.conversation, "Rapport du bureau")
        listed = until(lambda: [entry for entry in api("GET", "/api/v1/machines/conversations")[1]["conversations"] if entry["id"] == self.conversation], 20)
        self.assertEqual(len(listed), 1, "the host lists it once « lead » is granted")
        self.assertEqual((sorted(listed[0]), listed[0]["machine"], listed[0]["machine_name"], listed[0]["title"]),
                         (["id", "machine", "machine_name", "message_count", "title", "updated_at"], self.host["id"], "Bureau", "Rapport du bureau"))
        before = A.reglages().get("cluster")
        A.enregistrer_reglages({"cluster": False})
        self.addCleanup(lambda: A.enregistrer_reglages({"cluster": before}))
        self.assertEqual(api("GET", "/api/v1/machines/conversations")[1]["conversations"], [], "the multi-machine mode is off")

    def test_a_conversation_is_read_in_the_shape_of_a_local_one(self):
        status, read = api("GET", self.base)
        self.assertEqual((status, sorted(read), read["id"], read["machine"]), (200, CONVERSATION_FIELDS, self.conversation, self.host["id"]))
        self.assertEqual(read["messages"], [])

    def test_each_refusal_has_its_status(self):
        self.assertEqual(api("GET", "/api/v1/machines/{}/conversations/{}".format(UNKNOWN, self.conversation))[1]["error"]["code"], "not_found")
        self.assertEqual(api("GET", "/api/v1/machines/{}/conversations/{}".format(self.host["id"], "nothere!"))[1]["error"]["code"], "not_found")
        self.assertEqual(api("GET", "/api/v1/machines/{}/conversations/{}".format(self.host["id"], "0123abcd"))[0], 404, "the host has no such conversation")
        machines.noeud_autoriser_piloter(False)
        status, answer = api("GET", self.base)
        self.assertEqual((status, answer["error"]["code"]), (403, "machine_refused"), "the host does not grant « lead »")
        self.assertIn("conversations pilotées", answer["error"]["message"], "the host's sentence is passed on")
        machines.noeud_autoriser_piloter(True)
        for body in ({}, {"message": ""}, {"message": 1}, {"message": "Hi", "model": "x"}):
            self.assertEqual(stream(self.base + "/turns", body, [])[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(A.conv_lire(self.conversation)["messages"], [], "nothing reached the host")
        for body in ({"approved": "yes"}, {"approved": True, "remember": "always"}):
            self.assertEqual(api("POST", "/api/v1/machines/{}/approvals/abc".format(self.host["id"]), body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(api("POST", self.base + "/memory-choice", {"choice": "summary"})[1]["error"]["code"], "conflict", "no question waits")
        machines._ecrire_registre([dict(machines.lire()[0], adresse="http://127.0.0.1:9")])
        machines.SONDES.clear()
        machines.DERNIER_ETAT.clear()
        status, answer = api("GET", self.base)
        self.assertEqual((status, answer["error"]["code"]), (503, "machine_unreachable"))
        self.assertIn("Bureau", answer["error"]["message"])

    def test_a_turn_runs_on_the_host_and_streams_english_events(self):
        status, events = stream(self.base + "/turns", {"message": "Hello from here"}, [[{"content": "Hello from "}, {"content": "the host."}]])
        self.assertEqual(status, 200, events)
        english = {name for name, _ in api_v1.EVENTS.values()}
        self.assertEqual(sorted({event["type"] for event in events} - english), [], "no event keeps its French name")
        self.assertEqual(events[0], {"type": "start", "conversation_id": self.conversation})
        self.assertEqual("".join(event["text"] for event in events if event["type"] == "text"), "Hello from the host.")
        self.assertEqual((events[-1]["type"], events[-1]["conversation"]["id"]), ("end", self.conversation))
        stored = api("GET", self.base)[1]
        self.assertEqual([(m["role"], m["content"]) for m in stored["messages"] if m["role"] in ("user", "assistant")],
                         [("user", "Hello from here"), ("assistant", "Hello from the host.")], "kept by the host")
        self.assertEqual(api("POST", self.base + "/stop"), (200, {"was_running": False}))

    def test_an_approval_of_the_host_is_answered_through_this_machine(self):
        call = T.appel_outil("modifier", chemin="appli/moteur/code.py", ancien="return 1", nouveau="return 2")
        T.SCENARIO[:] = [[call], [{"content": "Understood."}]]
        request = urllib.request.Request(T.BASE + self.base + "/turns", data=json.dumps({"message": "Change it"}).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "X-Token": A.JETON})
        asked = []
        with urllib.request.urlopen(request, timeout=60) as response:
            for line in response:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["type"] == "approval_request":
                    asked.append(event)
                    status, answer = api("POST", "/api/v1/machines/{}/approvals/{}".format(self.host["id"], event["id"]), {"approved": False})
                    self.assertEqual((status, answer), (200, {"approved": False}))
        self.assertEqual(len(asked), 1)
        self.assertEqual((T.PROJET / "appli" / "moteur" / "code.py").read_text(encoding="utf-8"), "def f():\n    return 1\n", "refused: the file is untouched")

    def test_renaming_pinning_and_deleting_happen_on_the_host(self):
        status, changed = api("PATCH", self.base, {"title": "Notes du bureau", "pinned": True})
        self.assertEqual((status, changed["title"], changed["pinned"], sorted(changed)), (200, "Notes du bureau", True, CONVERSATION_FIELDS))
        self.assertEqual(A.conv_lire(self.conversation)["titre"], "Notes du bureau")
        for body in ({}, {"title": ""}, {"pinned": "yes"}, {"title": "x", "colour": "red"}):
            self.assertEqual(api("PATCH", self.base, body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(api("DELETE", self.base), (200, {"deleted": True}))
        self.assertRaises(ValueError, A.conv_lire, self.conversation)

    def test_images_and_documents_are_kept_by_the_host(self):
        status, _, body = raw("POST", "/api/v1/machines/{}/images".format(self.host["id"]), PNG)
        image = json.loads(body)
        self.assertEqual((status, sorted(image)), (201, ["id", "url"]), image)
        self.assertEqual(image["url"], "/api/v1/machines/{}/images/{}".format(self.host["id"], image["id"]))
        status, headers, data = raw("GET", image["url"], None)
        self.assertEqual((status, data, headers.get("Content-Type")), (200, PNG, "image/png"))
        self.assertIn("sandbox", headers.get("Content-Security-Policy", ""))
        status, _, body = raw("POST", "/api/v1/machines/{}/attachments".format(self.host["id"]), "Ligne une.\nLigne deux.\n".encode("utf-8"),
                              headers={"X-Name": "notes%20du%20bureau.txt"})
        document = json.loads(body)
        self.assertEqual((status, sorted(document), document["name"]), (201, ["characters", "id", "name"], "notes du bureau.txt"), document)
        status, headers, data = raw("GET", "/api/v1/machines/{}/attachments/{}?name=notes.txt".format(self.host["id"], document["id"]), None)
        self.assertEqual((status, data), (200, "Ligne une.\nLigne deux.\n".encode("utf-8")))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertEqual(raw("GET", "/api/v1/machines/{}/images/{}".format(self.host["id"], "..%2Fsecret"), None)[0], 404)
        status, events = stream(self.base + "/turns", {"message": "Look", "images": [image["id"]], "attachments": [{"id": document["id"], "name": document["name"]}]},
                                [[{"content": "Seen."}]])
        self.assertEqual((status, events[-1]["type"]), (200, "end"))
        sent = [m for m in A.conv_lire(self.conversation)["messages"] if m["role"] == "user"][-1]
        self.assertEqual((sent.get("images"), [piece["id"] for piece in sent.get("pieces", [])]), ([image["id"]], [document["id"]]), "the host keeps what was sent")


if __name__ == "__main__":
    unittest.main()
