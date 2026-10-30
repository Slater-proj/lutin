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
# Routes exclues : elles agissent vraiment sur la machine ou sur d'autres données que celles du serveur de test.
EXCLUES = ("arreter", "redemarrer", "mettre-a-jour", "installer", "ollama", "supprimer-modele", "oublier-modele", "bench", "autotest", "liberer-vram", "hors-ligne", "importer-claude", "reprise",
           "commande-claude", "git", "acces", "dossier-modeles", "deplacer", "modeles-restaurer", "verifier-lutin", "langue", "projet-claude", "decouvrir", "propositions", "qr", "nouveau-pin")
CLES = ("id", "conversation", "chemin", "nom", "texte", "mode", "modele", "message", "requete", "fichier", "fichiers", "dossier", "action", "pin", "url", "titre", "liste", "epingle", "choix", "garder",
        "reglages", "flux", "brouillon", "publication", "quand", "brief", "motifs", "consigne", "regulier", "intervalle_h", "actif", "section", "ok", "images", "pieces", "travail", "remplacer_depuis", "note",
        "heure", "jours", "prompt", "commande", "ancien", "nouveau", "contenu", "debut", "fin", "motif", "images", "version")


def routes():
    source = (SRC / "lutin" / "serveur.py").read_text(encoding="utf-8")
    trouvees = sorted(set(re.findall(r'"(/api/[a-z0-9-]+)"', source)))
    return [r for r in trouvees if not any(x in r for x in EXCLUES)]


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

    def appeler(self, chemin, corps=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, chemin), data=corps, method="POST" if corps is not None else "GET",
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
        self.assertGreater(len(liste), 60, "les routes du serveur sont bien trouvées")
        fautes = []
        for chemin in liste:
            for corps in [None] + list(variantes()):
                code = self.appeler(chemin, corps)
                if code == 0 or (code >= 500 and code != 503):
                    fautes.append((chemin, code, (corps or b"")[:60]))
        resume = sorted({(c, code) for c, code, _ in fautes})
        self.assertEqual(resume, [], "%d requête(s) absurde(s) ont donné une erreur interne ou coupé la connexion" % len(fautes))
        self.assertEqual(self.appeler("/api/etat"), 200, "le serveur répond toujours après toutes ces requêtes")

    def test_chemins_et_requetes_hors_norme(self):
        for chemin in ("/", "/api", "/api/", "/api/inconnue", "/..%2f..%2fetc/passwd", "/api/etat?a=" + "b" * 20000, "/%00", "/api/conversation?id=" + "x" * 5000, "/api/suivi?conversation=../../x",
                       "/api/fond-rapport?id=../../x", "/api/addon-etat?id=../../x", "/api/addon-flux?id=%00"):
            code = self.appeler(chemin)
            self.assertLess(code, 500, chemin[:60])
        self.assertEqual(self.appeler("/api/etat"), 200)


if __name__ == "__main__":
    unittest.main()
