"""Une opération de moteur (installation…) ne disparaît pas sans un mot : son résultat, réussi ou en erreur, reste lisible dans la barre du haut."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-fins-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon, et c'est lui qui enregistre les moteurs)
from lutin import engines  # noqa: E402


class Fins(unittest.TestCase):
    def setUp(self):
        engines.TACHES.clear()
        self.moteur = engines.MOTEURS["ollama"]

    def test_une_installation_reussie_laisse_son_dernier_message(self):
        def faire(action, progression):
            progression("Recherche de la dernière version…", 0, 0)
            progression("Installé : Colibri 2.1.0.", 1, 1)
        engines.lancer_tache(self.moteur, "installer", executer=faire, synchrone=True)
        fins = engines.fins_recentes()
        self.assertEqual([(f["statut"], f["texte"]) for f in fins], [("termine", "Installé : Colibri 2.1.0.")])
        self.assertEqual(engines.fins_recentes(maintenant=fins[0]["fin"] + engines.FIN_RESULTAT_S + 1), [], "un résultat réussi s'efface après quelques secondes")

    def test_une_erreur_reste_affichee_longtemps(self):
        def faire(action, progression):
            raise ValueError("GitHub ne répond pas")
        engines.lancer_tache(self.moteur, "installer", executer=faire, synchrone=True)
        fins = engines.fins_recentes()
        self.assertEqual([(f["statut"], f["texte"]) for f in fins], [("erreur", "GitHub ne répond pas")])
        self.assertEqual(len(engines.fins_recentes(maintenant=fins[0]["fin"] + engines.FIN_RESULTAT_S + 1)), 1)
        self.assertEqual(engines.fins_recentes(maintenant=fins[0]["fin"] + engines.FIN_ERREUR_S + 1), [])

    def test_une_operation_sans_message_ne_montre_rien(self):
        engines.lancer_tache(self.moteur, "demarrer", executer=lambda a, p: None, synchrone=True)
        self.assertEqual(engines.fins_recentes(), [])


if __name__ == "__main__":
    unittest.main()
