"""Robustesse du serveur : des requêtes absurdes sur chaque route (JSON invalide, types inattendus, textes énormes, chemins piégés) ne doivent jamais donner d'erreur interne (500) ni faire tomber le serveur.

C'est un vrai serveur Lutin dans un dossier temporaire (voir tools/captures.py). Les routes qui agissent sur la machine (arrêt, redémarrage, mise à jour, installation de modèles, niveau d'accès, dossier des modèles…)
sont exclues : on teste la solidité de l'analyse des requêtes, pas ces actions."""
import http.client
import json
import re
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import context  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
SRC = RACINE / "src"
# Routes exclues : elles agissent vraiment sur la machine, sur Internet ou sur d'autres données que celles du serveur de test.
EXCLUES = ("/access", "/lutin/update", "/lutin/restart", "/lutin/check", "/lutin/startup", "/offline", "/actions/", "/install", "/helper-programs", "/models/folder", "/models/check",
           "/models/library", "/models/variants", "/bench", "/speed-test", "/calibration", "/self-test", "/unload", "/free-graphics-memory", "/takeover", "/import-claude", "/git",
           "/web-search/test", "/move", "/language", "/third-party-skills", "/backup/restore", "/engines/comparison", "/measure", "/run", "/node/shutdown", "/machines/",
           "/search-by-meaning", "/github", "/models/proposals", "/models/recommendation", "/engines/x/models", "/devices", "/node/pairing-code")
CLES = ("id", "conversation", "chemin", "nom", "texte", "mode", "modele", "message", "requete", "fichier", "fichiers", "dossier", "action", "pin", "url", "titre", "liste", "epingle", "choix", "garder",
        "reglages", "flux", "brouillon", "publication", "quand", "brief", "motifs", "consigne", "regulier", "intervalle_h", "actif", "section", "ok", "images", "pieces", "travail", "remplacer_depuis", "note",
        "heure", "jours", "prompt", "commande", "ancien", "nouveau", "contenu", "debut", "fin", "motif", "images", "version")


def routes():
    """Every route of /api/v1 (its table, lutin.api_v1.ROUTES), its parameters filled with « x », but those of EXCLUES; and the models, deleted, kept out
    (DELETE /models/x would ask the engine)."""
    sys.path.insert(0, str(SRC))
    from lutin import api_v1
    trouvees = sorted({(r["method"], re.sub(r"\{[a-z_]+\}", "x", r["path"])) for r in api_v1.table()})
    return [(m, r) for m, r in trouvees if not any(x in r for x in EXCLUES) and not (m in ("POST", "DELETE") and r in ("/api/v1/models", "/api/v1/models/x"))]


def variantes():
    """Les corps de requête absurdes : chaque clé connue reçoit une valeur d'un type inattendu."""
    for valeur in (None, 123, -1, 3.5, True, "x" * 5000, "../../../etc/passwd", "C:\\Windows\\System32", "\x00\x01", ["a", 1], {"a": {"b": []}}, "é" * 300):
        yield json.dumps({c: valeur for c in CLES}).encode("utf-8")
    yield b"{}"
    yield b"[1, 2, 3]"
    yield b"null"
    yield b'"texte"'
    yield b"{pas du json"
    yield b""
    yield json.dumps({"message": "x" * 70000, "conversation": "x" * 200}).encode("utf-8")
    yield ("[" * 3000 + "]" * 3000).encode("utf-8")


class Robustesse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.contexte = captures.serveur_demo()
        cls.port, cls.tmp = cls.contexte.__enter__()
        cls.jeton = json.loads((cls.tmp / "home" / "donnees" / "console.json").read_text(encoding="utf-8"))["jeton"]

    @classmethod
    def tearDownClass(cls):
        cls.contexte.__exit__(None, None, None)

    def appeler(self, chemin, corps=None, methode=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, chemin), data=corps, method=methode or ("POST" if corps is not None else "GET"),
                                     headers={"Content-Type": "application/json", "X-Token": self.jeton})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read(200000)
                return r.status
        except urllib.error.HTTPError as e:
            e.read()
            return e.code
        except (http.client.HTTPException, OSError):
            return 0                                          # connexion coupée sans réponse

    def test_aucune_route_ne_donne_d_erreur_interne(self):
        liste = routes()
        self.assertGreater(len(liste), 120, "les routes du serveur sont bien trouvées")
        fautes = []
        for methode, chemin in liste:
            for corps in [None] if methode == "GET" else list(variantes()):
                code = self.appeler(chemin, corps, methode)
                if code == 0 or (code >= 500 and code != 503):
                    fautes.append((methode, chemin, code, (corps or b"")[:60]))
        resume = sorted({(m, c, code) for m, c, code, _ in fautes})
        self.assertEqual(resume, [], "%d requête(s) absurde(s) ont donné une erreur interne ou coupé la connexion" % len(fautes))
        self.assertEqual(self.appeler("/api/v1/status"), 200, "le serveur répond toujours après toutes ces requêtes")

    def test_chemins_et_requetes_hors_norme(self):
        for chemin in ("/", "/api", "/api/", "/api/inconnue", "/api/v1/", "/api/v1/inconnue", "/..%2f..%2fetc/passwd", "/api/v1/status?a=" + "b" * 20000, "/%00", "/api/v1/conversations/" + "x" * 5000,
                       "/api/v1/conversations/..%2f..%2fx/memory", "/api/v1/background-jobs/..%2f..%2fx/report", "/api/v1/addons/..%2f..%2fx/panel", "/api/v1/addons/%00/flow",
                       "/api/conversation?id=" + "x" * 5000, "/image/..%2f..%2fx", "/fichier/x/..%2f..%2fx"):
            code = self.appeler(chemin)
            self.assertLess(code, 500, chemin[:60])
        self.assertEqual(self.appeler("/api/v1/status"), 200)


if __name__ == "__main__":
    unittest.main()
