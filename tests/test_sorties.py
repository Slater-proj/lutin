"""Ce qui sort de la machine : requêtes nettoyées avant un service extérieur, journal des envois, aperçu /web, SearXNG chez soi non concerné."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-sorties-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import core as A  # noqa: E402
from lutin import web_search, outbound, web  # noqa: E402


class Nettoyage(unittest.TestCase):
    def test_ce_qui_ne_doit_jamais_partir_est_retire(self):
        cas = [
            ("contacter jean.dupont@example.com pour devis", "adresse e-mail", "jean.dupont"),
            ("appeler 06 12 34 56 78 demain", "numéro de téléphone", "06 12"),
            ("appeler +33 6 12 34 56 78 demain", "numéro de téléphone", "+33"),
            ("clé sk-abcdefghijklmnop1234 ne marche pas", "clé ou jeton secret", "sk-abc"),
            ("carte 4111 1111 1111 1111 refusée", "numéro de carte bancaire", "4111"),
            ("virement FR76 3000 6000 0112 3456 7890 189 erreur", "IBAN", "FR76"),
            ("pourquoi 192.168.1.20 ne répond pas", "adresse du réseau local", "192.168"),
            ("erreur dans C:\\Users\\marie\\Documents\\x.txt", "chemin contenant un nom d'utilisateur", "marie"),
            ("fichier /home/marie/projet/app.py introuvable", "chemin contenant un nom d'utilisateur", "marie"),
            ("token 9f8e7d6c5b4a39281706f5e4d3c2b1a0aa bloqué", "clé ou jeton secret", "9f8e7d6c"),
        ]
        for texte, categorie, disparu in cas:
            propre, retire = outbound.clean_query(texte)
            self.assertIn(categorie, retire, texte)
            self.assertNotIn(disparu, propre, texte)

    def test_une_question_normale_n_est_pas_touchee(self):
        for texte in ("prix du kWh en France en 2026", "python 3.12.4 asyncio timeout", "version 10.2.1 de node", "date 12 03 2024 rapport", "numéro 4111 1111 1111 1112 invalide luhn", "iPhone 15 Pro Max 256 Go", "résultats du match 3-2 hier soir"):
            propre, retire = outbound.clean_query(texte)
            self.assertEqual((propre, retire), (texte, []), texte)

    def test_requete_toute_entiere_personnelle_devient_vide(self):
        self.assertEqual(outbound.clean_query("jean@example.com")[0], "")


class Journal(unittest.TestCase):
    def setUp(self):
        outbound.clear()

    def test_noter_lire_vider_et_borne(self):
        outbound.record("tavily", "une requête", ["adresse e-mail"], True)
        outbound.record("exa", "autre", [], False)
        e = outbound.read()
        self.assertEqual([(x["service"], x["ok"]) for x in e], [("exa", False), ("tavily", True)], "le plus récent d'abord")
        self.assertEqual(e[1]["retire"], ["adresse e-mail"])
        for i in range(outbound.MAX_ENTRIES + 80):
            outbound.record("duckduckgo", "q%d" % i, [], True)
        assert len(outbound.read(1000)) <= outbound.MAX_ENTRIES
        outbound.clear()
        self.assertEqual(outbound.read(), [])

    def test_un_journal_illisible_ne_plante_pas(self):
        outbound._path().write_text("pas du json\n{\"service\": \"x\"}\n", encoding="utf-8")
        self.assertEqual([x["service"] for x in outbound.read()], ["x"])

    def test_une_requete_tres_longue_est_coupee(self):
        outbound.record("bing", "x" * 5000)
        self.assertLessEqual(len(outbound.read()[0]["requete"]), 300)


class ChezSoi(unittest.TestCase):
    def test_searxng_local_n_est_pas_exterieur_les_autres_si(self):
        for adresse, attendu in (("http://127.0.0.1:8080", True), ("http://192.168.1.20:8080", True), ("http://searxng:8080", True), ("http://nas.local:8080", True),
                                 ("https://searx.exemple.org", False), ("http://8.8.8.8:8080", False)):
            with mock.patch.object(web_search, "allowed_host", lambda a=adresse: web_search.urllib.parse.urlparse(a).hostname):
                self.assertEqual(web_search.is_at_home("searxng"), attendu, adresse)
        for nom in ("brave", "tavily", "exa", "perplexity", "duckduckgo", "bing"):
            self.assertFalse(web_search.is_at_home(nom))


class RechercheEtJournal(unittest.TestCase):
    def setUp(self):
        outbound.clear()
        web.SEARCH_CACHE.clear()
        web.BLOCKED.clear()

    def test_le_service_exterieur_recoit_la_requete_nettoyee_et_l_envoi_est_note(self):
        recues = []

        def faux(requete):
            recues.append(requete)
            return [{"titre": "T", "url": "https://exemple.org/a", "extrait": "e", "date": ""}]
        with mock.patch.object(web, "engines_of_search", lambda: [("tavily", faux)]):
            trouves, raisons = web.search_results("aide pour jean@example.com sur le kWh", 5)
        self.assertEqual(recues, ["aide pour sur le kWh"])
        self.assertTrue(trouves)
        e = outbound.read()[0]
        self.assertEqual((e["service"], e["requete"], e["retire"], e["ok"]), ("tavily", "aide pour sur le kWh", ["adresse e-mail"], True))
        self.assertNotIn("jean@example.com", json.dumps(outbound.read()), "l'adresse n'est même pas dans le journal")

    def test_un_searxng_chez_soi_recoit_la_requete_telle_quelle_sans_journal(self):
        recues = []
        with mock.patch.object(web, "engines_of_search", lambda: [("searxng", lambda q: recues.append(q) or [{"titre": "T", "url": "https://exemple.org/b", "extrait": "e", "date": ""}])]), \
                mock.patch.object(web_search, "is_at_home", lambda nom: nom == "searxng"):
            web.search_results("contacter jean@example.com", 5)
        self.assertEqual(recues, ["contacter jean@example.com"])
        self.assertEqual(outbound.read(), [])

    def test_requete_entierement_personnelle_n_est_envoyee_nulle_part(self):
        appels = []
        with mock.patch.object(web, "engines_of_search", lambda: [("exa", lambda q: appels.append(q) or [])]):
            trouves, raisons = web.search_results("jean@example.com", 5)
        self.assertEqual((appels, trouves), ([], []))
        self.assertIn("données personnelles", " ".join(raisons))
        self.assertEqual(outbound.read(), [])

    def test_un_echec_est_note_aussi(self):
        def casse(requete):
            raise A.ToolError("HTTP 500")
        with mock.patch.object(web, "engines_of_search", lambda: [("perplexity", casse)]):
            web.search_results("question simple", 5)
        self.assertFalse(outbound.read()[0]["ok"])


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lutin import security as S
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.port = cls.serveur.server_address[1]
        cls.avant = A.SECURITY
        A.SECURITY = S.Security(niveau=S.LOCAL)

    @classmethod
    def tearDownClass(cls):
        A.SECURITY = cls.avant
        cls.serveur.shutdown()

    def appel(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": "127.0.0.1:%d" % self.port, "X-Token": A.TOKEN}
        donnees = json.dumps(corps).encode() if corps is not None else None
        if donnees:
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        texte = r.read().decode("utf-8")
        c.close()
        return r.status, json.loads(texte) if texte else {}

    def test_apercu_web_nettoie_et_ne_rend_que_des_resultats(self):
        outbound.clear()
        web.SEARCH_CACHE.clear()
        web.BLOCKED.clear()
        with mock.patch.object(web, "engines_of_search", lambda: [("tavily", lambda q: [{"titre": "T1", "url": "https://exemple.org/a?utm_source=x", "extrait": "e" * 500, "date": "2026-05-01"}])]):
            statut, r = self.appel("POST", "/api/v1/web-search/preview", {"q": "tarif électricité écrire à marie@example.com"})
        self.assertEqual(statut, 200)
        self.assertEqual(r["removed"], ["adresse e-mail"])
        self.assertEqual(r["query"], "tarif électricité écrire à")
        self.assertEqual((r["results"][0]["domain"], r["results"][0]["source"], len(r["results"][0]["extract"])), ("exemple.org", "tavily", 300))
        self.assertEqual(r["results"][0]["url"], "https://exemple.org/a")
        self.assertEqual(self.appel("POST", "/api/v1/web-search/preview", {"q": "x"})[0], 400)

    def test_journal_et_vidage_par_l_api(self):
        outbound.clear()
        outbound.record("bing", "une question", [], True)
        statut, r = self.appel("GET", "/api/v1/health/outbound")
        self.assertEqual((statut, r["entries"][0]["service"]), (200, "bing"))
        self.assertEqual(self.appel("DELETE", "/api/v1/health/outbound")[0], 200)
        self.assertEqual(self.appel("GET", "/api/v1/health/outbound")[1]["entries"], [])


if __name__ == "__main__":
    unittest.main()
