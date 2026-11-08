"""Un dossier par conversation dans le dossier de travail : nom lisible et stable, retrouvé par la fin de l'identifiant, annoncé au modèle."""
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import fichiers, moteur as m

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-dosconv-"))


class DossierConversation(unittest.TestCase):
    def setUp(self):
        self.avant = m.RACINE
        m.RACINE = _TEMP.resolve()
        self.addCleanup(setattr, m, "RACINE", self.avant)

    def test_nom_lisible_sans_accents_ni_caracteres_speciaux(self):
        nom = fichiers._nom_dossier_conversation("Écrire un résumé : 100 % fiable !", "20261108-abc123def")
        self.assertTrue(nom.startswith("ecrire-un-resume-100-fiable-"), nom)
        self.assertTrue(nom.endswith("123def"), nom)
        self.assertEqual(fichiers._nom_dossier_conversation("", "x9"), "conversation-x9")

    def test_pas_cree_tant_qu_on_n_ecrit_pas_puis_retrouve_meme_si_le_titre_change(self):
        d = fichiers.dossier_de_conversation("abc-123456", "Mon titre")
        self.assertFalse(d.exists())
        fichiers.dossier_de_conversation("abc-123456", "Mon titre", creer=True)
        self.assertTrue(d.is_dir())
        self.assertEqual(fichiers.dossier_de_conversation("abc-123456", "Un tout autre titre"), d)          # retrouvé par l'identifiant
        self.assertNotEqual(fichiers.dossier_de_conversation("zzz-999999", "Mon titre"), d)          # une autre conversation, un autre dossier

    def test_le_modele_sait_ou_ranger(self):
        texte = fichiers.consigne_dossier({"id": "abc-123456", "titre": "Rapport"})
        self.assertIn("conversations/rapport-123456", texte)
        self.assertEqual(fichiers.consigne_dossier({}), "")
        self.assertEqual(fichiers.consigne_dossier(None), "")


if __name__ == "__main__":
    unittest.main()
