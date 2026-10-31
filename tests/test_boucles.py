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
    def test_garde_compte_les_appels_identiques_seulement(self):
        g = boucles.Garde()
        self.assertEqual([g.compter("lire", {"chemin": "a.txt"}) for _ in range(3)], [1, 2, 3])
        self.assertEqual(g.compter("lire", {"chemin": "b.txt"}), 1, "d'autres arguments : un autre appel")
        self.assertEqual(g.compter("lire", {"chemin": "a.txt"}), 4)
        self.assertFalse(g.abandon)
        self.assertEqual(g.compter("lire", {"chemin": "a.txt"}), 5)
        self.assertTrue(g.abandon, "cinq fois : on abandonne")
        for _ in range(8):
            self.assertEqual(g.compter("taches", {"liste": ["x"]}), 1, "taches, suivi et memoriser se rappellent légitimement")
        self.assertIn("exactement cet appel", boucles.Garde.message(3))

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


if __name__ == "__main__":
    unittest.main()
