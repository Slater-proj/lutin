"""Un faux llama-server pour les tests : mêmes arguments (-m, --port, -c), sert /health, /v1/models et /v1/chat/completions (d'un coup ou en flux, avec un appel d'outil si des outils sont fournis)."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
import os
if os.environ.get("LUTIN_FAUX_ARGS"):
    open(os.environ["LUTIN_FAUX_ARGS"], "a", encoding="utf-8").write(json.dumps(args) + chr(10))
ROUTEUR = "--models-preset" in args
if ROUTEUR:
    NOMS = [l.strip()[1:-1] for l in open(args[args.index("--models-preset") + 1], encoding="utf-8") if l.strip().startswith("[") and l.strip() != "[*]"]
    modele = "?"
else:
    modele = args[args.index("-m") + 1].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
ctx = args[args.index("-c") + 1] if "-c" in args else "?"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, o):
        d = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        if self.path.endswith("/health"):
            return self._json({"status": "ok"})
        self._json({"data": [{"id": n} for n in NOMS] if ROUTEUR else [{"id": modele}]})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        global modele
        if ROUTEUR:
            if corps.get("model") not in NOMS:
                d = json.dumps({"error": {"message": "model not found"}}).encode()
                self.send_response(404); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
                return
            modele = corps["model"]
        if self.path.endswith("/embeddings"):
            entrees = corps.get("input") or []
            return self._json({"data": [{"index": i, "embedding": [float(len(t)), 1.0, 0.5]} for i, t in enumerate(entrees)]})
        messages = corps.get("messages") or []
        dernier = (messages[-1] if messages else {}).get("role")
        appel = bool(corps.get("tools")) and dernier == "user"
        texte = "Il est 14 h 32." if dernier == "tool" else "réponse de %s (contexte %s)" % (modele, ctx)
        if not corps.get("stream"):
            return self._json({"choices": [{"message": {"content": texte}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if appel:
            morceaux = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "heure", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}]
        else:
            morceaux = [{"choices": [{"delta": {"content": mot + " "}}]} for mot in texte.split()]
        morceaux.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}, "timings": {"predicted_n": 8, "predicted_ms": 400.0, "prompt_ms": 50.0}})
        for m in morceaux:
            self.wfile.write(("data: " + json.dumps(m) + "\n\n").encode()); self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


HTTPServer(("127.0.0.1", port), H).serve_forever()
