"""La bibliothèque d'Ollama : lecture tolérante de la page de recherche, filtres, cache, erreurs claires."""
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import model_discovery

PAGE = (Path(__file__).resolve().parent / "fixtures" / "ollama-recherche.html").read_text(encoding="utf-8")


def http_fixe(page, statut=200):
    appels = []

    def http(adresse, entetes=None):
        appels.append(adresse)
        return statut, {}, page.encode("utf-8")
    http.appels = appels
    return http


class ModelesMac(unittest.TestCase):
    def test_les_modeles_pour_mac_ne_sont_pas_proposes_ailleurs(self):
        from unittest import mock
        self.assertTrue(model_discovery.pour_mac("qwen3-mlx") and model_discovery.pour_mac("auteur/modele-mlx-bf16") and model_discovery.pour_mac("mlx"))
        self.assertFalse(model_discovery.pour_mac("mixtral") or model_discovery.pour_mac("qwen3") or model_discovery.pour_mac("xmlx2"))
        with mock.patch("platform.system", return_value="Windows"):
            self.assertFalse(model_discovery.compatible("qwen3-mlx"))
            self.assertTrue(model_discovery.compatible("qwen3"))
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertTrue(model_discovery.compatible("qwen3-mlx"), "sur un Mac ils servent")


class Decouverte(unittest.TestCase):
    def setUp(self):
        model_discovery.CACHE.clear()

    def test_analyse_de_la_page(self):
        modeles = model_discovery.analyser(PAGE)
        self.assertEqual(len(modeles), 4)
        premier = modeles[0]
        self.assertTrue(premier["nom"] and premier["description"])
        self.assertTrue(all(isinstance(m["tailles"], list) and isinstance(m["capacites"], list) for m in modeles))
        tout = [c for m in modeles for c in m["capacites"]]
        self.assertTrue({"tools"} <= set(tout), "les capacités sont reconnues")
        self.assertTrue(any(m["tailles"] for m in modeles), "les tailles sont reconnues")
        for m in modeles:
            for t in m["tailles"]:
                self.assertRegex(t, model_discovery.RE_TAILLE.pattern, "l'âge (« 1d ») n'est pas une taille")

    def test_page_incomprehensible_donne_une_liste_vide_pas_une_erreur(self):
        self.assertEqual(model_discovery.analyser("<html>rien</html>"), [])
        self.assertEqual(model_discovery.analyser(None), [])

    def test_chercher_filtre_cache_et_parametres(self):
        http = http_fixe(PAGE)
        r = model_discovery.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 100)
        self.assertTrue(r["modeles"])
        self.assertIn("q=lfm", http.appels[0])
        self.assertIn("o=popular", http.appels[0])
        self.assertIn("p=2", http.appels[0])
        model_discovery.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 200)
        self.assertEqual(len(http.appels), 1, "la même demande, peu après : pas de nouvelle requête")
        model_discovery.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 100 + model_discovery.DUREE_CACHE + 1)
        self.assertEqual(len(http.appels), 2)

    def test_embeddings_et_nuage_seul_sont_ecartes(self):
        page = PAGE.replace(">tools<", ">embedding<", 1)
        noms = [m["nom"] for m in model_discovery.chercher("", "newest", 1, http=http_fixe(page))["modeles"]]
        brut = [m["nom"] for m in model_discovery.analyser(page) if "embedding" in m["capacites"]]
        self.assertTrue(brut)
        self.assertFalse(set(brut) & set(noms))

    def test_terme_nettoye_et_tri_refuse(self):
        http = http_fixe(PAGE)
        model_discovery.chercher("a&b=c<script>", "newest", 1, http=http)
        self.assertNotIn("<", http.appels[0])
        self.assertNotIn("&b=c", http.appels[0])
        with self.assertRaises(ValueError):
            model_discovery.chercher("", "au-hasard", 1, http=http)

    def test_erreurs_claires(self):
        with self.assertRaises(OSError) as e:
            model_discovery.chercher("", "newest", 1, http=http_fixe("", 503))
        self.assertIn("503", str(e.exception))
        with self.assertRaises(OSError) as e:
            model_discovery.chercher("x", "newest", 1, http=http_fixe("<html>le site a changé</html>"))
        self.assertIn("nom", str(e.exception))
        self.assertFalse([k for k in model_discovery.CACHE if k[0] == "x"], "une page illisible n'est pas gardée")

    def test_categorie_leger_lien_et_estimation(self):
        http = http_fixe(PAGE)
        r = model_discovery.chercher("", "newest", 1, http=http, categorie="tools")
        self.assertIn("c=tools", http.appels[0], "le filtre de capacité d'ollama.com est transmis")
        self.assertTrue(all(m["lien"] == "https://ollama.com/library/" + m["nom"] for m in r["modeles"]), "un lien vers la page de chaque modèle")
        with self.assertRaises(ValueError):
            model_discovery.chercher("", "newest", 1, http=http, categorie="n-importe-quoi")
        legers = model_discovery.chercher("", "newest", 1, http=http_fixe(PAGE), leger=True)["modeles"]
        self.assertTrue(all(any(0 < model_discovery.milliards(t) <= model_discovery.LEGER_B for t in m["tailles"]) for m in legers))
        embeddings = model_discovery.chercher("", "newest", 1, http=http_fixe(PAGE.replace(">tools<", ">embedding<", 1)), categorie="embedding")["modeles"]
        self.assertTrue(any("embedding" in m["capacites"] for m in embeddings), "demandés expressément, les embeddings sont montrés")

    def test_pas_de_doublon_et_pas_de_fausse_taille(self):
        bloc = PAGE.split("<li ", 2)[1]
        page = "<ul>" + ("<li " + bloc) * 2 + "</ul>"          # le même modèle deux fois dans une même page
        modeles = model_discovery.chercher("", "newest", 1, http=http_fixe(page))["modeles"]
        self.assertEqual(len(modeles), 1, "un modèle n'apparaît qu'une fois")
        avec = page.replace(">tools<", ">1m<", 1)
        self.assertNotIn("1m", model_discovery.analyser(avec)[0]["tailles"], "« 1m » (contexte) n'est pas une taille installable")
        self.assertIn("270m", model_discovery.analyser(page.replace(">tools<", ">270m<", 1))[0]["tailles"], "un vrai petit modèle en millions reste proposé")

    def test_tailles_et_jugement_de_la_machine(self):
        self.assertEqual(model_discovery.milliards("8b"), 8)
        self.assertEqual(model_discovery.milliards("8x7b"), 56)
        self.assertEqual(model_discovery.milliards("e4b"), 4)
        self.assertAlmostEqual(model_discovery.milliards("270m"), 0.27)
        self.assertEqual(model_discovery.milliards("latest"), 0)
        self.assertAlmostEqual(model_discovery.go_estime("8b"), 5.0, delta=0.1)
        liste = [{"nom": "x", "tailles": ["1b", "70b", "latest"], "capacites": []}]
        evals = model_discovery.evaluer_tailles(liste, lambda go: {"niveau": "trop_gros" if go > 20 else "bien", "texte": "t"})[0]["evaluations"]
        self.assertEqual(evals["70b"]["niveau"], "trop_gros")
        self.assertEqual(evals["1b"]["niveau"], "bien")
        self.assertNotIn("latest", evals, "une étiquette sans taille n'est pas jugée")
        self.assertNotIn("evaluations", liste[0], "la liste en cache n'est pas modifiée")


if __name__ == "__main__":
    unittest.main()
