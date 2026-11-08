"""Recherche web : Tavily, Exa et Perplexity (clé personnelle). Seuls les RÉSULTATS sont repris (le modèle de Lutin répond lui-même), la clé n'est jamais renvoyée, l'ordre d'essai est respecté."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-fournisseurs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

RECUES = []
REPONSES = {
    "/tavily/search": {"answer": "RÉPONSE TOUTE FAITE À IGNORER", "results": [{"title": "T1", "url": "https://exemple.org/a?utm_source=x", "content": "extrait tavily", "published_date": "2026-05-02"}, {"title": "sans adresse"}]},
    "/exa/search": {"results": [{"title": "E1", "url": "https://exemple.net/b", "text": "  extrait   exa\n sur deux lignes ", "publishedDate": "2026-04-30T10:00:00.000Z"}]},
    "/perplexity/search": {"results": [{"title": "P1", "url": "https://exemple.com/c", "snippet": "extrait perplexity", "date": "2026-05-01"}], "id": "x"},
}


class Faux(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        RECUES.append((self.path, {k.lower(): v for k, v in self.headers.items()}, corps))
        d = json.dumps(REPONSES.get(self.path, {})).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)


SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % SERVEUR.server_address[1]
os.environ["LUTIN_TAVILY_URL"] = BASE + "/tavily"          # avant l'import de lutin.recherche
os.environ["LUTIN_EXA_URL"] = BASE + "/exa"
os.environ["LUTIN_PERPLEXITY_URL"] = BASE + "/perplexity"

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import recherche, web  # noqa: E402


class Fournisseurs(unittest.TestCase):
    def setUp(self):
        RECUES.clear()
        c = _m.DONNEES / "recherche.json"
        c.unlink(missing_ok=True)
        recherche.ACTUELLES.v = {}
        self.addCleanup(setattr, recherche.ACTUELLES, "v", {})

    def test_les_cles_ne_sont_jamais_renvoyees(self):
        v = recherche.enregistrer(tavily_cle="tvly-abcdefghij1234", exa_cle="exa-key-1234567890", perplexity_cle="pplx-abcdefghij5678")
        self.assertTrue(v["tavily"] and v["exa"] and v["perplexity"])
        self.assertEqual((v["tavily_fin"], v["exa_fin"], v["perplexity_fin"]), ("1234", "7890", "5678"))
        self.assertNotIn("tvly-abcdefghij1234", json.dumps(v))
        v = recherche.enregistrer(exa_cle="")
        self.assertFalse(v["exa"])
        self.assertTrue(v["tavily"], "retirer une clé ne touche pas les autres")

    def test_cle_invalide_refusee(self):
        for nom in ("tavily_cle", "exa_cle", "perplexity_cle"):
            with self.assertRaises(ValueError):
                recherche.enregistrer(**{nom: "pas de espaces ni é"})

    def test_ordre_d_essai(self):
        recherche.enregistrer(tavily_cle="tvly-abcdefghij1234", exa_cle="exa-key-1234567890", perplexity_cle="pplx-abcdefghij5678", brave_cle="BSAbravekey12345")
        self.assertEqual([n for n, _ in recherche.fournisseurs_configures()], ["brave", "tavily", "exa", "perplexity"])
        self.assertEqual([n for n, _ in web.moteurs_de_recherche()][-2:], ["duckduckgo", "bing"], "les moteurs sans clé restent le dernier recours")
        etat = {e["nom"]: e["configure"] for e in web.etat_moteurs()}
        self.assertTrue(etat["tavily"] and etat["exa"] and etat["perplexity"] and not etat["duckduckgo"])

    def test_tavily_garde_les_resultats_et_ignore_la_reponse_toute_faite(self):
        recherche.enregistrer(tavily_cle="tvly-abcdefghij1234")
        recherche.ACTUELLES.v = {"periode": "semaine", "actualites": True}
        r = recherche.resultats_tavily("lutin assistant")
        self.assertEqual(r, [{"titre": "T1", "url": "https://exemple.org/a?utm_source=x", "extrait": "extrait tavily", "date": "2026-05-02"}])
        chemin, tetes, corps = RECUES[0]
        self.assertEqual(chemin, "/tavily/search")
        self.assertEqual(tetes["authorization"], "Bearer tvly-abcdefghij1234")
        self.assertEqual((corps["time_range"], corps["topic"], corps["include_answer"]), ("week", "news", False))
        self.assertNotIn("RÉPONSE TOUTE FAITE", json.dumps(r))

    def test_exa(self):
        recherche.enregistrer(exa_cle="exa-key-1234567890")
        recherche.ACTUELLES.v = {"periode": "jour"}
        r = recherche.resultats_exa("question précise")
        self.assertEqual((r[0]["titre"], r[0]["extrait"], r[0]["date"]), ("E1", "extrait exa sur deux lignes", "2026-04-30"))
        chemin, tetes, corps = RECUES[0]
        self.assertEqual(tetes["x-api-key"], "exa-key-1234567890")
        self.assertIn("startPublishedDate", corps)
        self.assertEqual(corps["contents"]["text"]["maxCharacters"], 600)

    def test_perplexity_api_de_recherche_pas_de_reponse_redigee(self):
        recherche.enregistrer(perplexity_cle="pplx-abcdefghij5678")
        recherche.ACTUELLES.v = {"periode": "mois", "site": "exemple.com"}
        r = recherche.resultats_perplexity("actualité")
        self.assertEqual((r[0]["titre"], r[0]["extrait"]), ("P1", "extrait perplexity"))
        chemin, tetes, corps = RECUES[0]
        self.assertEqual(chemin, "/perplexity/search")
        self.assertEqual(tetes["authorization"], "Bearer pplx-abcdefghij5678")
        self.assertEqual(corps["search_recency_filter"], "month")
        self.assertIn("site:exemple.com", corps["query"])
        self.assertNotIn("messages", corps, "aucun modèle de chat n'est appelé : seulement la recherche")

    def test_sans_cle_une_erreur_claire(self):
        for f in (recherche.resultats_tavily, recherche.resultats_exa, recherche.resultats_perplexity):
            with self.assertRaises(_m.ErreurOutil) as e:
                f("x")
            self.assertIn("clé", str(e.exception).lower())

    def test_recherche_complete_passe_par_le_fournisseur_et_le_nettoie(self):
        recherche.enregistrer(tavily_cle="tvly-abcdefghij1234")
        web.CACHE_RECHERCHE.clear()
        web.BLOQUES.clear()
        trouves, raisons = web.chercher_resultats("lutin assistant local", 5)
        self.assertEqual(trouves[0]["source"], "tavily")
        self.assertEqual(trouves[0]["url"], "https://exemple.org/a", "l'adresse est nettoyée de son suivi")


if __name__ == "__main__":
    unittest.main()
