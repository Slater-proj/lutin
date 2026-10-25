"""Régénère les captures d'écran du README (assets/capture-*.png) avec un environnement de démonstration : faux Ollama, conversation d'exemple, aucune donnée réelle.

    python tools/captures.py [navigateur]

Il lance un vrai serveur Lutin dans un dossier temporaire, puis Chrome (ou Edge, Chromium) sans écran prend les captures. Rien n'est écrit en dehors de assets/ et du dossier temporaire.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = RACINE / "src"
ASSETS = RACINE / "assets"
MODELES = {"qwen3:8b": "d1", "qwen2.5-coder:7b": "d2", "gemma4:12b": "d3"}


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, o):
        d = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        if self.path == "/api/tags":
            return self._json({"models": [{"name": n, "digest": d, "size": 5_000_000_000} for n, d in MODELES.items()]})
        self._json({"version": "0.12.0", "models": []})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._json({"capabilities": ["completion", "tools"]})


def navigateur(choix=None):
    for c in (choix, os.environ.get("CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if c and Path(c).is_file():
            return c
    raise SystemExit("Aucun navigateur trouvé : indique-le en argument ou avec la variable CHROME.")


def conversation_demo(ident, titre, minutes):
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%S.000", time.localtime(time.time() - minutes * 60))
    return {"id": ident, "titre": titre, "date": maintenant, "maj": maintenant, "resume": "", "travail": "principal", "epingle": ident == "a1b2c3d4", "taches": [
        {"texte": "Relire le README", "etat": "fait"}, {"texte": "Corriger les fautes", "etat": "en_cours"}, {"texte": "Lancer les tests", "etat": "a_faire"}],
        "messages": [
            {"role": "user", "content": "Relis le README du projet et corrige les fautes d'orthographe, sans toucher au reste."},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lire", "arguments": {"chemin": "README.md"}}}]},
            {"role": "tool", "tool_name": "lire", "content": "1\t# Mon projet\n2\tUn petit outil pour classer ses photos par date.\n3\tIl a été écrit en Python et ne demande aucune dépendence."},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "modifier", "arguments": {"chemin": "README.md", "ancien": "dépendence", "nouveau": "dépendance"}}}]},
            {"role": "tool", "tool_name": "modifier", "content": "Modifié : README.md. Ancienne version sauvegardée.\nVérification : syntaxe correcte."},
            {"role": "assistant", "content": "C'est fait : j'ai corrigé **une faute** dans `README.md`.\n\n- « dépendence » est devenu « dépendance » (ligne 3)\n- le reste du fichier est resté identique\n\nLa version précédente est gardée : le bouton **↩ Annuler** la remet en place. Veux-tu que je lance aussi les tests ?"}]}


def principal(choix=None):
    chrome = navigateur(choix)
    base = Path(os.environ.get("PUBLIC") or tempfile.gettempdir())          # un chemin sans nom d'utilisateur : il apparaît en bas de la capture
    tmp = Path(tempfile.mkdtemp(prefix="demo-", dir=str(base)))
    serveur = None
    try:
        ollama = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
        threading.Thread(target=ollama.serve_forever, daemon=True).start()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        home = tmp / "home"
        env = dict(os.environ, LUTIN_HOME=str(home), OLLAMA_URL="http://127.0.0.1:%d" % ollama.server_address[1], PYTHONPATH=str(SRC), LUTIN_SANS_GARDE="1", PYTHONIOENCODING="utf-8")
        for d in ("config", "donnees/conversations", "memoire", "cache"):
            (home / d).mkdir(parents=True)
        (home / "donnees" / "reglages.json").write_text(json.dumps({"seuil_ram_go": 0.5, "seuil_disque_go": 1.0, "plafond_donnees_go": 50.0}), encoding="utf-8")          # la machine qui prend les captures peut être à l'étroit
        (tmp / "Projet").mkdir()
        (tmp / "Documents").mkdir()
        (home / "config" / "config.json").write_text(json.dumps({
            "schema": 1, "installe": True, "verifier_maj": False, "securite": {"niveau": "local", "port": port, "url_publique": "", "proxy_ips": [], "ecoute": ""},
            "emplacements": {"modeles": "", "travail": str(tmp / "Projet"), "travaux": [{"id": "documents", "nom": "Documents", "chemin": str(tmp / "Documents")}], "travail_actif": ""},
            "modeles": {"choisis": {"polyvalent": "qwen3:8b", "code": "qwen2.5-coder:7b"}, "ignores": []}}), encoding="utf-8")
        for ident, titre, minutes in (("a1b2c3d4", "Corriger les fautes du README", 2), ("b2c3d4e5", "Idée de nom pour le projet", 95), ("c3d4e5f6", "Expliquer une erreur de pip", 1500)):
            (home / "donnees" / "conversations" / (ident + ".json")).write_text(json.dumps(conversation_demo(ident, titre, minutes), ensure_ascii=False), encoding="utf-8")
        (home / "cache" / "bench.json").write_text(json.dumps({"qwen3:8b": {"modele": "qwen3:8b", "date": time.strftime("%Y-%m-%dT%H:%M:%S"), "machine": "démonstration", "complet": True, "notes": {},
                                                                              "resultats": {"vitesse": {"tok_s": 54.2, "charge_s": 2.1}, "outils": {"points": 3, "sur": 3}, "code": {"points": 4, "sur": 4},
                                                                                            "francais": {"points": 2, "sur": 2}, "consignes": {"points": 1, "sur": 1}}}}), encoding="utf-8")
        (home / "cache" / "propositions.json").write_text(json.dumps({"date": time.time(), "erreurs": [], "catalogue": "absent", "propositions": [
            {"cle": "nouveau:code:qwen2.5-coder:14b", "type": "nouveau", "role": "code", "modele": "qwen2.5-coder:14b", "ancien": "qwen2.5-coder:7b", "go": 9,
             "phrase": "Écrit et corrige du code de façon fiable ; pour 12 à 16 Go de mémoire vidéo.", "raison": "Mieux noté pour ce rôle (8 contre 7)."}]}), encoding="utf-8")
        serveur = subprocess.Popen([sys.executable, "-B", "-m", "lutin", "serve", "--sans-navigateur", "--sans-superviseur"], cwd=tempfile.gettempdir(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console = home / "donnees" / "console.json"
        debut = time.time()
        while time.time() - debut < 60 and not console.is_file():
            time.sleep(0.3)
        if not console.is_file():
            raise SystemExit("Le serveur de démonstration n'a pas démarré.")
        time.sleep(1.5)
        ASSETS.mkdir(exist_ok=True)
        for nom, ancre in (("capture-conversation.png", "#conv=a1b2c3d4"), ("capture-modeles.png", "#modeles")):
            profil = tmp / ("profil-" + nom)
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1", "--user-data-dir=" + str(profil), "--window-size=1280,800",
                            "--virtual-time-budget=8000", "--screenshot=" + str(ASSETS / nom), "http://127.0.0.1:%d/%s" % (port, ancre)], capture_output=True, timeout=120)
            print("✔ assets/" + nom if (ASSETS / nom).is_file() else "✘ " + nom)
    finally:
        if serveur:
            serveur.terminate()
            try:
                serveur.wait(10)
            except subprocess.TimeoutExpired:
                serveur.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    principal(sys.argv[1] if len(sys.argv) > 1 else None)
