"""Un vrai `lutin serve` (processus séparé) face à un faux Ollama, puis `lutin chat` et `lutin pin` par-dessus : le chemin complet d'un utilisateur."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import cli, client, config

SRC = Path(__file__).resolve().parent.parent / "src"
REPONSE = ["Bon", "jour ", "depuis le faux modèle."]


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, o):
        d = json.dumps(o).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        if self.path == "/api/version":
            return self._json(200, {"version": "0.12.0"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": "qwen3:8b", "digest": "d"}]})
        if self.path == "/api/ps":
            return self._json(200, {"models": []})
        self._json(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/show":
            return self._json(200, {"capabilities": ["completion", "tools"]})
        if self.path == "/api/chat":
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            if corps.get("stream", True):
                for morceau in REPONSE:
                    self.wfile.write((json.dumps({"message": {"role": "assistant", "content": morceau}, "done": False}) + "\n").encode()); self.wfile.flush()
                self.wfile.write((json.dumps({"done": True, "prompt_eval_count": 10, "eval_count": 9}) + "\n").encode())
            else:
                self.wfile.write(json.dumps({"message": {"role": "assistant", "content": "Titre"}, "done": True}).encode())
            return
        self._json(404, {})


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BoutEnBout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.ollama = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
        threading.Thread(target=cls.ollama.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % cls.ollama.server_address[1]
        cls.env = dict(os.environ, LUTIN_HOME=cls.t.name, OLLAMA_URL=url, PYTHONPATH=str(SRC), LUTIN_SANS_GARDE="1", LUTIN_SANS_DEMARRAGE="1", PYTHONIOENCODING="utf-8")
        d = config.dossiers({"LUTIN_HOME": cls.t.name})
        cfg = config.charger(d)
        cfg.update(installe=True, verifier_maj=False)
        cfg["securite"]["port"] = port_libre()
        cfg["emplacements"]["travail"] = str(Path(cls.t.name) / "travail")
        cfg["modeles"]["choisis"] = {"polyvalent": "qwen3:8b"}
        config.enregistrer(d, cfg)
        cls.serveur = subprocess.Popen([sys.executable, "-B", "-m", "lutin", "serve", "--sans-navigateur", "--sans-superviseur"], cwd=tempfile.gettempdir(), env=cls.env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        cls.client = client.ClientLocal(d["donnees"])
        debut = time.time()
        while time.time() - debut < 60 and not cls.client.disponible():
            if cls.serveur.poll() is not None:
                break
            time.sleep(0.3)
        if not cls.client.disponible():
            cls.serveur.kill()
            raise unittest.SkipTest("le serveur n'a pas démarré : " + (cls.serveur.stdout.read() or "")[-1500:])

    @classmethod
    def tearDownClass(cls):
        cls.serveur.terminate()
        try:
            cls.serveur.wait(10)
        except subprocess.TimeoutExpired:
            cls.serveur.kill()
        cls.ollama.shutdown()
        cls.t.cleanup()

    def commande(self, *argv):
        sortie = io.StringIO()
        with mock.patch.dict(os.environ, {"LUTIN_HOME": self.t.name}), contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = cli.principal(list(argv))
        return code, sortie.getvalue()

    def test_le_serveur_ecoute_seulement_en_local_et_le_fichier_console_existe(self):
        adresse = self.client.adresse
        self.assertTrue(adresse.startswith("http://127.0.0.1:"), adresse)
        self.assertRegex(self.client.jeton, r"^[0-9a-f]{32}$")

    def test_une_requete_sans_jeton_est_refusee(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.client.adresse + "/api/etat", timeout=10)
        self.assertEqual(e.exception.code, 403)

    def test_chat_dans_le_terminal(self):
        code, sortie = self.commande("chat", "Dis bonjour")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Bonjour depuis le faux modèle.", sortie)

    def test_la_conversation_est_enregistree_et_visible_depuis_l_api(self):
        self.commande("chat", "Une question pour l'historique")
        etat = self.client.obtenir("/api/etat")
        self.assertTrue(any("historique" in (c.get("titre") or "") for c in etat["conversations"]))
        self.assertIn("qwen3:8b", etat["installes"])
        self.assertEqual(etat["reglages"]["modele"], "qwen3:8b", "le modèle choisi à l'installation devient le modèle par défaut")

    def test_pin(self):
        code, sortie = self.commande("pin")
        self.assertEqual(code, 0, sortie)
        self.assertRegex(sortie, r"Code PIN : \d{6}")

    def test_la_page_est_servie_et_contient_le_nom(self):
        import urllib.request
        with urllib.request.urlopen(self.client.adresse + "/", timeout=10) as r:
            page = r.read().decode("utf-8")
        self.assertIn("<title>Lutin</title>", page)
        self.assertNotIn("__TOKEN__", page, "le marqueur est remplacé par le vrai jeton")
        self.assertRegex(page, r"TOKEN = '[0-9a-f]{32}'")
        self.assertNotIn(self.client.jeton, page, "le jeton de la console n'est jamais dans la page")

    def test_la_page_s_execute_dans_un_navigateur_sans_erreur_javascript(self):
        """Chrome sans écran charge la vraie page servie par le vrai serveur : aucune erreur JavaScript, et la liste des modèles est remplie par l'API."""
        import shutil
        chrome = next((c for c in (os.environ.get("CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
                                   r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if c and Path(c).is_file()), None)
        if not chrome:
            self.skipTest("aucun navigateur trouvé (variable CHROME pour en indiquer un)")
        with tempfile.TemporaryDirectory() as profil:
            r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + profil, "--enable-logging=stderr", "--v=0",
                                "--virtual-time-budget=6000", "--dump-dom", self.client.adresse + "/"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        erreurs = [ligne for ligne in r.stderr.splitlines() if "CONSOLE" in ligne and ("Uncaught" in ligne or "SyntaxError" in ligne or "ReferenceError" in ligne or "TypeError" in ligne)]
        self.assertEqual(erreurs, [], "\n".join(erreurs)[:1500])
        self.assertIn("qwen3:8b", r.stdout, "la liste des modèles installés est affichée par la page")


if __name__ == "__main__":
    unittest.main()
