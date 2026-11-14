"""Moteur compatible OpenAI : traduction des demandes et des flux (format d'Ollama dedans), contre un faux serveur qui parle /v1."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import context  # noqa: F401
from lutin import openai_engine as mo

RECUES = []


class Faux(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            corps = json.dumps({"data": [{"id": "qwen-test", "meta": {"size": 2_000_000_000}}, {"id": "autre"}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(corps))); self.end_headers(); self.wfile.write(corps)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        RECUES.append((self.path, corps, self.headers.get("Authorization")))
        if not corps.get("stream"):
            rep = json.dumps({"choices": [{"message": {"content": "Bonjour", "tool_calls": [{"function": {"name": "lire", "arguments": "{\"chemin\": \"a.txt\"}"}}]}, "finish_reason": "tool_calls"}],
                              "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(rep))); self.end_headers(); self.wfile.write(rep)
            return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        morceaux = [{"choices": [{"delta": {"reasoning_content": "je réfléchis"}}]}, {"choices": [{"delta": {"content": "Sal"}}]}, {"choices": [{"delta": {"content": "ut"}}]},
                    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "lire", "arguments": "{\"chem"}}]}}]},
                    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "in\": \"b.txt\"}"}}]}, "finish_reason": "tool_calls"}]},
                    {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 9}, "timings": {"predicted_ms": 900.0, "predicted_n": 9, "prompt_ms": 100.0}}]
        for m in morceaux:
            self.wfile.write(("data: " + json.dumps(m) + "\n\n").encode()); self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
ADRESSE = "http://127.0.0.1:%d/v1" % SERVEUR.server_address[1]


class Essai(mo.MoteurOpenAI):
    id, nom = "essai", "Essai"

    def adresse(self):
        return ADRESSE

    def cle(self):
        return "secret"


class Traduction(unittest.TestCase):
    def test_messages_outils_images_et_options(self):
        corps = {"model": "m", "stream": True, "options": {"temperature": 0.3, "top_p": 0.9, "top_k": 40, "num_predict": 200, "num_ctx": 8192}, "tools": [{"type": "function", "function": {"name": "lire"}}],
                 "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "Lis a", "images": ["iVBORw0KGgo="]},
                              {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lire", "arguments": {"chemin": "a"}}}]},
                              {"role": "tool", "tool_name": "lire", "content": "contenu"}, {"role": "tool", "tool_name": "orphelin", "content": "reste"}]}
        s = mo.vers_openai(corps)
        self.assertEqual((s["model"], s["temperature"], s["top_p"], s["top_k"], s["max_tokens"]), ("m", 0.3, 0.9, 40, 200))
        self.assertNotIn("num_ctx", s)
        self.assertEqual(s["stream_options"], {"include_usage": True})
        self.assertEqual(s["tools"], corps["tools"])
        u = s["messages"][1]["content"]
        self.assertEqual(u[1]["image_url"]["url"], "data:image/png;base64,iVBORw0KGgo=")
        appel = s["messages"][2]["tool_calls"][0]
        self.assertEqual((appel["id"], appel["function"]["arguments"]), ("call_1", "{\"chemin\": \"a\"}"), "arguments en texte JSON")
        self.assertEqual(s["messages"][3], {"role": "tool", "tool_call_id": "call_1", "content": "contenu"}, "le résultat reprend l'identifiant de l'appel")
        self.assertEqual(s["messages"][4]["role"], "user", "un résultat sans appel devient du texte (le serveur le refuserait)")

    def test_arguments_mal_fermes_et_formats(self):
        self.assertEqual(mo.arguments_json('{"a": 1'), {"a": 1})
        self.assertEqual(mo.arguments_json('{"a": 1,}'), {"a": 1})
        self.assertEqual(mo.arguments_json(""), {})
        self.assertEqual(mo.arguments_json("n'importe quoi"), {})
        s = mo.vers_openai({"model": "m", "stream": False, "format": "json", "messages": []})
        self.assertEqual(s["response_format"], {"type": "json_object"})
        self.assertNotIn("stream_options", s)


class AvecUnServeur(unittest.TestCase):
    def setUp(self):
        RECUES.clear()
        self.m = Essai()

    def test_actif_et_modeles(self):
        self.assertTrue(self.m.actif())
        r = self.m.modeles()
        self.assertEqual((r["actif"], r["installes"], r["tailles"]), (True, ["qwen-test", "autre"], {"qwen-test": 2_000_000_000}))
        self.assertEqual(self.m.en_memoire("qwen-test"), {"taille": 0, "vram": 0}, "prêt : pas de « chargement » annoncé")

    def test_un_serveur_absent_est_inactif_sans_erreur(self):
        class Absent(Essai):
            def adresse(self):
                return "http://127.0.0.1:9/v1"
        self.assertFalse(Absent().actif())
        self.assertEqual(Absent().modeles(), {"actif": False, "installes": [], "tailles": {}})
        self.assertIsNone(Absent().en_memoire("x"))

    def test_chat_d_un_coup(self):
        r = self.m.chat({"model": "qwen-test", "messages": [{"role": "user", "content": "Salut"}], "options": {"temperature": 0.1}}, 10)
        self.assertEqual(r["message"]["content"], "Bonjour")
        self.assertEqual(r["message"]["tool_calls"], [{"function": {"name": "lire", "arguments": {"chemin": "a.txt"}}}])
        self.assertEqual((r["prompt_eval_count"], r["eval_count"], r["done"]), (7, 3, True))
        chemin, corps, auth = RECUES[0]
        self.assertEqual((chemin, corps["stream"], auth), ("/v1/chat/completions", False, "Bearer secret"))

    def test_chat_en_flux_traduit_au_format_d_ollama(self):
        with self.m.chat_flux({"model": "qwen-test", "messages": [{"role": "user", "content": "Salut"}]}, 10) as flux:
            evenements = list(flux)
        self.assertEqual("".join(e["message"].get("content", "") for e in evenements if e.get("message")), "Salut")
        self.assertEqual([e["message"]["thinking"] for e in evenements if e.get("message", {}).get("thinking")], ["je réfléchis"])
        appels = [a for e in evenements for a in e.get("message", {}).get("tool_calls", [])]
        self.assertEqual(appels, [{"function": {"name": "lire", "arguments": {"chemin": "b.txt"}}}], "l'appel d'outil est reconstitué morceau par morceau")
        fin = evenements[-1]
        self.assertTrue(fin["done"])
        self.assertEqual((fin["prompt_eval_count"], fin["eval_count"], fin["eval_duration"]), (20, 9, 900_000_000))
        self.assertEqual(fin["done_reason"], "stop")
        self.assertTrue(RECUES[0][1]["stream"])


if __name__ == "__main__":
    unittest.main()
