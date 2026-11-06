"""Un faux llama-server pour les tests : mêmes arguments (-m, --port, -c), sert /v1/models et /v1/chat/completions."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
modele = args[args.index("-m") + 1].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
ctx = args[args.index("-c") + 1] if "-c" in args else "?"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, o):
        d = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        self._json({"data": [{"id": modele}]})

    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        self._json({"choices": [{"message": {"content": "réponse de %s (contexte %s)" % (modele, ctx)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})


HTTPServer(("127.0.0.1", port), H).serve_forever()
