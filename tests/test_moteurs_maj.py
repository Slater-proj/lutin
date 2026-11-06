"""Mise à jour des moteurs : un contrôle par 24 h au plus, silencieux sans réseau, jamais d'installation toute seule ; l'avis apparaît sur la carte du moteur."""
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-majmoteurs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import moteurs, moteurs_maj  # noqa: E402


class Versions(unittest.TestCase):
    def test_comparaison_des_numeros_de_version(self):
        self.assertEqual(moteurs_maj.numeros("b12167 (cuda)"), (12167,))
        self.assertEqual(moteurs_maj.numeros("v0.12.3"), (0, 12, 3))
        self.assertEqual(moteurs_maj.numeros("rien"), ())
        self.assertTrue(moteurs_maj.plus_recente("b12200", "b12167 (cuda)"))
        self.assertFalse(moteurs_maj.plus_recente("b12167", "b12167 (cuda)"))
        self.assertFalse(moteurs_maj.plus_recente("b12100", "b12167"), "jamais de « mise à jour » vers une version plus ancienne")
        self.assertTrue(moteurs_maj.plus_recente("v0.12.10", "0.12.9"), "0.12.10 est plus récent que 0.12.9 (nombres, pas texte)")
        self.assertFalse(moteurs_maj.plus_recente("", "b1"))
        self.assertFalse(moteurs_maj.plus_recente("b2", ""), "version installée inconnue : on ne prétend rien")


class Controle(unittest.TestCase):
    def setUp(self):
        self.donnees = _TEMP / "donnees-test"
        shutil.rmtree(self.donnees, ignore_errors=True)
        self.donnees.mkdir()
        self.avant = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.donnees, hors_ligne=lambda: False, en_docker=lambda: False)
        self.addCleanup(lambda: moteurs.CONTEXTE.update(self.avant))
        self.appels = []

        def llamacpp(mo, http_json):
            self.appels.append("llamacpp")
            return ("b12167 (cuda)", self.derniere)
        self.derniere = "b12200"
        p1 = mock.patch.object(moteurs_maj, "_derniere_llamacpp", llamacpp)
        p2 = mock.patch.object(moteurs_maj, "_derniere_ollama", lambda http_json: self.appels.append("ollama") or None)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        moteurs_maj.EN_COURS["actif"] = False

    def test_un_avis_puis_pas_de_nouveau_controle_avant_24_h(self):
        e = moteurs_maj.verifier(force=True, maintenant=lambda: 1000.0)
        self.assertTrue(e["llamacpp"]["disponible"])
        self.assertEqual((e["llamacpp"]["actuelle"], e["llamacpp"]["derniere"]), ("b12167 (cuda)", "b12200"))
        self.assertNotIn("ollama", e, "rien à dire d'un moteur dont on ne sait rien")
        n = len(self.appels)
        moteurs_maj.verifier(maintenant=lambda: 1000.0 + 3600)
        self.assertEqual(len(self.appels), n, "une heure plus tard : aucune requête")
        moteurs_maj.verifier(maintenant=lambda: 1000.0 + 25 * 3600)
        self.assertGreater(len(self.appels), n, "vingt-cinq heures plus tard : nouveau contrôle")

    def test_pas_de_reseau_garde_l_ancien_resultat_sans_bruit(self):
        moteurs_maj.verifier(force=True, maintenant=lambda: 1000.0)

        def panne(mo, http_json):
            raise urllib.error.URLError("pas de réseau")
        with mock.patch.object(moteurs_maj, "_derniere_llamacpp", panne):
            e = moteurs_maj.verifier(force=True, maintenant=lambda: 2000.0)
        self.assertTrue(e["llamacpp"]["disponible"], "le dernier résultat connu reste affiché")

    def test_hors_ligne_aucune_requete(self):
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        self.assertEqual(moteurs_maj.verifier(force=True), {})
        self.assertEqual(self.appels, [])

    def test_apres_une_mise_a_jour_l_avis_disparait(self):
        moteurs_maj.verifier(force=True, maintenant=lambda: 1000.0)
        self.assertIn("llamacpp", moteurs_maj.lire())
        moteurs_maj.oublier("llamacpp")
        self.assertEqual(moteurs_maj.etat(), {}, "le résultat n'est plus vrai : il sera refait au prochain contrôle")

    def test_a_jour_pas_d_avis(self):
        self.derniere = "b12167"
        e = moteurs_maj.verifier(force=True, maintenant=lambda: 1000.0)
        self.assertFalse(e["llamacpp"]["disponible"])


if __name__ == "__main__":
    unittest.main()
