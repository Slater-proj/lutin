import sys
import unittest
from pathlib import Path

import context  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import mesurer_rappel  # noqa: E402
from lutin import recall  # noqa: E402


class QualiteDuRappel(unittest.TestCase):
    def test_la_recherche_par_mots_retrouve_les_reformulations(self):
        """24 questions reformulées (pluriels, accents, conjugaisons, anglais) : une régression de la recherche se voit ici. Reste hors de portée des mots seuls : un pur synonyme (« backups » pour « sauvegardes »), que la recherche par le sens couvre."""
        r = mesurer_rappel.mesurer()
        self.assertGreaterEqual(r["rappel_1"], 0.92, r["ratees"])
        self.assertGreaterEqual(r["rappel_3"], 0.92, r["ratees"])
        self.assertGreaterEqual(r["mrr"], 0.92, r["ratees"])

    def test_le_pluriel_n_empeche_pas_de_retrouver(self):
        self.assertEqual(recall.mots("Mes chats et mon chat"), ["chat", "chat"])
        self.assertEqual(recall.mots("fonctions"), ["fonction"])
        self.assertEqual(recall.mots("access bonus mois"), ["access", "bonus", "mois"])


if __name__ == "__main__":
    unittest.main()
