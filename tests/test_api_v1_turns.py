"""`POST /api/v1/conversations/{id}/turns`: the answer stream of the versioned API, on a real server with the fake engine of tests/test_moteur.py.

What is fixed here: the English name of every event and of every field, the refusals that come before the stream, and the fact that nothing French
leaks: the source is read, and an event or a field the agent emits without an entry in `api_v1.EVENTS` fails a test."""
import ast
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import test_moteur as T  # the fake engine, its temporary folders and a server at the « this machine » level (imported as a module: its tests do not run here)

from lutin import api_v1  # noqa: E402

A = T.A
SOURCE = Path(__file__).resolve().parent.parent / "src" / "lutin"


def api(method, path, body=None):
    request = urllib.request.Request(T.BASE + path, method=method, data=None if body is None else json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Token": A.JETON})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read().decode("utf-8"))


def turn(conversation, body, scenario=None, approve=None):
    """Sends a message and returns (status, events), or (status, error) when the turn is refused before the stream. `approve(event)` answers an approval request."""
    T.SCENARIO[:] = scenario or []
    request = urllib.request.Request("{}/api/v1/conversations/{}/turns".format(T.BASE, conversation), data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Token": A.JETON})
    events = []
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get("Content-Type")
            for raw in response:
                if not raw.strip():
                    continue                                    # the heartbeat of the stream
                events.append(json.loads(raw.decode("utf-8")))
                if events[-1]["type"] == "approval_request":
                    api("POST", "/api/v1/approvals/" + events[-1]["id"], {"approved": bool(approve and approve(events[-1]))})
            return response.status, content_type, events
    except urllib.error.HTTPError as refused:
        return refused.code, refused.headers.get("Content-Type"), json.loads(refused.read().decode("utf-8"))


def new_conversation():
    status, created = api("POST", "/api/v1/conversations", {})
    assert status == 201, (status, created)
    return created["id"]


def of_type(events, name):
    return [event for event in events if event["type"] == name]


class Stream(unittest.TestCase):
    def test_a_turn_streams_english_events_from_start_to_end(self):
        conversation = new_conversation()
        status, content_type, events = turn(conversation, {"message": "Hello", "thinking": True}, [[{"thinking": "let me think"}, {"content": "Good "}, {"content": "morning"}]])
        self.assertEqual((status, content_type), (200, "application/x-ndjson; charset=utf-8"))
        self.assertEqual(events[0], {"type": "start", "conversation_id": conversation})
        self.assertEqual("".join(event["text"] for event in of_type(events, "text")), "Good morning")
        self.assertEqual("".join(event["text"] for event in of_type(events, "thinking")), "let me think")
        self.assertEqual(sorted(events[-1]), ["conversation", "type"])
        self.assertEqual((events[-1]["type"], sorted(events[-1]["conversation"]), events[-1]["conversation"]["id"]), ("end", ["id", "title"], conversation))
        tokens, speed = of_type(events, "tokens"), of_type(events, "speed")
        self.assertEqual(sorted(tokens[-1]), ["measured", "total", "type", "used"])
        self.assertEqual((tokens[-1]["used"], tokens[-1]["measured"]), (1300, True), "the figures of the fake engine: 1234 read + 66 written")
        self.assertEqual(sorted(speed[-1]), ["load_s", "read_tokens_per_s", "tokens", "total_s", "type", "write_tokens_per_s"])
        self.assertEqual((speed[-1]["write_tokens_per_s"], speed[-1]["tokens"], speed[-1]["load_s"], speed[-1]["total_s"]), (33.0, 66, 1.5, 4.0))
        english = {name for name, _ in api_v1.EVENTS.values()}
        self.assertEqual(sorted({event["type"] for event in events} - english), [], "no event keeps its French name")
        status, stored = api("GET", "/api/v1/conversations/" + conversation)
        self.assertEqual([(m["role"], m["content"]) for m in stored["messages"] if m["role"] in ("user", "assistant")], [("user", "Hello"), ("assistant", "Good morning")])

    def test_a_tool_call_waits_for_an_approval_answered_through_v1(self):
        conversation, asked = new_conversation(), []
        call = T.appel_outil("modifier", chemin="appli/moteur/code.py", ancien="return 1", nouveau="return 2")
        status, _, events = turn(conversation, {"message": "Change it"}, [[call], [{"content": "Understood."}]], approve=lambda event: asked.append(event) or False)
        self.assertEqual(status, 200)
        self.assertEqual(of_type(events, "tool_call")[0], {"type": "tool_call", "name": "modifier", "arguments": {"chemin": "appli/moteur/code.py", "ancien": "return 1", "nouveau": "return 2"}})
        self.assertEqual(len(asked), 1)
        self.assertEqual(sorted(asked[0]), ["auto_approval_suspended", "detail", "diff", "id", "reason", "title", "type"])
        self.assertIn("return 2", asked[0]["diff"])
        result = of_type(events, "tool_result")[0]
        self.assertEqual((sorted(result), result["name"]), (["name", "text", "type"], "modifier"))
        self.assertEqual((T.PROJET / "appli" / "moteur" / "code.py").read_text(encoding="utf-8"), "def f():\n    return 1\n", "refused: the file is untouched")
        self.assertEqual(events[-1]["type"], "end")

    def test_a_failure_during_the_turn_is_an_error_event_with_a_code(self):
        status, _, events = turn(new_conversation(), {"message": "Hello"}, [[{"error": "model exploded"}]] * 6)
        self.assertEqual(status, 200)
        errors = of_type(events, "error")
        self.assertTrue(errors, [event["type"] for event in events])
        self.assertEqual((sorted(errors[-1]), sorted(errors[-1]["error"]), errors[-1]["error"]["code"]), (["error", "type"], ["code", "message"], "turn_failed"))
        self.assertEqual(events[-1]["type"], "end")


class Refusals(unittest.TestCase):
    """Before the stream: an ordinary v1 error, and nothing is created or left running."""

    def test_the_body_is_checked(self):
        conversation = new_conversation()
        fields = "Champs acceptés : message, model, thinking, replace_from, images, attachments, workspace."
        for body in ({}, {"message": 3}, {"message": "Hello", "modele": "x"}, {"message": "Hello", "options": {}}):
            self.assertEqual(turn(conversation, body)[::2], (400, {"error": {"code": "invalid_request", "message": fields}}), body)
        self.assertEqual(turn(conversation, {"message": "  "})[::2], (400, {"error": {"code": "invalid_request", "message": "Écris un message (60 000 caractères au maximum)."}}))
        self.assertEqual(turn(conversation, {"message": "Hello", "replace_from": 7})[2]["error"]["code"], "invalid_request")
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            self.assertEqual(turn(conversation, {"message": ""})[2], {"error": {"code": "invalid_request", "message": "Write a message (60,000 characters at most)."}})
        self.assertEqual(api("GET", "/api/v1/conversations/" + conversation)[1]["messages"], [])

    def test_an_unknown_conversation_is_not_created(self):
        before = len(api("GET", "/api/v1/conversations")[1]["conversations"])
        self.assertEqual(turn("ffffffff", {"message": "Hello"})[::2], (404, {"error": {"code": "not_found", "message": "Conversation inconnue."}}))
        self.assertEqual(len(api("GET", "/api/v1/conversations")[1]["conversations"]), before)

    def test_a_conversation_already_answering_and_too_many_turns(self):
        conversation = new_conversation()
        with mock.patch.dict(A.TOURS_ACTIFS, {conversation: threading.Event()}):
            status, _, answer = turn(conversation, {"message": "Hello"})
            self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))
        with mock.patch.object(A, "TOURS_SIMULTANES", 0):
            status, _, answer = turn(conversation, {"message": "Hello"})
            self.assertEqual((status, sorted(answer["error"]), answer["error"]["code"]), (429, ["code", "message"], "too_many_turns"))
        self.assertNotIn(conversation, A.TOURS_ACTIFS)

    def test_the_memory_choice_of_a_long_conversation_is_answered_through_v1(self):
        conversation, path = new_conversation(), "/api/v1/conversations/{}/memory-choice"
        self.assertEqual(api("POST", path.format(conversation), {"choice": "file"}), (409, {"error": {"code": "no_pending_choice", "message": "Plus de question en attente pour cette conversation."}}))
        waiting = {"evenement": threading.Event(), "choix": None, "garder": False}
        with mock.patch.dict(A.CHOIX_MEMOIRE, {conversation: waiting}):
            for body in ({}, {"choice": "fichier"}, {"choice": "file", "remember": 1}, {"choice": "file", "garder": True}):
                status, answer = api("POST", path.format(conversation), body)
                self.assertEqual((status, answer["error"]["code"], waiting["evenement"].is_set()), (400, "invalid_request", False), body)
            self.assertEqual(api("POST", path.format(conversation), {"choice": "file", "remember": True}), (200, {"choice": "file"}))
        self.assertEqual((waiting["choix"], waiting["garder"], waiting["evenement"].is_set()), ("fichier", True, True))

    def test_the_french_route_keeps_its_names(self):
        events = T.chat("Bonjour", reponses=[[{"content": "Salut"}]])
        self.assertEqual((events[0]["type"], events[-1]["type"], T.texte_de(events)), ("debut", "fin", "Salut"))
        self.assertEqual(sorted(events[-1]["conversation"]), ["id", "titre"])


class Table(unittest.TestCase):
    """The stream is translated from a table: what the agent emits is read in the source, so that a new event or a new field cannot go out in French unnoticed."""

    @staticmethod
    def emitted():
        found = []
        for file in sorted(SOURCE.glob("*.py")):
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Dict):
                    keys = [key.value if isinstance(key, ast.Constant) else None for key in node.keys]
                    kind = node.values[keys.index("type")] if "type" in keys else None
                    if isinstance(kind, ast.Constant):
                        found.append((file.name, node.lineno, kind.value, {key for key in keys if key and key != "type"}, False))
                elif isinstance(node, ast.Call) and node.args:
                    function = node.func
                    name = function.id if isinstance(function, ast.Name) else function.slice.value if isinstance(function, ast.Subscript) and isinstance(function.slice, ast.Constant) else ""
                    first = node.args[0]
                    if name != "emit":
                        continue
                    if isinstance(first, ast.Dict):
                        keys = [key.value if isinstance(key, ast.Constant) else None for key in first.keys]
                        kind = first.values[keys.index("type")] if "type" in keys else None
                        found.append((file.name, node.lineno, kind.value if isinstance(kind, ast.Constant) else None, set(), True))
                    elif isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "dict":
                        kinds = [keyword.value.value for keyword in first.keywords if keyword.arg == "type" and isinstance(keyword.value, ast.Constant)]
                        inner = [arg for arg in first.args if isinstance(arg, ast.Dict)]
                        if kinds:
                            found.append((file.name, node.lineno, kinds[0], {keyword.arg for keyword in first.keywords if keyword.arg and keyword.arg != "type"}, True))
                        elif not inner:
                            found.append((file.name, node.lineno, None, set(), True))
                    else:
                        found.append((file.name, node.lineno, None, set(), True))
        return found

    def test_every_emitted_event_has_an_english_name(self):
        emitted = [entry for entry in self.emitted() if entry[4]]
        self.assertGreater(len(emitted), 30, "the reading of the source found the calls to emit")
        unknown = sorted((file, line, kind) for file, line, kind, _, _ in emitted if kind not in api_v1.EVENTS)
        self.assertEqual(unknown, [], "emitted without an entry in api_v1.EVENTS (file, line, type)")

    def test_every_field_of_an_event_has_an_english_name(self):
        unknown = sorted((file, line, kind, sorted(fields - set(api_v1.EVENTS[kind][1]))) for file, line, kind, fields, _ in self.emitted()
                         if kind in api_v1.EVENTS and fields - set(api_v1.EVENTS[kind][1]))
        self.assertEqual(unknown, [], "fields without an English name in api_v1.EVENTS (file, line, type, fields)")

    def test_the_fields_given_through_a_variable(self):
        """Three events take their fields from a variable, which the reading of the source cannot see: they are checked on the functions that build them."""
        speed = A.calculer_vitesse({"eval_count": 66, "prompt_eval_count": 1234, "eval_duration": 2e9, "prompt_eval_duration": 5e8, "load_duration": 1.5e9, "total_duration": 4e9})
        self.assertEqual(sorted(set(speed) - set(api_v1.EVENTS["vitesse"][1])), [])
        self.assertEqual(sorted({"utilise", "total", "reel"} - set(api_v1.EVENTS["jetons"][1])), [])
        self.assertEqual(sorted({"medias", "medias_fichiers", "fichiers_joints"} - set(api_v1.EVENTS["resultat"][1])), [])

    def test_names_are_english_and_unique(self):
        names = [name for name, _ in api_v1.EVENTS.values()]
        self.assertEqual(len(names), len(set(names)))
        for name, fields in api_v1.EVENTS.values():
            for word in [name, *fields.values()]:
                self.assertRegex(word, r"^[a-z][a-z0-9_]*$")

    def test_translation_of_the_shapes_that_are_not_a_plain_renaming(self):
        self.assertEqual(api_v1.event({"type": "taches", "liste": [{"texte": "a", "etat": "fait"}, {"texte": "b", "etat": "en_cours"}, {"texte": "c", "etat": "a_faire"}]}),
                         {"type": "tasks", "tasks": [{"text": "a", "state": "done"}, {"text": "b", "state": "in_progress"}, {"text": "c", "state": "todo"}]})
        self.assertEqual(api_v1.event({"type": "fin", "conversation": {"id": "0123abcd", "titre": "T"}}), {"type": "end", "conversation": {"id": "0123abcd", "title": "T"}})
        self.assertEqual(api_v1.event({"type": "erreur", "texte": "boom"}), {"type": "error", "error": {"code": "turn_failed", "message": "boom"}})
        self.assertEqual(api_v1.event({"type": "accord_retabli"}), {"type": "auto_approval_restored"})
        self.assertEqual(api_v1.event({"type": "approbation", "id": "x", "titre": "t", "detail": "d", "diff": "", "raison": "r", "suspendu": True}),
                         {"type": "approval_request", "id": "x", "title": "t", "detail": "d", "diff": "", "reason": "r", "auto_approval_suspended": True})
        self.assertEqual(api_v1.event({"type": "something_new", "x": 1}), {"type": "something_new", "x": 1}, "an unknown event goes through unchanged")


if __name__ == "__main__":
    unittest.main()
