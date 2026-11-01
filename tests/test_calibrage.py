import unittest

import context  # noqa: F401
from lutin import calibrage


class Choix(unittest.TestCase):
    def test_candidats_selon_les_coeurs_disponibles(self):
        self.assertEqual(calibrage.candidats(6), [2, 3, 4, 6])
        self.assertEqual(calibrage.candidats(18), [6, 9, 12, 18])
        self.assertEqual(calibrage.candidats(2), [2], "deux cœurs : rien à comparer")
        self.assertEqual(calibrage.candidats(0, cpus=8), [3, 4, 5, 8])

    def test_le_plus_petit_nombre_de_coeurs_a_moins_de_3_pour_cent_du_meilleur(self):
        mesures = [{"fils": 4, "tok_s": 9.0}, {"fils": 6, "tok_s": 10.2}, {"fils": 8, "tok_s": 10.3}, {"fils": 12, "tok_s": 9.5}]
        self.assertEqual(calibrage.choisir(mesures), 6, "10,2 est à moins de 3 % de 10,3 : on garde des cœurs pour le reste")
        self.assertEqual(calibrage.choisir([{"fils": 4, "tok_s": 8.0}, {"fils": 8, "tok_s": 12.0}]), 8, "un vrai gain est suivi")
        self.assertEqual(calibrage.choisir([{"fils": 4, "tok_s": None}, {"fils": 8, "tok_s": 5.0}]), 8, "une mesure manquée est ignorée")

    def test_aucune_mesure_aucun_conseil(self):
        self.assertIsNone(calibrage.choisir([]))
        self.assertIsNone(calibrage.choisir([{"fils": 4, "tok_s": None}]))


if __name__ == "__main__":
    unittest.main()
