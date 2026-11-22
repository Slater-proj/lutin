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

from lutin import core as _m  # noqa: E402,F401
from lutin import loop_detection  # noqa: E402

PLAN = "Voici le plan : d'abord lire le fichier de configuration, ensuite corriger les erreurs de syntaxe, puis relancer les tests et enfin publier la nouvelle version. On commence ?"


class Boucles(unittest.TestCase):
    @staticmethod
    def appeler(g, nom, args, resultat):
        """Ce que fait agent.py pour un appel : compter, refuser au-delà du seuil, sinon noter le résultat obtenu."""
        n = g.compter(nom, args)
        if n >= loop_detection.CALL_THRESHOLD:
            g.refuser(nom, args)
        else:
            g.noter_resultat(nom, args, resultat)
        return n

    def test_garde_compte_les_appels_identiques_au_meme_resultat(self):
        g = loop_detection.Guard()
        self.assertEqual([self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu") for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.appeler(g, "lire", {"chemin": "b.txt"}, "autre"), 1, "d'autres arguments : un autre appel")
        self.assertEqual(self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu"), 4)
        self.assertFalse(g.abandon)
        self.assertEqual(self.appeler(g, "lire", {"chemin": "a.txt"}, "contenu"), 5)
        self.assertTrue(g.abandon, "cinq fois le même résultat : on abandonne")
        for _ in range(8):
            self.assertEqual(self.appeler(g, "taches", {"liste": ["x"]}, "ok"), 1, "taches, suivi et memoriser se rappellent légitimement")
        self.assertIn("exactement cet appel", loop_detection.Guard.message(3))

    def test_relire_un_fichier_qui_change_n_est_pas_une_boucle(self):
        """Relire après avoir modifié, relancer les tests après une correction : même appel, résultat différent. Le détecteur de boucle ne coupe pas un travail qui avance."""
        g = loop_detection.Guard()
        for i in range(12):
            self.assertLess(self.appeler(g, "lire", {"chemin": "a.py"}, "version %d" % i), loop_detection.CALL_THRESHOLD)
        self.assertFalse(g.abandon)
        for i in range(12):
            self.assertLess(self.appeler(g, "commande", {"commande": "pytest"}, "%d échecs" % (12 - i)), loop_detection.CALL_THRESHOLD)
        self.assertFalse(g.abandon)

    def test_le_texte_doit_tourner_en_rond_deux_controles_de_suite(self):
        self.assertEqual(loop_detection.CONSECUTIVE_CHECKS, 2)
        self.assertGreaterEqual(loop_detection.REPEAT_MIN_LENGTH, 2500)

    def test_similitude_et_reponse_repetee(self):
        self.assertGreater(loop_detection.similarity(PLAN, PLAN.replace("On commence ?", "On y va ?")), 0.8)
        self.assertLess(loop_detection.similarity(PLAN, "La salle est réservée pour le douze mai, le traiteur confirme la semaine prochaine."), 0.2)
        self.assertEqual(loop_detection.similarity("", PLAN), 0.0)
        conv = {"messages": [{"role": "user", "content": "go"}, {"role": "assistant", "content": PLAN}, {"role": "user", "content": "oui"}, {"role": "assistant", "content": PLAN + " Dis-moi."}]}
        self.assertTrue(loop_detection.repeats_last_answer(conv))
        conv["messages"][-1]["content"] = "J'ai lu le fichier : il contient deux erreurs de syntaxe aux lignes 12 et 40, je les corrige maintenant."
        self.assertFalse(loop_detection.repeats_last_answer(conv), "une réponse différente n'est pas une boucle")
        self.assertFalse(loop_detection.repeats_last_answer({"messages": [{"role": "assistant", "content": "Oui."}, {"role": "assistant", "content": "Oui."}]}), "les réponses courtes ne comptent pas")
        self.assertFalse(loop_detection.repeats_last_answer({"messages": []}))


    def test_texte_qui_tourne_en_rond_detecte_sans_faux_positif(self):
        boucle = "Je dois vérifier le fichier de configuration puis relancer les tests. " * 40
        self.assertTrue(loop_detection.repeated_text(boucle), "la même phrase 40 fois")
        self.assertTrue(loop_detection.repeated_text("Hmm. " + boucle + "Je dois vérifier le fichier de configuration"), "même coupée au milieu d'une phrase")
        self.assertFalse(loop_detection.repeated_text(boucle[:600]), "trop court pour juger")
        normal = " ".join("Étape %d : lire le fichier numéro %d, noter ce qui change et passer au suivant." % (i, i * 7) for i in range(60))
        self.assertFalse(loop_detection.repeated_text(normal), "une longue réflexion qui avance n'est pas une boucle")
        deux_fois = "Il faut d'abord comprendre le problème en détail avant de décider quoi faire ensuite. " * 2 + normal
        self.assertFalse(loop_detection.repeated_text(deux_fois), "une phrase redite deux fois n'est pas une boucle")
        self.assertFalse(loop_detection.repeated_text(""))
        self.assertFalse(loop_detection.repeated_text(None))

    def test_une_recherche_reformulee_est_la_meme_recherche(self):
        """Plan step 7: a small model rephrases the same search (order, case, accents, short words); it gets the same results, so it is the same call."""
        g = loop_detection.Guard()
        for requete in ("couleur robots Marly", "Marly : la COULEUR des robots", "robots marly couleur"):
            n = self.appeler(g, "chercher", {"motif": requete}, "rien trouvé")
        self.assertEqual(n, 3, "the third rephrasing is refused like a third identical call")
        self.assertEqual(self.appeler(g, "chercher", {"motif": "taille des robots"}, "rien trouvé"), 1, "other words: another search")
        self.assertNotEqual(loop_detection.fingerprint("lire", {"chemin": "A.txt"}), loop_detection.fingerprint("lire", {"chemin": "a.txt"}), "only searches are judged on their words")

    def test_le_meme_outil_qui_echoue_encore_et_encore(self):
        """Plan step 7: the same tool failing with different arguments (one wrong path after another) is a loop too: advice from the third error in a row,
        the turn concluded at the sixth; a success in between resets the count."""
        g = loop_detection.Guard()
        resultats = [g.noter_erreur("lire", "Erreur : fichier introuvable (x%d.txt)" % i) for i in range(5)]
        self.assertNotIn("de suite", resultats[1])
        self.assertIn("vient d'échouer 3 fois de suite", resultats[2])
        self.assertTrue(resultats[2].startswith("Erreur : fichier introuvable (x2.txt)"), "the error itself comes first")
        self.assertFalse(g.abandon)
        self.assertEqual(g.noter_erreur("lire", "contenu du fichier"), "contenu du fichier", "a success is given as it is")
        self.assertNotIn("de suite", g.noter_erreur("lire", "Erreur : encore"), "and resets the count")
        for _ in range(5):
            g.noter_erreur("modifier", "Erreur : texte introuvable")
        self.assertFalse(g.abandon)
        g.noter_erreur("modifier", "Erreur : texte introuvable")
        self.assertEqual((g.abandon, g.raison), (True, "errors"))


if __name__ == "__main__":
    unittest.main()
