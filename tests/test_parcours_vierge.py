"""Parcours d'une installation vierge (aucune donnée, aucun moteur qui répond) : aucune page ne plante, aucune route de lecture ne renvoie d'erreur 5xx,
et la page principale se charge. C'est le filet de la stabilisation : une régression qui casse un écran au premier lancement se voit ici."""
import gzip
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-vierge-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]

# Routes de lecture sans effet de bord ni accès au réseau extérieur (on exclut la découverte du réseau, la recherche web, la mise à jour en ligne).
LECTURES = ["/api/etat", "/api/acces", "/api/addons", "/api/conseil", "/api/contexte", "/api/documents", "/api/dossiers", "/api/emplacements",
            "/api/fichiers-crees", "/api/journal", "/api/machines", "/api/mcp", "/api/memoire", "/api/missions", "/api/moteurs", "/api/notes",
            "/api/planifie", "/api/propositions", "/api/ressources", "/api/sante-systeme", "/api/skills", "/api/suivi", "/api/travaux", "/api/variantes",
            "/api/estimation?modele=qwen3:8b", "/api/bench-moteurs"]


def lire(chemin):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request("GET", chemin, headers={"Host": "127.0.0.1:%d" % PORT, "X-Token": A.JETON})
    r = c.getresponse()
    corps = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, corps


class ParcoursVierge(unittest.TestCase):
    def test_page_principale_se_charge(self):
        statut, corps = lire("/")
        self.assertEqual(statut, 200)
        self.assertIn("<html", corps.lower())

    def test_aucune_route_de_lecture_ne_plante(self):
        for chemin in LECTURES:
            with self.subTest(chemin=chemin):
                statut, corps = lire(chemin)
                self.assertLess(statut, 500, (chemin, corps[:300]))
                self.assertNotEqual(statut, 403, chemin)          # le jeton est envoyé : un refus ici cacherait un plantage
                json.loads(corps)          # toujours du JSON lisible, même en cas de refus

    def test_etat_vierge_explique_le_premier_lancement(self):
        statut, corps = lire("/api/etat")
        self.assertEqual(statut, 200)
        etat = json.loads(corps)
        self.assertIn("premier_lancement", etat)          # sans moteur, la page doit pouvoir dire quoi faire

    def test_route_inconnue_est_un_404_propre(self):
        statut, corps = lire("/api/cette-route-n-existe-pas")
        self.assertEqual(statut, 404)

    def test_chemins_hors_dossier_refuses(self):
        for chemin in ("/fichier/../../../etc/passwd", "/lib/../serveur.py", "/image/..%2f..%2fsecret", "/piece/%2e%2e/%2e%2e/x"):
            with self.subTest(chemin=chemin):
                statut, corps = lire(chemin)
                self.assertIn(statut, (400, 403, 404), chemin)
                self.assertNotIn("root:", corps)


class DonneesAbimees(unittest.TestCase):
    """Un fichier de données coupé en deux (coupure de courant), vide, d'un autre type (ancienne version, édition à la main) ne doit jamais empêcher l'application de répondre."""
    FICHIERS = {"reglages.json": ("/api/etat",), "noeud.json": ("/api/machines", "/api/noeud/etat"), "machines.json": ("/api/machines",)}          # fichier -> routes qui le lisent
    CONTENUS = ["{", "[]", "null", '"texte"', '{"moteur": 3, "machine": [], "jetons": "x", "extinction": {}}']

    def tearDown(self):
        for f in self.FICHIERS:
            (A.DONNEES / f).unlink(missing_ok=True)

    def test_fichiers_abimes(self):
        for fichier in self.FICHIERS:
            for contenu in self.CONTENUS:
                (A.DONNEES / fichier).write_text(contenu, encoding="utf-8")
                for chemin in self.FICHIERS[fichier]:
                    with self.subTest(fichier=fichier, contenu=contenu, chemin=chemin):
                        statut, corps = lire(chemin)
                        self.assertLess(statut, 500, corps[:300])


class Compression(unittest.TestCase):
    def demander(self, chemin, encodage=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        en_tetes = {"Host": "127.0.0.1:%d" % PORT, "X-Token": A.JETON}
        if encodage:
            en_tetes["Accept-Encoding"] = encodage
        c.request("GET", chemin, headers=en_tetes)
        r = c.getresponse()
        corps = r.read()
        c.close()
        return r, corps

    def test_la_page_est_compressee_seulement_si_le_navigateur_le_demande(self):
        r_brut, brut = self.demander("/")
        self.assertIsNone(r_brut.getheader("Content-Encoding"))
        r_gz, comprime = self.demander("/", "gzip, deflate, br")
        self.assertEqual(r_gz.getheader("Content-Encoding"), "gzip")
        self.assertEqual(r_gz.getheader("Vary"), "Accept-Encoding")
        self.assertEqual(int(r_gz.getheader("Content-Length")), len(comprime))
        self.assertEqual(gzip.decompress(comprime), brut, "le contenu est identique")
        self.assertLess(len(comprime), len(brut) / 2)

    def test_une_petite_reponse_n_est_pas_compressee(self):
        r, corps = self.demander("/api/journal", "gzip")          # vide sur une installation vierge : quelques octets
        self.assertLess(len(corps), 1400)
        self.assertIsNone(r.getheader("Content-Encoding"), "trop petite : la compression ne gagnerait rien")
        json.loads(corps)

    def test_l_etat_compresse_reste_du_json_valide(self):
        r, corps = self.demander("/api/etat", "gzip")
        donnees = gzip.decompress(corps) if r.getheader("Content-Encoding") == "gzip" else corps
        self.assertIn("version", json.loads(donnees))


if __name__ == "__main__":
    unittest.main()
