"""Sortir le modèle d'une boucle : mêmes appels d'outils refaits, même réponse répétée."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-boucles-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401
from lutin import boucles  # noqa: E402

PLAN = "Voici le plan : d'abord lire le fichier de configuration, ensuite corriger les erreurs de syntaxe, puis relancer les tests et enfin publier la nouvelle version. On commence ?"


class Boucles(unittest.TestCase):
    @staticmethod
    def appeler(g, nom, args, resultat):
        """Ce que fait dialogue.py pour un appel : compter, refuser au-delà du seuil, sinon noter le résultat obtenu."""
        n = g.compter(nom, args)
        if n >= boucles.SEUIL_APPEL:
            g.refuser(nom, args)
        else:
            g.noter_resultat(nom, args, resultat)
        return n

    def test_garde_compte_les_appels_identiques_au_meme_resultat(self):
        g = boucles.Garde()
        self.assertEqual([self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu") for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.appeler(g, "lire", {"chemin": "b.txt"}, "autre"), 1, "d'autres arguments : un autre appel")
        self.assertEqual(self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu"), 4)
        self.assertFalse(g.abandon)
        self.assertEqual(self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu"), 5)
        self.assertTrue(g.abandon, "cinq fois le même résultat : on abandonne")
        for _ in range(8):
            self.assertEqual(self.appeler(g, "taches", {"liste": ["x"]}, "ok"), 1, "taches, suivi et memoriser se rappellent légitimement")
        self.assertIn("exactement cet appel", boucles.Garde.message(3))

    def test_relire_un_fichier_qui_change_n_est_pas_une_boucle(self):
        """Relire après avoir modifié, relancer les tests après une correction : même appel, résultat différent. Le détecteur de boucle ne coupe pas un travail qui avance."""
        g = boucles.Garde()
        for i in range(12):
            self.assertLess(self.appeler(g, "lire", {"chemin": "a.py"}, "version %d" % i), boucles.SEUIL_APPEL)
        self.assertFalse(g.abandon)
        for i in range(12):
            self.assertLess(self.appeler(g, "commande", {"commande": "pytest"}, "%d échecs" % (12 - i)), boucles.SEUIL_APPEL)
        self.assertFalse(g.abandon)

    def test_le_texte_doit_tourner_en_rond_deux_controles_de_suite(self):
        self.assertEqual(boucles.VERIFICATIONS_DE_SUITE, 2)
        self.assertGreaterEqual(boucles.LONGUEUR_REPETITION, 2500)

    def test_similitude_et_reponse_repetee(self):
        self.assertGreater(boucles.similitude(PLAN, PLAN.replace("On commence ?", "On y va ?")), 0.8)
        self.assertLess(boucles.similitude(PLAN, "La salle est réservée pour le douze mai, le traiteur confirme la semaine prochaine."), 0.2)
        self.assertEqual(boucles.similitude("", PLAN), 0.0)
        conv = {"messages": [{"role": "user", "content": "go"}, {"role": "assistant", "content": PLAN}, {"role": "user", "content": "oui"}, {"role": "assistant", "content": PLAN + " Dis-moi."}]}
        self.assertTrue(boucles.repete_derniere_reponse(conv))
        conv["messages"][-1]["content"] = "J'ai lu le fichier : il contient deux erreurs de syntaxe aux lignes 12 et 40, je les corrige maintenant."
        self.assertFalse(boucles.repete_derniere_reponse(conv), "une réponse différente n'est pas une boucle")
        self.assertFalse(boucles.repete_derniere_reponse({"messages": [{"role": "assistant", "content": "Oui."}, {"role": "assistant", "content": "Oui."}]}), "les réponses courtes ne comptent pas")
        self.assertFalse(boucles.repete_derniere_reponse({"messages": []}))


    def test_texte_qui_tourne_en_rond_detecte_sans_faux_positif(self):
        boucle = "Je dois vérifier le fichier de configuration puis relancer les tests. " * 40
        self.assertTrue(boucles.texte_repete(boucle), "la même phrase 40 fois")
        self.assertTrue(boucles.texte_repete("Hmm. " + boucle + "Je dois vérifier le fichier de configuration"), "même coupée au milieu d'une phrase")
        self.assertFalse(boucles.texte_repete(boucle[:600]), "trop court pour juger")
        normal = " ".join("Étape %d : lire le fichier numéro %d, noter ce qui change et passer au suivant." % (i, i * 7) for i in range(60))
        self.assertFalse(boucles.texte_repete(normal), "une longue réflexion qui avance n'est pas une boucle")
        deux_fois = "Il faut d'abord comprendre le problème en détail avant de décider quoi faire ensuite. " * 2 + normal
        self.assertFalse(boucles.texte_repete(deux_fois), "une phrase redite deux fois n'est pas une boucle")
        self.assertFalse(boucles.texte_repete(""))
        self.assertFalse(boucles.texte_repete(None))


if __name__ == "__main__":
    unittest.main()
