"""Recherche web complète : SearXNG et Brave (faux serveurs locaux), options (période, site, actualités, langue), nettoyage des résultats, exception d'hôte très étroite, lecture des PDF, liens, cache, reprise, charset,
configuration sans fuite de la clé. Aucun accès à Internet ; LUTIN_WEB_LOCAL n'est PAS posé : les adresses locales restent refusées, sauf celle de SearXNG."""
import http.client
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-recherche-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)
os.environ.pop("LUTIN_WEB_LOCAL", None)
os.environ.pop("LUTIN_RECHERCHE_URL", None)

RECU = []          # (serveur, chemin, en-têtes) des demandes reçues
ETAT = {"searxng": "json", "page503": 1}


def lancer(classe):
    s = ThreadingHTTPServer(("127.0.0.1", 0), classe)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


class FauxSearxng(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        RECU.append(("searxng", self.path, dict(self.headers)))
        if ETAT["searxng"] == "html":
            corps, type_ = b"<html>pas de json</html>", "text/html"
        else:
            corps = json.dumps({"results": [
                {"title": "Docs officielles", "url": "https://docs.exemple.org/guide?utm_source=x&id=3#haut", "content": "Le guide <b>complet</b>", "publishedDate": "2026-10-30T08:00:00"},
                {"title": "Doublon", "url": "https://www.docs.exemple.org/guide/?id=3", "content": "même page"},
                {"title": "Blog", "url": "https://blog.exemple.net/a", "content": "un billet"},
                {"title": "Blog 2", "url": "https://blog.exemple.net/b", "content": "un autre"},
                {"title": "Blog 3", "url": "https://blog.exemple.net/c", "content": "encore un"},
                {"title": "Dangereux", "url": "javascript:alert(1)", "content": "x"},
            ]}).encode()
            type_ = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


class FauxBrave(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        RECU.append(("brave", self.path, dict(self.headers)))
        if self.headers.get("X-Subscription-Token") != "cle-brave-123456":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if "/news/" in self.path:
            donnees = {"results": [{"title": "Une dépêche", "url": "https://presse.exemple.fr/n1", "description": "<strong>Dernière</strong> minute", "age": "2 hours ago"}]}
        else:
            donnees = {"web": {"results": [{"title": "Résultat Brave", "url": "https://brave-site.exemple.org/x", "description": "un <strong>extrait</strong>", "age": "3 days ago"}]}}
        corps = json.dumps(donnees).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


PAGE_ARTICLE = ("<html><head><title>Article</title><meta charset='iso-8859-1'></head><body><nav><a href='/menu'>Menu du site</a></nav>"
                "<article><h1>Le titre</h1><p>Un long paragraphe de contenu utile, écrit pour dépasser le seuil de page vide et pour prouver que le menu est ignoré : " + "mot " * 60 + "</p>"
                "<a href='/suite'>La suite</a> <a href='https://autre.exemple.org/x'>Ailleurs</a> <a href='#haut'>haut</a></article><footer>Mentions légales du pied</footer></body></html>")
PAGE_NAV_SEULE = "<html><body><nav>Un contenu qui n'existe que dans une balise nav, assez long pour compter : " + "texte " * 50 + "</nav></body></html>"


class FauxPages(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, type_, corps, code=200):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        RECU.append(("pages", self.path, {}))
        if self.path == "/article":
            return self._rep("text/html", PAGE_ARTICLE.encode("iso-8859-1", "replace"))
        if self.path == "/navseule":
            return self._rep("text/html; charset=utf-8", PAGE_NAV_SEULE.encode("utf-8"))
        if self.path == "/fragile":
            if ETAT["page503"] > 0:
                ETAT["page503"] -= 1
                return self._rep("text/plain", b"occupe", 503)
            return self._rep("text/plain; charset=utf-8", "Enfin disponible, voici le texte.".encode("utf-8"))
        if self.path == "/doc.pdf":
            from test_extraction import pdf_simple
            return self._rep("application/pdf", pdf_simple())
        if self.path == "/sansextension":
            from test_extraction import pdf_simple
            return self._rep("application/pdf", pdf_simple(True))
        if self.path == "/long":
            return self._rep("text/plain; charset=utf-8", "".join("ligne %04d\n" % i for i in range(1500)).encode())
        self._rep("text/plain", b"", 404)


S_SX, S_BR, S_PG = lancer(FauxSearxng), lancer(FauxBrave), lancer(FauxPages)
URL_SX = "http://127.0.0.1:%d" % S_SX.server_address[1]
URL_BR = "http://127.0.0.1:%d/res/v1/" % S_BR.server_address[1]
URL_PG = "http://127.0.0.1:%d" % S_PG.server_address[1]
os.environ["LUTIN_BRAVE_URL"] = URL_BR          # avant l'import de lutin.recherche

from lutin import moteur as A  # noqa: E402
from lutin import recherche, web  # noqa: E402


def derniere(nom):
    return [r for r in RECU if r[0] == nom][-1]


def requete_de(chemin):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(chemin).query)


class Base(unittest.TestCase):
    def setUp(self):
        del RECU[:]
        ETAT.update(searxng="json", page503=1)
        recherche.enregistrer("", "")
        web.CACHE_RECHERCHE.clear()
        web.CACHE_PAGES.clear()
        web.BLOQUES.clear()

    def tearDown(self):
        recherche.enregistrer("", "")
        recherche.ACTUELLES.v = {}


class Configuration(Base):
    def test_adresse_de_searxng_validee_et_normalisee(self):
        self.assertEqual(recherche.normaliser_adresse("127.0.0.1:8080/"), "http://127.0.0.1:8080")
        self.assertEqual(recherche.normaliser_adresse("https://sx.exemple.org/moteur/"), "https://sx.exemple.org/moteur")
        self.assertEqual(recherche.normaliser_adresse(""), "")
        for mauvaise in ("ftp://x", "http://u:p@x", "http://x/?a=b", "http://x:99999", "http://x/#f", "pas une adresse /"):
            with self.subTest(mauvaise=mauvaise), self.assertRaises(ValueError):
                recherche.normaliser_adresse(mauvaise)

    def test_la_cle_n_est_jamais_dans_la_vue_et_le_fichier_est_prive(self):
        vue = recherche.enregistrer(URL_SX, "cle-brave-123456")
        self.assertEqual((vue["searxng"], vue["brave"], vue["brave_fin"]), (URL_SX, True, "3456"))
        self.assertNotIn("cle-brave-123456", json.dumps(vue))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(recherche._chemin()).st_mode), 0o600)
        self.assertEqual(recherche.enregistrer(brave_cle="")["brave"], False, "retirer la clé")
        self.assertEqual(recherche.vue()["searxng"], URL_SX, "ne pas toucher à SearXNG en retirant la clé")
        for mauvaise in ("trop court", "avec espace dedans!!", "x" * 300):
            with self.subTest(mauvaise=mauvaise), self.assertRaises(ValueError):
                recherche.enregistrer(brave_cle=mauvaise)

    def test_un_fichier_de_configuration_abime_ne_plante_pas(self):
        recherche._chemin().write_text("[1, 2", encoding="utf-8")
        self.assertEqual(recherche.config(), {"searxng": "", "brave_cle": ""})
        recherche._chemin().write_text('"texte"', encoding="utf-8")
        self.assertEqual(recherche.config()["searxng"], "")

    def test_options_validees_et_propres_a_chaque_fil(self):
        self.assertEqual(recherche.definir_options("Semaine", "https://www.Docs.Python.org/3/", True, "en"), {"periode": "semaine", "site": "docs.python.org", "actualites": True, "langue": "en"})
        for periode, site in (("hier", None), (None, "pas un domaine"), (None, "x.y;rm")):
            with self.subTest(periode=periode, site=site), self.assertRaises(ValueError):
                recherche.definir_options(periode, site)
        recherche.definir_options("jour")
        vu = []
        t = threading.Thread(target=lambda: vu.append(recherche.options()))
        t.start()
        t.join()
        self.assertEqual(vu, [{}], "un autre fil ne voit pas les options de celui-ci")


class Nettoyage(Base):
    def test_suivi_ancres_et_doublons(self):
        res = recherche.nettoyer([
            {"titre": "A", "url": "https://exemple.org/p?utm_source=a&fbclid=1&id=7#ancre"},
            {"titre": "A bis", "url": "https://www.exemple.org/p/?id=7"},
            {"titre": "Faux", "url": "javascript:alert(1)"}, {"titre": "Vide", "url": ""}, {"titre": "Mail", "url": "mailto:x@y.z"}], 10)
        self.assertEqual([x["url"] for x in res], ["https://exemple.org/p?id=7"])

    def test_au_plus_deux_par_site_sauf_si_un_site_est_demande(self):
        entree = [{"titre": str(i), "url": "https://meme.exemple.org/%d" % i} for i in range(5)] + [{"titre": "autre", "url": "https://autre.exemple.net/"}]
        self.assertEqual(len(recherche.nettoyer(entree, 10)), 3)
        self.assertEqual(len(recherche.nettoyer(entree, 10, par_site=0)), 6)
        self.assertEqual(len(recherche.nettoyer(entree, 2)), 2, "et jamais plus que demandé")

    def test_textes_nettoyes_et_bornes(self):
        r = recherche.nettoyer([{"titre": "  Un   titre \n long ", "url": "https://exemple.org/", "extrait": "x" * 900, "date": "2026-10-30 08:00:00 +0200 et beaucoup trop long pour une date"}], 5)[0]
        self.assertEqual(r["titre"], "Un titre long")
        self.assertEqual((len(r["extrait"]), len(r["date"])), (300, 40))


class Searxng(Base):
    def test_exception_d_hote_limitee_a_searxng(self):
        recherche.enregistrer(URL_SX)
        res = recherche.resultats_searxng("requete")
        self.assertTrue(res)
        autre = URL_PG + "/article"
        with self.assertRaises(A.ErreurOutil) as e:
            web.web_telecharger(autre)
        self.assertIn("Adresse locale refusée", str(e.exception), "la lecture d'une page locale reste interdite, même à côté de SearXNG")
        with self.assertRaises(A.ErreurOutil):
            A.outil_web_lire(URL_SX + "/search?q=x", 0, {"web": True})
        with self.assertRaises(A.ErreurOutil):
            web.web_telecharger(URL_PG + "/article", hote_autorise="un.autre.hote")

    def test_requete_envoyee_et_resultats_nettoyes(self):
        recherche.enregistrer(URL_SX)
        recherche.definir_options("semaine", "docs.exemple.org", True, "en")
        recherche.resultats_searxng("guide installation")
        q = requete_de(derniere("searxng")[1])
        self.assertEqual((q["format"], q["language"], q["time_range"], q["categories"]), (["json"], ["en"], ["week"], ["news"]))
        self.assertEqual(q["q"], ["site:docs.exemple.org guide installation"])
        recherche.definir_options()
        res, _ = web.chercher_resultats("guide", 10, options=recherche.options())
        self.assertEqual([x["source"] for x in res], ["searxng"] * 3)
        urls = [x["url"] for x in res]
        self.assertIn("https://docs.exemple.org/guide?id=3", urls, "suivi et ancre retirés")
        self.assertEqual(sum("blog.exemple.net" in u for u in urls), 2, "deux résultats au plus par site")
        self.assertFalse(any("javascript" in u for u in urls))
        self.assertEqual(res[0]["date"], "2026-10-30")

    def test_reponse_non_json_dit_comment_corriger(self):
        recherche.enregistrer(URL_SX)
        ETAT["searxng"] = "html"
        with self.assertRaises(A.ErreurOutil) as e:
            recherche.resultats_searxng("x")
        self.assertIn("settings.yml", str(e.exception))

    def test_il_passe_avant_duckduckgo_et_bing(self):
        self.assertEqual([n for n, _ in web.moteurs_de_recherche()], ["duckduckgo", "bing"])
        recherche.enregistrer(URL_SX, "cle-brave-123456")
        self.assertEqual([n for n, _ in web.moteurs_de_recherche()], ["searxng", "brave", "duckduckgo", "bing"])

    def test_outil_complet_citations_date_et_moteur(self):
        recherche.enregistrer(URL_SX)
        texte = A.outil_web_chercher("guide d'installation", 6, {"web": True}, 0, "mois", "docs.exemple.org")
        for attendu in ("CONTENU WEB NON FIABLE", "1. Docs officielles", "https://docs.exemple.org/guide?id=3", "Date : 2026-10-30", "Moteur : searxng", "période : mois", "site : docs.exemple.org"):
            self.assertIn(attendu, texte)
        self.assertNotIn("utm_source", texte)
        for mauvais in ({"periode": "hier"}, {"site": "pas un site"}):
            with self.assertRaises(A.ErreurOutil):
                A.outil_web_chercher("x", 3, {"web": True}, 0, mauvais.get("periode"), mauvais.get("site"))

    def test_une_instance_arretee_laisse_les_autres_moteurs_prendre_le_relais(self):
        recherche.enregistrer("http://127.0.0.1:9")          # personne n'y répond
        appels = []
        vrai = web.moteurs_de_recherche
        web.moteurs_de_recherche = lambda: recherche.fournisseurs_configures() + [("secours", lambda q: appels.append(q) or [{"titre": "S", "url": "https://secours.exemple.org/", "extrait": ""}])]
        try:
            res, raisons = web.chercher_resultats("x", 3, options={})
        finally:
            web.moteurs_de_recherche = vrai
        self.assertEqual([x["source"] for x in res], ["secours"])
        self.assertTrue(any("searxng" in r for r in raisons), "la panne de SearXNG est expliquée")


class Brave(Base):
    def test_cle_en_en_tete_fraicheur_et_description_nettoyee(self):
        recherche.enregistrer(brave_cle="cle-brave-123456")
        recherche.definir_options("jour", None, False, "fr")
        res = recherche.resultats_brave("python 3.14")
        self.assertEqual(res[0]["extrait"], "un extrait")
        chemin, en_tetes = derniere("brave")[1], derniere("brave")[2]
        self.assertTrue(chemin.startswith("/res/v1/web/search?"))
        self.assertEqual(requete_de(chemin)["freshness"], ["pd"])
        self.assertEqual(en_tetes.get("X-Subscription-Token"), "cle-brave-123456")

    def test_actualites_utilisent_le_point_d_acces_des_nouvelles(self):
        recherche.enregistrer(brave_cle="cle-brave-123456")
        recherche.definir_options(None, None, True)
        res = recherche.resultats_brave("élections")
        self.assertEqual((res[0]["titre"], res[0]["extrait"]), ("Une dépêche", "Dernière minute"))
        self.assertIn("/news/search", derniere("brave")[1])

    def test_mauvaise_cle_est_une_erreur_claire(self):
        recherche.enregistrer(brave_cle="mauvaise-cle-000000")
        with self.assertRaises(A.ErreurOutil) as e:
            recherche.resultats_brave("x")
        self.assertIn("401", str(e.exception))


class LecturePages(Base):
    def setUp(self):
        super().setUp()
        os.environ["LUTIN_WEB_LOCAL"] = "1"          # les pages de test sont sur la boucle locale (interdite sinon, c'est justement ce que vérifie la classe Searxng)

    def tearDown(self):
        os.environ.pop("LUTIN_WEB_LOCAL", None)
        super().tearDown()

    def test_menus_et_pieds_de_page_ignores_et_liens_absolus(self):
        t = A.outil_web_lire(URL_PG + "/article", 0, {"web": True})
        self.assertIn("Un long paragraphe de contenu utile", t)
        self.assertNotIn("Menu du site", t)
        self.assertNotIn("Mentions légales", t)
        liens = A.outil_web_lire(URL_PG + "/article", 0, {"web": True}, True)
        self.assertIn("- La suite : " + URL_PG + "/suite", liens)
        self.assertIn("https://autre.exemple.org/x", liens)
        self.assertNotIn("#haut", liens)

    def test_page_dont_tout_le_contenu_est_dans_nav_est_quand_meme_lue(self):
        self.assertIn("n'existe que dans une balise nav", A.outil_web_lire(URL_PG + "/navseule", 0, {"web": True}))

    def test_jeu_de_caracteres_annonce_par_la_page(self):
        self.assertIn("écrit pour dépasser", A.outil_web_lire(URL_PG + "/article", 0, {"web": True}))

    def test_suite_d_une_page_longue_ne_retelecharge_pas(self):
        A.outil_web_lire(URL_PG + "/long", 0, {"web": True})
        suite = A.outil_web_lire(URL_PG + "/long", web.WEB_PAGE, {"web": True})
        self.assertIn("ligne 0600", suite)
        self.assertEqual(len([r for r in RECU if r[1] == "/long"]), 1, "une seule requête pour les deux morceaux")

    def test_une_panne_passagere_est_retentee_une_fois(self):
        vrai, web.time.sleep = web.time.sleep, lambda s: None
        try:
            t = A.outil_web_lire(URL_PG + "/fragile", 0, {"web": True})
        finally:
            web.time.sleep = vrai
        self.assertIn("Enfin disponible", t)
        self.assertEqual(len([r for r in RECU if r[1] == "/fragile"]), 2)

    def test_pdf_avec_ou_sans_extension(self):
        for chemin in ("/doc.pdf", "/sansextension"):
            with self.subTest(chemin=chemin):
                t = A.outil_web_lire(URL_PG + chemin, 0, {"web": True})
                self.assertIn("Bonjour le monde, création d'un déploiement", t)
                self.assertIn("CONTENU WEB NON FIABLE", t)

    def test_liens_d_un_texte_brut_refuses(self):
        with self.assertRaises(A.ErreurOutil):
            A.outil_web_lire(URL_PG + "/long", 0, {"web": True}, True)

    def test_hors_ligne_l_emporte_sur_le_cache(self):
        from lutin import horsligne
        A.outil_web_lire(URL_PG + "/long", 0, {"web": True})
        vrai = horsligne.garde

        def refuse(url):
            raise horsligne.HorsLigne("mode hors ligne")
        horsligne.garde = refuse
        try:
            with self.assertRaises(A.ErreurOutil):
                A.outil_web_lire(URL_PG + "/long", 0, {"web": True})
        finally:
            horsligne.garde = vrai


class Legerete(Base):
    """Fluide et léger : un seul moteur par recherche, mémoire bornée, aperçus qui ne téléchargent que le début des pages."""

    def test_un_seul_moteur_est_interroge_quand_le_premier_repond(self):
        appels = []
        ok = [{"titre": "T", "url": "https://exemple.org/%d" % i, "extrait": ""} for i in range(3)]
        vrai = web.moteurs_de_recherche
        web.moteurs_de_recherche = lambda: [(n, (lambda q, n=n: appels.append(n) or ok)) for n in ("searxng", "brave", "duckduckgo", "bing")]
        try:
            web.chercher_resultats("une requête", 5, options={})
            web.chercher_resultats("une requête", 5, options={})          # la même : le cache répond
        finally:
            web.moteurs_de_recherche = vrai
        self.assertEqual(appels, ["searxng"], "un moteur, une fois : pas quatre en même temps")

    def test_le_cache_de_pages_reste_borne_en_nombre_et_en_poids(self):
        vrai = web.web_telecharger
        web.web_telecharger = lambda url, donnees=None, **_: (url, "text/plain", "x" * 1_400_000)
        try:
            for i in range(20):
                web.page_en_cache("https://exemple.org/%d" % i, maintenant=lambda i=i: 1000 + i)
            poids = sum(len(v[1][2]) for v in web.CACHE_PAGES.values())
            self.assertLessEqual(len(web.CACHE_PAGES), web.CACHE_PAGES_MAX)
            self.assertLessEqual(poids, web.CACHE_PAGES_OCTETS)
            self.assertIn("https://exemple.org/19", web.CACHE_PAGES, "le plus récent est gardé")
            self.assertNotIn("https://exemple.org/0", web.CACHE_PAGES, "le plus ancien est parti")
            web.CACHE_PAGES.clear()
            web.web_telecharger = lambda url, donnees=None, **_: (url, "text/plain", "x" * 3_000_000)
            web.page_en_cache("https://exemple.org/enorme")
            self.assertEqual(len(web.CACHE_PAGES), 0, "une page énorme n'entre pas dans le cache")
        finally:
            web.web_telecharger = vrai

    def test_un_apercu_ne_telecharge_que_le_debut_de_la_page(self):
        vues = []
        vrai = web.web_telecharger
        web.web_telecharger = lambda url, donnees=None, **kw: (vues.append(kw), (url, "text/html", "<p>" + "un texte assez long pour faire un extrait lisible " * 5 + "</p>"))[1]
        try:
            self.assertTrue(web.extrait_page("https://exemple.org/x"))
        finally:
            web.web_telecharger = vrai
        self.assertEqual(vues, [{"max_octets": web.EXTRAIT_OCTETS}])
        self.assertLessEqual(web.EXTRAIT_OCTETS, 300_000)

    def test_aucun_fil_de_fond_n_est_ajoute(self):
        avant = threading.active_count()
        recherche.enregistrer(URL_SX)
        for _ in range(3):
            recherche.resultats_searxng("x")
        recherche.enregistrer("", "")
        time.sleep(0.2)
        self.assertLessEqual(threading.active_count(), avant, "la recherche ne laisse aucun fil derrière elle")


class Test(Base):
    def test_chaque_moteur_est_interroge_separement(self):
        recherche.enregistrer(URL_SX, "cle-brave-123456")
        vrai = web.moteurs_de_recherche
        web.moteurs_de_recherche = lambda: recherche.fournisseurs_configures() + [("muet", lambda q: [])]
        try:
            res = web.tester_moteurs("x")
            etat = web.etat_moteurs()
        finally:
            web.moteurs_de_recherche = vrai
        par_nom = {r["nom"]: r for r in res}
        self.assertTrue(par_nom["searxng"]["ok"] and par_nom["searxng"]["nombre"] == 3)
        self.assertTrue(par_nom["brave"]["ok"])
        self.assertFalse(par_nom["muet"]["ok"])
        self.assertEqual(par_nom["muet"]["erreur"], "aucun résultat")
        self.assertEqual([e["nom"] for e in etat], ["searxng", "brave", "muet"])
        self.assertTrue(etat[0]["configure"] and not etat[2]["configure"])


class Api(Base):
    @classmethod
    def setUpClass(cls):
        from lutin import securite as S
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.port = cls.serveur.server_address[1]
        cls.avant = A.SECURITE
        A.SECURITE = S.Securite(niveau=S.LOCAL)

    @classmethod
    def tearDownClass(cls):
        A.SECURITE = cls.avant
        cls.serveur.shutdown()

    def appel(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": "127.0.0.1:%d" % self.port, "X-Token": A.JETON}
        donnees = json.dumps(corps).encode() if corps is not None else None
        if donnees:
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        texte = r.read().decode("utf-8")
        c.close()
        return r.status, json.loads(texte) if texte else {}

    def test_lire_enregistrer_tester_sans_jamais_renvoyer_la_cle(self):
        statut, v = self.appel("GET", "/api/web-recherche")
        self.assertEqual(statut, 200)
        self.assertTrue(v["modifiable"] and not v["brave"])
        self.assertEqual([m["nom"] for m in v["moteurs"]], ["duckduckgo", "bing"])
        statut, v = self.appel("POST", "/api/web-recherche-config", {"searxng": URL_SX, "brave_cle": "cle-brave-123456"})
        self.assertEqual(statut, 200)
        self.assertEqual((v["searxng"], v["brave"], v["brave_fin"]), (URL_SX, True, "3456"))
        statut, v2 = self.appel("GET", "/api/web-recherche")
        self.assertNotIn("cle-brave-123456", json.dumps(v) + json.dumps(v2))
        self.assertNotIn("cle-brave-123456", json.dumps(self.appel("GET", "/api/etat")[1]), "l'état général ne la contient pas non plus")
        statut, t = self.appel("POST", "/api/web-recherche-test", {})
        self.assertEqual(statut, 200)
        self.assertTrue({r["nom"]: r["ok"] for r in t["resultats"]}["searxng"])

    def test_la_recherche_dans_les_conversations_n_est_pas_masquee(self):
        """/api/recherche est la recherche dans les conversations (page, barre latérale) ; celle du web a ses propres routes /api/web-recherche… : jamais la même adresse."""
        statut, v = self.appel("GET", "/api/recherche?q=quelquechose")
        self.assertEqual(statut, 200)
        self.assertIn("resultats", v)
        self.assertNotIn("moteurs", v)
        self.assertIn("moteurs", self.appel("GET", "/api/web-recherche")[1])

    def test_entrees_invalides_refusees(self):
        self.assertEqual(self.appel("POST", "/api/web-recherche-config", {"searxng": "ftp://x"})[0], 400)
        self.assertEqual(self.appel("POST", "/api/web-recherche-config", {"brave_cle": "x y"})[0], 400)

    def test_un_autre_appareil_ne_peut_pas_regler(self):
        vrai = self.serveur.RequestHandlerClass._configurateur_strict
        self.serveur.RequestHandlerClass._configurateur_strict = lambda self_: False          # un appareil appairé n'est jamais « cette machine »
        try:
            statut, v = self.appel("POST", "/api/web-recherche-config", {"searxng": URL_SX, "brave_cle": "cle-brave-123456"})
            self.assertEqual(statut, 403)
            self.assertEqual((recherche.vue()["searxng"], recherche.vue()["brave"]), ("", False), "rien n'a été enregistré")
            self.assertFalse(self.appel("GET", "/api/web-recherche")[1]["modifiable"])
        finally:
            self.serveur.RequestHandlerClass._configurateur_strict = vrai


if __name__ == "__main__":
    unittest.main()
