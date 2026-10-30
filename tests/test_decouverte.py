"""La bibliothèque d'Ollama : lecture tolérante de la page de recherche, filtres, cache, erreurs claires."""
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import decouverte

PAGE = (Path(__file__).resolve().parent / "fixtures" / "ollama-recherche.html").read_text(encoding="utf-8")


def http_fixe(page, statut=200):
    appels = []

    def http(adresse, entetes=None):
        appels.append(adresse)
        return statut, {}, page.encode("utf-8")
    http.appels = appels
    return http


class Decouverte(unittest.TestCase):
    def setUp(self):
        decouverte.CACHE.clear()

    def test_analyse_de_la_page(self):
        modeles = decouverte.analyser(PAGE)
        self.assertEqual(len(modeles), 4)
        premier = modeles[0]
        self.assertTrue(premier["nom"] and premier["description"])
        self.assertTrue(all(isinstance(m["tailles"], list) and isinstance(m["capacites"], list) for m in modeles))
        tout = [c for m in modeles for c in m["capacites"]]
        self.assertTrue({"tools"} <= set(tout), "les capacités sont reconnues")
        self.assertTrue(any(m["tailles"] for m in modeles), "les tailles sont reconnues")
        for m in modeles:
            for t in m["tailles"]:
                self.assertRegex(t, decouverte.RE_TAILLE.pattern, "l'âge (« 1d ») n'est pas une taille")

    def test_page_incomprehensible_donne_une_liste_vide_pas_une_erreur(self):
        self.assertEqual(decouverte.analyser("<html>rien</html>"), [])
        self.assertEqual(decouverte.analyser(None), [])

    def test_chercher_filtre_cache_et_parametres(self):
        http = http_fixe(PAGE)
        r = decouverte.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 100)
        self.assertTrue(r["modeles"])
        self.assertIn("q=lfm", http.appels[0])
        self.assertIn("o=popular", http.appels[0])
        self.assertIn("p=2", http.appels[0])
        decouverte.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 200)
        self.assertEqual(len(http.appels), 1, "la même demande, peu après : pas de nouvelle requête")
        decouverte.chercher("lfm", "popular", 2, http=http, maintenant=lambda: 100 + decouverte.DUREE_CACHE + 1)
        self.assertEqual(len(http.appels), 2)

    def test_embeddings_et_nuage_seul_sont_ecartes(self):
        page = PAGE.replace(">tools<", ">embedding<", 1)
        noms = [m["nom"] for m in decouverte.chercher("", "newest", 1, http=http_fixe(page))["modeles"]]
        brut = [m["nom"] for m in decouverte.analyser(page) if "embedding" in m["capacites"]]
        self.assertTrue(brut)
        self.assertFalse(set(brut) & set(noms))

    def test_terme_nettoye_et_tri_refuse(self):
        http = http_fixe(PAGE)
        decouverte.chercher("a&b=c<script>", "newest", 1, http=http)
        self.assertNotIn("<", http.appels[0])
        self.assertNotIn("&b=c", http.appels[0])
        with self.assertRaises(ValueError):
            decouverte.chercher("", "au-hasard", 1, http=http)

    def test_erreurs_claires(self):
        with self.assertRaises(OSError) as e:
            decouverte.chercher("", "newest", 1, http=http_fixe("", 503))
        self.assertIn("503", str(e.exception))
        with self.assertRaises(OSError) as e:
            decouverte.chercher("x", "newest", 1, http=http_fixe("<html>le site a changé</html>"))
        self.assertIn("nom", str(e.exception))
        self.assertFalse([k for k in decouverte.CACHE if k[0] == "x"], "une page illisible n'est pas gardée")


if __name__ == "__main__":
    unittest.main()
