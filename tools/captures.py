"""Régénère les captures d'écran du README (assets/capture-*.png) avec un environnement de démonstration : faux Ollama, conversation d'exemple, aucune donnée réelle.

    python tools/captures.py [navigateur]

Il lance un vrai serveur Lutin dans un dossier temporaire, puis Chrome (ou Edge, Chromium) sans écran prend les captures. Rien n'est écrit en dehors de assets/ et du dossier temporaire.
"""
import contextlib
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


# Le contenu de démonstration (conversations, tâches, proposition) existe dans les deux langues : les captures du README suivent la langue de l'interface.
DEMO = {
    "fr": {
        "titres": ("Corriger les fautes du README", "Idée de nom pour le projet", "Expliquer une erreur de pip"),
        "taches": ("Relire le README", "Corriger les fautes", "Lancer les tests"),
        "demande": "Relis le README du projet et corrige les fautes d'orthographe, sans toucher au reste.",
        "lecture": "1\t# Mon projet\n2\tUn petit outil pour classer ses photos par date.\n3\tIl a été écrit en Python et ne demande aucune dépendence.",
        "faute": ("dépendence", "dépendance"),
        "ecriture": "Modifié : README.md. Ancienne version sauvegardée.\nVérification : syntaxe correcte.",
        "reponse": "C'est fait : j'ai corrigé **une faute** dans `README.md`.\n\n- « dépendence » est devenu « dépendance » (ligne 3)\n- le reste du fichier est resté identique\n\nLa version précédente est gardée : le bouton **↩ Annuler** la remet en place. Veux-tu que je lance aussi les tests ?",
        "machine": "démonstration",
        "phrase": "Écrit et corrige du code de façon fiable ; pour 12 à 16 Go de mémoire vidéo.",
        "raison": "Mieux noté pour ce rôle (8 contre 7).",
    },
    "en": {
        "titres": ("Fix the README typos", "Name ideas for the project", "Explain a pip error"),
        "taches": ("Read the README", "Fix the typos", "Run the tests"),
        "demande": "Read the project's README and fix the spelling mistakes, without touching anything else.",
        "lecture": "1\t# My project\n2\tA small tool to sort your photos by date.\n3\tIt was written in Python and needs no dependancy.",
        "faute": ("dependancy", "dependency"),
        "ecriture": "Modified: README.md. Old version saved.\nCheck: syntax is correct.",
        "reponse": "Done: I fixed **one typo** in `README.md`.\n\n- « dependancy » became « dependency » (line 3)\n- the rest of the file is unchanged\n\nThe previous version is kept: the **↩ Undo** button puts it back. Shall I run the tests too?",
        "machine": "demo",
        "phrase": "Writes and fixes code reliably; for 12 to 16 GB of video memory.",
        "raison": "Better rated for this role (8 against 7).",
    },
}


def conversation_demo(ident, titre, minutes, langue="fr"):
    d = DEMO[langue]
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%S.000", time.localtime(time.time() - minutes * 60))
    return {"id": ident, "titre": titre, "date": maintenant, "maj": maintenant, "resume": "", "travail": "principal", "epingle": ident == "a1b2c3d4", "taches": [
        {"texte": d["taches"][0], "etat": "fait"}, {"texte": d["taches"][1], "etat": "en_cours"}, {"texte": d["taches"][2], "etat": "a_faire"}],
        "messages": [
            {"role": "user", "content": d["demande"]},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lire", "arguments": {"chemin": "README.md"}}}]},
            {"role": "tool", "tool_name": "lire", "content": d["lecture"]},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "modifier", "arguments": {"chemin": "README.md", "ancien": d["faute"][0], "nouveau": d["faute"][1]}}}]},
            {"role": "tool", "tool_name": "modifier", "content": d["ecriture"]},
            {"role": "assistant", "content": d["reponse"]}]}


@contextlib.contextmanager
def serveur_demo(variables=None):
    """Un vrai serveur Lutin dans un dossier temporaire (faux Ollama, conversation d'exemple) ; rend (port, dossier temporaire). `variables` complète l'environnement (ex. LUTIN_LANGUE)."""
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
        langue = (variables or {}).get("LUTIN_LANGUE", "fr")
        env = dict(os.environ, LUTIN_HOME=str(home), OLLAMA_URL="http://127.0.0.1:%d" % ollama.server_address[1], PYTHONPATH=str(SRC), LUTIN_SANS_GARDE="1", PYTHONIOENCODING="utf-8", **(variables or {}))
        for d in ("config", "donnees/conversations", "memoire", "cache"):
            (home / d).mkdir(parents=True)
        (home / "donnees" / "reglages.json").write_text(json.dumps({"seuil_ram_go": 0.5, "seuil_disque_go": 1.0, "plafond_donnees_go": 50.0}), encoding="utf-8")          # la machine qui prend les captures peut être à l'étroit
        (tmp / ("Project" if langue == "en" else "Projet")).mkdir()
        (tmp / "Documents").mkdir()
        (home / "config" / "config.json").write_text(json.dumps({
            "schema": 1, "installe": True, "verifier_maj": False, "securite": {"niveau": "local", "port": port, "url_publique": "", "proxy_ips": [], "ecoute": ""},
            "emplacements": {"modeles": "", "travail": str(tmp / ("Project" if langue == "en" else "Projet")), "travaux": [{"id": "documents", "nom": "Documents", "chemin": str(tmp / "Documents")}], "travail_actif": ""},
            "modeles": {"choisis": {"polyvalent": "qwen3:8b", "code": "qwen2.5-coder:7b"}, "ignores": []}}), encoding="utf-8")
        for (ident, minutes), titre in zip((("a1b2c3d4", 2), ("b2c3d4e5", 95), ("c3d4e5f6", 1500)), DEMO[langue]["titres"]):
            (home / "donnees" / "conversations" / (ident + ".json")).write_text(json.dumps(conversation_demo(ident, titre, minutes, langue), ensure_ascii=False), encoding="utf-8")
        (home / "cache" / "bench.json").write_text(json.dumps({"qwen3:8b": {"modele": "qwen3:8b", "date": time.strftime("%Y-%m-%dT%H:%M:%S"), "machine": DEMO[langue]["machine"], "complet": True, "notes": {},
                                                                              "resultats": {"vitesse": {"tok_s": 54.2, "charge_s": 2.1}, "outils": {"points": 3, "sur": 3}, "code": {"points": 4, "sur": 4},
                                                                                            "francais": {"points": 2, "sur": 2}, "consignes": {"points": 1, "sur": 1}}}}), encoding="utf-8")
        (home / "cache" / "propositions.json").write_text(json.dumps({"date": time.time(), "erreurs": [], "catalogue": "absent", "propositions": [
            {"cle": "nouveau:code:qwen2.5-coder:14b", "type": "nouveau", "role": "code", "modele": "qwen2.5-coder:14b", "ancien": "qwen2.5-coder:7b", "go": 9,
             "phrase": DEMO[langue]["phrase"], "raison": DEMO[langue]["raison"]}]}), encoding="utf-8")
        serveur = subprocess.Popen([sys.executable, "-B", "-m", "lutin", "serve", "--sans-navigateur", "--sans-superviseur"], cwd=tempfile.gettempdir(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console = home / "donnees" / "console.json"
        debut = time.time()
        while time.time() - debut < 60 and not console.is_file():
            time.sleep(0.3)
        if not console.is_file():
            raise SystemExit("Le serveur de démonstration n'a pas démarré.")
        time.sleep(1.5)
        yield port, tmp
    finally:
        if serveur:
            serveur.terminate()
            try:
                serveur.wait(10)
            except subprocess.TimeoutExpired:
                serveur.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def principal(choix=None):
    """Les captures anglaises s'appellent capture-*.png (README.md), les françaises capture-*.fr.png (README.fr.md)."""
    chrome = navigateur(choix)
    ASSETS.mkdir(exist_ok=True)
    for langue, suffixe in (("en", ""), ("fr", ".fr")):
        with serveur_demo({"LUTIN_LANGUE": langue}) as (port, tmp):
            for base, ancre in (("capture-conversation", "#conv=a1b2c3d4"), ("capture-modeles", "#modeles")):
                nom = base + suffixe + ".png"
                profil = tmp / ("profil-" + nom)
                subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1", "--user-data-dir=" + str(profil), "--window-size=1280,800",
                                "--virtual-time-budget=8000", "--screenshot=" + str(ASSETS / nom), "http://127.0.0.1:%d/%s" % (port, ancre)], capture_output=True, timeout=120)
                print("✔ assets/" + nom if (ASSETS / nom).is_file() else "✘ " + nom)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    principal(sys.argv[1] if len(sys.argv) > 1 else None)
