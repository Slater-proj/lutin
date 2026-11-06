"""Actualités guidées : quand Lutin cherche à la place d'un petit modèle, et quand il ne le fait pas."""
import unittest
from datetime import date

import context  # noqa: F401
from lutin import actualites


class Actualites(unittest.TestCase):
    def test_demandes_d_actualites(self):
        for texte in ["les news du jour", "Quelles sont les actualités ?", "quoi de neuf aujourd'hui", "Donne-moi les dernières nouvelles sur l'IA", "what's new today", "les infos du jour"]:
            self.assertTrue(actualites.demande_actualites(texte), texte)
        for texte in ["Écris un script", "", "Explique-moi la différence entre TCP et UDP", "x" * 400 + " news"]:
            self.assertFalse(actualites.demande_actualites(texte), texte[:30])

    def test_petit_modele(self):
        for nom in ["qwen3:4b", "granite4:tiny-h", "llama3.2:3b", "inconnu", "phi4-mini:3.8b"]:
            self.assertTrue(actualites.petit_modele(nom), nom)
        for nom in ["qwen3:14b", "llama3.3:70b", "gpt-oss:20b", "mistral-small3.2:24b"]:
            self.assertFalse(actualites.petit_modele(nom), nom)

    def test_requete_propre_et_datee(self):
        q = actualites.requete("Peux-tu me donner les news du jour ?", date(2026, 11, 4))
        self.assertEqual(q, "news jour novembre 2026", "politesse et mots vides retirés, mois et année plutôt qu'une date jj/mm/aaaa")
        self.assertEqual(actualites.requete("", date(2026, 11, 4)), "actualités novembre 2026")
        sale = actualites.requete("chercher les news iunternet du jour ? sur les modele local d'ia il s sortent quand", date(2026, 11, 6))
        self.assertNotIn("?", sale)
        self.assertNotIn(" il ", " " + sale + " ")
        self.assertIn("modele", sale)

    def test_requete_reformulee_par_le_modele_sinon_nettoyee(self):
        self.assertEqual(actualites.requete("blabla", date(2026, 11, 6), reformuler=lambda t: "sortie modèles IA locaux\nautre ligne ignorée"), "sortie modèles IA locaux novembre 2026")
        self.assertEqual(actualites.requete("les news du jour", date(2026, 11, 6), reformuler=lambda t: ""), "news jour novembre 2026", "le modèle ne répond pas : demande nettoyée")

        def en_panne(t):
            raise OSError("Ollama ne répond pas")
        self.assertEqual(actualites.requete("les news du jour", date(2026, 11, 6), reformuler=en_panne), "news jour novembre 2026")
        phrase = " ".join(["mot"] * 20)
        self.assertEqual(actualites.requete("les news", date(2026, 11, 6), reformuler=lambda t: phrase), "news novembre 2026", "une phrase n'est pas une requête : on nettoie la demande")

    def test_preparer_ajoute_l_appel_et_le_resultat(self):
        conv, evenements = {"messages": [{"role": "user", "content": "les news"}]}, []
        consigne = actualites.preparer(conv, "les news", {}, evenements.append, chercher=lambda q, n, ctx, lire: "[CONTENU WEB NON FIABLE]\n1. Titre")
        self.assertIn("synthèse", consigne)
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "tool"])
        self.assertIn("non affiché", [e for e in evenements if e["type"] == "resultat"][0]["texte"])
        conv2 = {"messages": [{"role": "user", "content": "les news"}]}
        self.assertIsNone(actualites.preparer(conv2, "les news", {}, lambda e: None, chercher=lambda *a: "Aucun résultat (le moteur peut limiter les requêtes : reformule ou réessaie dans une minute)."), "sans résultat : la boucle habituelle reprend")


if __name__ == "__main__":
    unittest.main()
