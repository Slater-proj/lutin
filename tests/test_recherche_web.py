"""La recherche web ne dépend plus d'un seul moteur : si DuckDuckGo limite les requêtes, Bing prend le relais ; un moteur muet est laissé tranquille ; le modèle sait quoi faire quand plus rien ne répond."""
import base64
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-recherche-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import web  # noqa: E402


def lien_bing(adresse):
    u = "a1" + base64.urlsafe_b64encode(adresse.encode()).decode().rstrip("=")
    return "https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;ptn=3&amp;u=" + u + "&amp;ntb=1"


PAGE_BING = ('<ol id="b_results"><li class="b_algo" data-id><h2><a target="_blank" href="%s" h="ID=SERP">Docker <strong>Compose</strong> et SWAG</a></h2><div class="b_caption"><p class="b_lineclamp2">Un exemple de docker-compose pour le proxy SWAG &amp; OVH.</p></div></li>'
             '<li class="b_algo"><h2><a href="https://exemple.org/direct">Page directe</a></h2><p>Sans suivi.</p></li><li class="b_ad"><h2><a href="https://pub.example/">Publicité</a></h2></li></ol>') % lien_bing("https://docs.linuxserver.io/swag?a=1&b=2")


class Bing(unittest.TestCase):
    def test_l_adresse_reelle_est_retrouvee_derriere_le_lien_de_suivi(self):
        self.assertEqual(web.adresse_bing(lien_bing("https://www.docker.com/")), "https://www.docker.com/")
        self.assertEqual(web.adresse_bing("https://exemple.org/x"), "https://exemple.org/x")
        self.assertEqual(web.adresse_bing("https://www.bing.com/ck/a?u=zzz"), "", "un lien de suivi illisible est écarté")

    def test_page_de_resultats(self):
        vrai = web.web_telecharger
        web.web_telecharger = lambda url, donnees=None: (url, "text/html", PAGE_BING)
        try:
            r = web.resultats_bing("docker swag")
        finally:
            web.web_telecharger = vrai
        self.assertEqual([x["url"] for x in r], ["https://docs.linuxserver.io/swag?a=1&b=2", "https://exemple.org/direct"], "les publicités ne sont pas des résultats")
        self.assertEqual(r[0]["titre"], "Docker Compose et SWAG")
        self.assertIn("SWAG & OVH", r[0]["extrait"])


class Relais(unittest.TestCase):
    def setUp(self):
        web.BLOQUES.clear()
        web.CACHE_RECHERCHE.clear()
        self.vrai = web.moteurs_de_recherche
        self.appels = []

    def tearDown(self):
        web.moteurs_de_recherche = self.vrai
        web.BLOQUES.clear()
        web.CACHE_RECHERCHE.clear()

    def moteurs(self, **comportements):
        def fabrique(nom, f):
            def appel(requete):
                self.appels.append(nom)
                return f(requete)
            return nom, appel
        web.moteurs_de_recherche = lambda: [fabrique(n, f) for n, f in comportements.items()]

    def test_duckduckgo_limite_bing_prend_le_relais_puis_duckduckgo_est_laisse_tranquille(self):
        res = [{"titre": "T", "url": "https://exemple.org/", "extrait": "E"}]
        self.moteurs(duckduckgo=lambda q: [], bing=lambda q: res)
        r, raisons = web.chercher_resultats("une requête", 5, maintenant=lambda: 1000)
        self.assertEqual((r, self.appels), (res, ["duckduckgo", "bing"]))
        self.appels.clear()
        r, _ = web.chercher_resultats("une autre requête", 5, maintenant=lambda: 1100)
        self.assertEqual((r, self.appels), (res, ["bing"]), "DuckDuckGo est en pause : on ne l'interroge plus")
        self.appels.clear()
        web.chercher_resultats("une autre requête", 5, maintenant=lambda: 1200)
        self.assertEqual(self.appels, [], "la même recherche vient du cache")
        self.appels.clear()
        web.chercher_resultats("encore une autre", 5, maintenant=lambda: 1000 + web.PAUSE_BLOQUE_S + 1)
        self.assertEqual(self.appels[0], "duckduckgo", "la pause finie, DuckDuckGo est retenté en premier")

    def test_une_erreur_reseau_d_un_moteur_ne_bloque_pas_les_autres(self):
        def casse(q):
            raise A.ErreurOutil("HTTP 429")
        self.moteurs(duckduckgo=casse, bing=lambda q: [{"titre": "T", "url": "https://exemple.org/", "extrait": ""}])
        r, _ = web.chercher_resultats("x", 3)
        self.assertEqual(len(r), 1)

    def test_tous_muets_message_qui_dit_quoi_faire_et_pas_de_boucle(self):
        self.moteurs(duckduckgo=lambda q: [], bing=lambda q: [])
        texte = web.outil_web_chercher("quelque chose", 5, {"web": True}, 0)
        self.assertIn("NE RÉESSAIE PAS", texte)
        self.assertIn("duckduckgo", texte)
        self.assertIn("bing", texte)
        self.appels.clear()
        web.outil_web_chercher("autre chose", 5, {"web": True}, 0)
        self.assertEqual(sorted(self.appels), ["bing", "duckduckgo"], "même en pause, on retente quand tout est muet")

    def test_une_adresse_de_recherche_imposee_remplace_les_moteurs(self):
        web.moteurs_de_recherche = self.vrai
        os.environ["LUTIN_RECHERCHE_URL"] = "http://127.0.0.1:9/x"
        try:
            self.assertEqual([n for n, _ in web.moteurs_de_recherche()], ["duckduckgo"])
        finally:
            os.environ.pop("LUTIN_RECHERCHE_URL", None)
        self.assertEqual([n for n, _ in web.moteurs_de_recherche()], ["duckduckgo", "bing"])


if __name__ == "__main__":
    unittest.main()
