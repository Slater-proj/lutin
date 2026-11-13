"""Actualités guidées : quand Lutin cherche à la place d'un petit modèle, et quand il ne le fait pas."""
import unittest
from datetime import date

import context  # noqa: F401
from lutin import news


class Actualites(unittest.TestCase):
    def test_demandes_d_actualites(self):
        for texte in ["les news du jour", "Quelles sont les actualités ?", "quoi de neuf aujourd'hui", "Donne-moi les dernières nouvelles sur l'IA", "what's new today", "les infos du jour"]:
            self.assertTrue(news.demande_actualites(texte), texte)
        for texte in ["Écris un script", "", "Explique-moi la différence entre TCP et UDP", "x" * 400 + " news"]:
            self.assertFalse(news.demande_actualites(texte), texte[:30])

    def test_un_lien_ou_un_chemin_local_ne_lance_pas_une_recherche_sur_internet(self):
        """Le défaut vécu : « tu peux me donner le lien de la page html » (un fichier de son dossier) partait chercher « affiche 11b mpage html » sur le web."""
        petit, grand = "qwen3:4b", "qwen3:32b"
        locaux = ["affiche moi le 11b tu peux me donner le lien de la mpage html", "donne-moi le lien de la page html de la galerie", "donne-moi le lien du fichier", "où est le lien vers ma sauvegarde ?",
                  "ouvre C:\\Users\\x\\galerie.html", "où est \\\\NAS\\Software\\dossier", "affiche file:///C:/x/galerie-v11b.html", "montre-moi galerie-v11b.html", "donne-moi le chemin local de la galerie"]
        for texte in locaux:
            for modele in (petit, grand):
                self.assertEqual(news.mode_guide(texte, modele), "", (texte, modele))
        web = ["donne-moi des liens vers des articles sur le jazz", "cherche des liens sur la cuisine japonaise sur internet", "peux-tu chercher sur le web le prix du kWh", "donne-moi des liens vers des vidéos youtube sur le yoga"]
        for texte in web:
            self.assertEqual(news.mode_guide(texte, grand), "recherche", texte)

    def test_petit_modele(self):
        for nom in ["qwen3:4b", "granite4:tiny-h", "llama3.2:3b", "inconnu", "phi4-mini:3.8b"]:
            self.assertTrue(news.petit_modele(nom), nom)
        for nom in ["qwen3:14b", "llama3.3:70b", "gpt-oss:20b", "mistral-small3.2:24b"]:
            self.assertFalse(news.petit_modele(nom), nom)

    def test_requete_propre_et_datee(self):
        q = news.requete("Peux-tu me donner les news du jour ?", date(2026, 11, 4))
        self.assertEqual(q, "news jour novembre 2026", "politesse et mots vides retirés, mois et année plutôt qu'une date jj/mm/aaaa")
        self.assertEqual(news.requete("", date(2026, 11, 4)), "actualités novembre 2026")
        sale = news.requete("chercher les news iunternet du jour ? sur les modele local d'ia il s sortent quand", date(2026, 11, 6))
        self.assertNotIn("?", sale)
        self.assertNotIn(" il ", " " + sale + " ")
        self.assertIn("modele", sale)

    def test_requete_reformulee_par_le_modele_sinon_nettoyee(self):
        self.assertEqual(news.requete("blabla", date(2026, 11, 6), reformuler=lambda t: "sortie modèles IA locaux\nautre ligne ignorée"), "sortie modèles IA locaux novembre 2026")
        self.assertEqual(news.requete("les news du jour", date(2026, 11, 6), reformuler=lambda t: ""), "news jour novembre 2026", "le modèle ne répond pas : demande nettoyée")

        def en_panne(t):
            raise OSError("Ollama ne répond pas")
        self.assertEqual(news.requete("les news du jour", date(2026, 11, 6), reformuler=en_panne), "news jour novembre 2026")
        phrase = " ".join(["mot"] * 20)
        self.assertEqual(news.requete("les news", date(2026, 11, 6), reformuler=lambda t: phrase), "news novembre 2026", "une phrase n'est pas une requête : on nettoie la demande")

    def test_preparer_ajoute_l_appel_et_le_resultat(self):
        conv, evenements = {"messages": [{"role": "user", "content": "les news"}]}, []
        consigne = news.preparer(conv, "les news", {}, evenements.append, chercher=lambda q, n, ctx, lire: "[CONTENU WEB NON FIABLE]\n1. Titre")
        self.assertIn("synthèse", consigne)
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "tool"])
        self.assertIn("non affiché", [e for e in evenements if e["type"] == "resultat"][0]["texte"])
        conv2 = {"messages": [{"role": "user", "content": "les news"}]}
        self.assertIsNone(news.preparer(conv2, "les news", {}, lambda e: None, chercher=lambda *a: "Aucun résultat (le moteur peut limiter les requêtes : reformule ou réessaie dans une minute)."), "sans résultat : la boucle habituelle reprend")


class RechercheGuidee(unittest.TestCase):
    """Un petit modèle n'appelle pas l'outil de lui-même : Lutin cherche (ou lit l'adresse collée) et ne lui laisse que la réponse."""

    def test_modes(self):
        petit, grand = "qwen3:4b", "qwen3:32b"
        self.assertEqual(news.mode_guide("Cherche l'histoire judiciaire de Fiona Warr et donne-moi des liens", grand), "recherche", "demande claire : guidée même pour un grand modèle")
        self.assertEqual(news.mode_guide("qui est Fiona Warr ?", petit), "recherche")
        self.assertEqual(news.mode_guide("qui est Fiona Warr ?", grand), "", "question implicite : un grand modèle décide seul")
        self.assertEqual(news.mode_guide("résume https://exemple.org/article", grand), "lecture")
        self.assertEqual(news.mode_guide("les news du jour", petit), "actualites")
        self.assertEqual(news.mode_guide("les news du jour", grand), "")
        for texte in ["cherche le bug dans mon code", "explique la différence entre TCP et UDP", "bonjour", "Cherche", "", "cherche ```x = 1```", "x" * 500 + " cherche",
                      "https://exemple.org " + "mot " * 40]:
            self.assertEqual(news.mode_guide(texte, petit), "", texte[:30])

    def test_requete_sans_date_ni_bruit(self):
        q = news.requete("Cherche l'histoire judiciaire de Fiona Warr sur internet et donne-moi des liens", datee=False)
        self.assertEqual(q, "histoire judiciaire fiona warr", q)
        self.assertEqual(news.requete("...", datee=False), "...", "rien à garder : la demande telle quelle")
        appels = []
        news.requete("un ou deux mots", datee=False, reformuler=lambda t: appels.append(t) or "x")
        self.assertEqual(appels, [], "demande courte : pas d'appel au modèle")
        long = "cherche " + " ".join("motnumero%d" % i for i in range(12))
        self.assertEqual(news.requete(long, datee=False, reformuler=lambda t: "sujet reformulé"), "sujet reformulé")

    def test_recherche_montre_les_liens_et_ajoute_le_resultat(self):
        resultat = ("[CONTENU WEB NON FIABLE : x]\nRésultats\n\n1. Affaire Warr\n   https://a.example/warr\n   extrait\n\n2. Autre\n   https://b.example/x\n   extrait")
        conv, evenements = {"messages": [{"role": "user", "content": "cherche docker compose"}]}, []
        consigne = news.preparer(conv, "cherche docker compose", {}, evenements.append, chercher=lambda q, n, ctx, lire: resultat, mode="recherche")
        self.assertIn("[1]", consigne)
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "tool"])
        liens = [e["texte"] for e in evenements if e["type"] == "info" and "https://a.example/warr" in e["texte"]]
        self.assertEqual(len(liens), 1)
        self.assertIn("https://b.example/x", liens[0])
        self.assertEqual(news.sources(resultat), [("Affaire Warr", "https://a.example/warr"), ("Autre", "https://b.example/x")])

    def test_lecture_de_l_adresse_collee(self):
        conv, evenements, lus = {"messages": [{"role": "user", "content": "résume https://exemple.org/a."}]}, [], []
        consigne = news.preparer(conv, "résume https://exemple.org/a.", {}, evenements.append, mode="lecture", lire=lambda url, debut, ctx: lus.append(url) or "texte de la page")
        self.assertEqual(lus, ["https://exemple.org/a"], "la ponctuation finale n'est pas l'adresse")
        self.assertIn("page", consigne)
        self.assertEqual(conv["messages"][-1]["tool_name"], "web_lire")

    def test_reproches_et_noms_communs_ne_declenchent_rien(self):
        for texte in ["C'est la même réponse là tu ne m'as pas donné tes sources de tes résultats de recherche", "tu n'as pas cherché", "tu as déjà cherché non ?"]:
            self.assertEqual(news.mode_guide(texte, "qwen3:4b"), "", texte)
        self.assertEqual(news.mode_guide("Tu peux faire une recherche sur Fiona Watt ?", "qwen3:32b"), "recherche")

    def test_la_periode_se_dit_comme_on_veut(self):
        from lutin import web_search
        for dit, attendu in [("année", "an"), ("year", "an"), ("semaine", "semaine"), ("Week", "semaine"), ("aujourd'hui", "jour"), ("", None)]:
            self.assertEqual(web_search.definir_options(dit)["periode"], attendu, dit)
        with self.assertRaises(ValueError):
            web_search.definir_options("siècle")

    def test_noms_propres(self):
        self.assertEqual(news.noms_propres("Cherche l'histoire judiciaire de Fiona Warr et donne-moi des liens"), ["Fiona Warr"])
        self.assertEqual(news.noms_propres("Cherche des liens. Merci"), [])
        self.assertEqual(news.noms_propres("qui est Marie Curie ?"), ["Marie Curie"])

    def test_le_nom_est_entre_guillemets_et_verifie(self):
        pertinent = "[CONTENU WEB NON FIABLE : x]\n\n1. Fiona Watt\n   https://a.example/fw\n   Fiona Watt est une autrice."
        vus, conv = [], {"messages": [{"role": "user", "content": "x"}]}
        consigne = news.preparer(conv, "Cherche des infos sur Fiona Watt", {}, lambda e: None, chercher=lambda q, n, c, l: vus.append(q) or pertinent, mode="recherche")
        self.assertIn('"Fiona Watt"', vus[0])
        self.assertIn("[1]", consigne)

    def test_resultats_hors_sujet_le_modele_n_invente_rien(self):
        hors_sujet = "[CONTENU WEB NON FIABLE : x]\n\n1. Histoire — Wikipédia\n   https://fr.wikipedia.org/wiki/Histoire\n   L'histoire est une science."
        vus, evenements, conv = [], [], {"messages": [{"role": "user", "content": "x"}]}
        consigne = news.preparer(conv, "Cherche l'histoire judiciaire de Fiona Warr", {}, evenements.append, chercher=lambda q, n, c, l: vus.append(q) or hors_sujet, mode="recherche")
        self.assertEqual(len(vus), 2, "une seconde chance avec le nom seul")
        self.assertEqual(vus[1], '"Fiona Warr"')
        self.assertIn("Fiona Warr", consigne)
        self.assertIn("sans rien inventer", consigne)
        self.assertNotIn("Wikipédia", conv["messages"][-1]["content"], "les pages hors sujet ne sont pas données au modèle")
        self.assertTrue([e for e in evenements if e["type"] == "info" and "⚠" in e["texte"]])

    def test_sans_resultat_la_boucle_habituelle_reprend(self):
        conv = {"messages": [{"role": "user", "content": "cherche x"}]}
        self.assertIsNone(news.preparer(conv, "cherche x", {}, lambda e: None, chercher=lambda *a: "La recherche web ne répond pas.", mode="recherche"))


if __name__ == "__main__":
    unittest.main()
