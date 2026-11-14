"""Suite de conformité commune : la MÊME série de vérifications est jouée sur chaque adaptateur de moteur (Ollama, llama.cpp, serveur externe) contre un faux serveur.

Chaque moteur déclare une grille de capacités (natif / adapté / non / non testé). Cette suite vérifie chaque case « natif » ou « adapté » : la grille ne peut pas promettre ce que l'adaptateur ne sait pas faire.
Les cases qui ne se vérifient pas avec un simple faux serveur (plusieurs modèles, téléchargement, installation) sont listées dans VERIFIE_AILLEURS, avec le test qui s'en charge."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-conformite-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engines  # noqa: E402

PNG = "iVBORw0KGgo="
EVENEMENTS = {"ferme": threading.Event(), "dernier": {}}
USER = [{"role": "user", "content": "Salut"}]
HEURE = [{"type": "function", "function": {"name": "heure", "description": "L'heure", "parameters": {"type": "object", "properties": {}}}}]
# Ce qui n'est pas vérifiable avec un faux serveur seul : le test qui le vérifie à la place.
VERIFIE_AILLEURS = {"plusieurs_modeles": "test_moteur_llamacpp.py (mode routeur)", "telechargement": "test_registre_ollama.py et test_ollama_partage.py", "installation": "test_moteur_llamacpp.py (installation)"}


class FauxOpenAI(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, o, code=200):
        d = json.dumps(o).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        self._json({"status": "ok"} if self.path.endswith("/health") else {"data": [{"id": "modele-test"}]})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        EVENEMENTS["dernier"] = corps
        if self.path.endswith("/embeddings"):
            return self._json({"data": [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(corps["input"])]})
        dernier = corps["messages"][-1]
        if dernier.get("content") == "LONG":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b'data: {"choices":[{"delta":{"content":"mot "}}]}\n\n')
                    self.wfile.flush()
                    time.sleep(0.05)
            except OSError:
                EVENEMENTS["ferme"].set()
            return
        appel = bool(corps.get("tools")) and dernier["role"] == "user"
        if not corps.get("stream"):
            return self._json({"choices": [{"message": {"content": "réponse complète", "reasoning_content": "je réfléchis"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if appel:
            morceaux = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "heure", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}]
        else:
            morceaux = [{"choices": [{"delta": {"reasoning_content": "je réfléchis"}}]}] + [{"choices": [{"delta": {"content": mot + " "}}]} for mot in "réponse du flux".split()]
        for m in morceaux + [{"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 6}}]:
            self.wfile.write(("data: " + json.dumps(m) + "\n\n").encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FauxOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, o, code=200):
        d = json.dumps(o).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json({"models": [{"name": "modele-test", "size": 1000}]})
        if self.path.startswith("/api/ps"):
            return self._json({"models": []})
        self._json({"version": "0.0-test"})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        EVENEMENTS["dernier"] = corps
        if self.path == "/api/embed":
            return self._json({"embeddings": [[float(len(t)), 1.0] for t in corps["input"]]})
        dernier = corps["messages"][-1]
        if not corps.get("stream", True):
            return self._json({"message": {"role": "assistant", "content": "réponse complète", "thinking": "je réfléchis"}, "done": True})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            if dernier.get("content") == "LONG":
                for _ in range(200):
                    self.wfile.write((json.dumps({"message": {"role": "assistant", "content": "mot "}, "done": False}) + "\n").encode())
                    self.wfile.flush()
                    time.sleep(0.05)
                return
            if corps.get("tools") and dernier["role"] == "user":
                lignes = [{"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "heure", "arguments": {}}}]}, "done": False}]
            else:
                lignes = [{"message": {"role": "assistant", "thinking": "je réfléchis"}, "done": False}] + [{"message": {"role": "assistant", "content": mot + " "}, "done": False} for mot in "réponse du flux".split()]
            for ligne in lignes + [{"done": True, "done_reason": "stop", "eval_count": 6, "prompt_eval_count": 5}]:
                self.wfile.write((json.dumps(ligne) + "\n").encode())
                self.wfile.flush()
        except OSError:
            EVENEMENTS["ferme"].set()


def serveur(classe):
    s = ThreadingHTTPServer(("127.0.0.1", 0), classe)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


class Conformite:
    """Les vérifications communes. Chaque sous-classe fournit `moteur` (l'adaptateur) et `modele`."""
    moteur = None
    modele = "modele-test"

    def corps(self, messages=USER, **plus):
        return dict({"model": self.modele, "messages": messages, "options": {}}, **plus)

    def flux(self, corps, stop=None):
        with engines.FluxInterruptible(lambda: self.moteur.chat_flux(corps), stop or threading.Event()) as f:
            return list(f)

    def verifier_discuter(self):
        rep = self.moteur.chat(self.corps(stream=False))
        self.assertIn("réponse", rep["message"]["content"])

    def verifier_flux(self):
        evenements = self.flux(self.corps())
        self.assertEqual("".join((e.get("message") or {}).get("content", "") for e in evenements).strip(), "réponse du flux")
        self.assertTrue(evenements[-1].get("done"), "le dernier évènement annonce la fin")

    def verifier_outils(self):
        evenements = self.flux(self.corps(tools=HEURE))
        appels = [a for e in evenements for a in (e.get("message") or {}).get("tool_calls", [])]
        self.assertEqual([a["function"]["name"] for a in appels], ["heure"])
        self.assertIsInstance(appels[0]["function"]["arguments"], dict)
        self.assertIn("tools", EVENEMENTS["dernier"])

    def verifier_reflexion(self):
        evenements = self.flux(self.corps())
        self.assertIn("je réfléchis", "".join((e.get("message") or {}).get("thinking", "") for e in evenements))

    def verifier_vision(self):
        self.flux(self.corps([{"role": "user", "content": "Décris", "images": [PNG]}]))
        envoye = json.dumps(EVENEMENTS["dernier"])
        self.assertIn(PNG, envoye, "l'image est bien transmise au serveur")

    def verifier_embeddings(self):
        v = self.moteur.vecteurs(self.modele, ["a", "bbb"])
        self.assertEqual(len(v), 2)
        self.assertEqual([x[0] for x in v], [1.0, 3.0])

    def verifier_arret(self):
        """Comme le fait la conversation : à chaque évènement on regarde le bouton Arrêter, et quitter le flux coupe la connexion."""
        EVENEMENTS["ferme"].clear()
        stop = threading.Event()
        threading.Timer(0.4, stop.set).start()
        debut = time.time()
        lus = 0
        with engines.FluxInterruptible(lambda: self.moteur.chat_flux(self.corps([{"role": "user", "content": "LONG"}])), stop) as f:
            for e in f:
                lus += 1
                if stop.is_set():
                    break
        self.assertGreater(lus, 0)
        self.assertLess(time.time() - debut, 4)
        self.assertTrue(EVENEMENTS["ferme"].wait(4), "le serveur voit la connexion se fermer : il arrête de générer")

    def verifier_liste(self):
        m = self.moteur.modeles()
        self.assertTrue(m["actif"])
        self.assertIn(self.modele, m["installes"])

    def test_la_grille_est_complete_et_honnete(self):
        g = self.moteur.grille()
        self.assertEqual(set(g), set(engines.FONCTIONS))
        for f, (etat, note) in g.items():
            self.assertIn(etat, engines.ETATS, f)
        vue = {x["fonction"]: x for x in self.moteur.vue()["grille"]}
        self.assertEqual(list(vue), list(engines.FONCTIONS))
        self.verifier_liste()
        for f, (etat, note) in g.items():
            if etat not in ("natif", "adapte"):
                continue
            if f in VERIFIE_AILLEURS:
                continue
            with self.subTest(fonction=f, etat=etat):
                verif = getattr(self, "verifier_" + f, None)
                self.assertIsNotNone(verif, "{} : « {} » est déclaré {} mais aucune vérification ne le couvre".format(self.moteur.id, f, etat))
                verif()

    def test_une_fonction_non_declaree_ne_ment_pas(self):
        """Une fonction « non » ou « non_teste » n'est jamais présentée comme acquise : la note l'explique ou l'état le dit."""
        for f, (etat, note) in self.moteur.grille().items():
            if etat in ("non", "non_teste"):
                self.assertTrue(note, "{} : {} sans explication".format(f, etat))


class OllamaAdaptateur(Conformite, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = serveur(FauxOllama)
        cls.ancien = _m.OLLAMA
        _m.OLLAMA = "http://127.0.0.1:%d" % cls.s.server_address[1]
        cls.moteur = engines.MOTEURS["ollama"]

    @classmethod
    def tearDownClass(cls):
        _m.OLLAMA = cls.ancien
        cls.s.shutdown()


class OpenAIBase(Conformite):
    id = ""

    @classmethod
    def setUpClass(cls):
        cls.s = serveur(FauxOpenAI)
        cls.ancien = dict(engines.CONTEXTE)
        cls.dossier = Path(tempfile.mkdtemp(dir=_TEMP))
        engines.CONTEXTE.update(donnees=lambda: cls.dossier, en_docker=lambda: False, hors_ligne=lambda: False)
        ml.regler(cls.id, adresse="http://127.0.0.1:%d" % cls.s.server_address[1])
        cls.moteur = engines.MOTEURS[cls.id]

    @classmethod
    def tearDownClass(cls):
        engines.CONTEXTE.update(cls.ancien)
        cls.s.shutdown()


class LlamaCppAdaptateur(OpenAIBase, unittest.TestCase):
    id = "llamacpp"          # joint à une adresse : c'est l'adaptateur OpenAI de llama.cpp, sans programme à lancer


class ServeurExterneAdaptateur(OpenAIBase, unittest.TestCase):
    id = "openai"


class Garde(unittest.TestCase):
    def test_trois_adaptateurs_et_chaque_fonction_declaree_est_couverte(self):
        self.assertEqual({"ollama", "llamacpp", "openai"} <= set(engines.MOTEURS), True)
        for ident in ("ollama", "llamacpp", "openai"):
            for f in engines.FONCTIONS:
                etat = engines.MOTEURS[ident].grille()[f][0]
                if etat in ("natif", "adapte") and f not in VERIFIE_AILLEURS:
                    self.assertTrue(hasattr(Conformite, "verifier_" + f), "{} : aucune vérification pour « {} »".format(ident, f))


if __name__ == "__main__":
    unittest.main()
