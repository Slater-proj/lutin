"""Réglages des outils (Réglages > Outils) : bornes sûres, commandes « sans accord » strictement validées, outils coupés, limites appliquées sans redémarrer."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-outils-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import reglages_outils as RO  # noqa: E402

PAR_DEFAUT = {"outils_desactives": [], "outil_delai_commande_s": 240, "outil_sortie_max": 9000, "outil_lecture_max": 7000, "outil_chercher_delai_s": 25, "commandes_sans_accord": [], "dossiers_ignores_en_plus": []}


class Outils(unittest.TestCase):
    def tearDown(self):
        A.enregistrer_reglages(PAR_DEFAUT)

    def test_les_valeurs_par_defaut_sont_celles_d_avant(self):
        r = A.reglages()
        self.assertEqual({k: r[k] for k in PAR_DEFAUT}, PAR_DEFAUT)
        self.assertEqual((A.DELAI_COMMANDE_S, A.SORTIE_MAX, A.LECTURE_MAX, A.CHERCHER_DELAI), (240, 9000, 7000, 25))

    def test_les_valeurs_absurdes_reviennent_dans_les_bornes(self):
        r = RO.nettoyer({"outil_delai_commande_s": 99999, "outil_sortie_max": -5, "outil_lecture_max": "abc", "outil_chercher_delai_s": 0,
                         "outils_desactives": ["executer", "memoriser", "suivi", "n_importe_quoi"], "commandes_sans_accord": ["rm -rf x", "pytest -q", "git status && del x"], "dossiers_ignores_en_plus": ["data", "../x", "a/b"]})
        self.assertEqual((r["outil_delai_commande_s"], r["outil_sortie_max"], r["outil_lecture_max"], r["outil_chercher_delai_s"]), (3600, 2000, 7000, 5))
        self.assertEqual(r["outils_desactives"], ["executer"], "la mémoire et la fiche de suivi ne se coupent pas ici")
        self.assertEqual(r["commandes_sans_accord"], ["pytest -q"])
        self.assertEqual(r["dossiers_ignores_en_plus"], ["data"])

    def test_une_commande_dangereuse_est_refusee_avec_une_explication(self):
        for mauvaise in ("rm -rf x", "del *.txt", "curl http://exemple.org", "git status && del x", "cat /etc/passwd", "type C:\secret.txt", "python -c \"x\"", "pip install x", "bash -c x", "git status | more", "echo $(id)", "pytest ../x"):
            with self.assertRaises(ValueError, msg=mauvaise):
                A.enregistrer_reglages({"commandes_sans_accord": [mauvaise]})
        with self.assertRaises(ValueError):
            A.enregistrer_reglages({"outils_desactives": ["suivi"]})
        with self.assertRaises(ValueError):
            A.enregistrer_reglages({"dossiers_ignores_en_plus": ["a/b"]})

    def test_une_commande_sure_passe_sans_accord_seulement_nue_ou_avec_des_arguments_simples(self):
        A.enregistrer_reglages({"commandes_sans_accord": ["pytest -q", "git fetch"]})
        A.reglages()
        self.assertTrue(A.commande_lecture_sure("git fetch"))
        self.assertTrue(A.commande_lecture_sure("git fetch origin"))
        self.assertTrue(A.commande_lecture_sure("pytest -q tests"))
        self.assertFalse(A.commande_lecture_sure("pytest -q && del x"))
        self.assertFalse(A.commande_lecture_sure("git fetch ../autre"))
        self.assertFalse(A.commande_lecture_sure("pytestx"))
        self.assertTrue(A.commande_lecture_sure("git status"), "les lectures d'origine restent")

    def test_les_limites_sont_appliquees_et_les_dossiers_ignores_ajoutes(self):
        A.enregistrer_reglages({"outil_delai_commande_s": 600, "outil_sortie_max": 20000, "outil_lecture_max": 15000, "outil_chercher_delai_s": 60, "dossiers_ignores_en_plus": ["archives"]})
        A.reglages()
        self.assertEqual((A.DELAI_COMMANDE_S, A.SORTIE_MAX, A.LECTURE_MAX, A.CHERCHER_DELAI), (600, 20000, 15000, 60))
        self.assertIn("archives", A.DOSSIERS_IGNORES)
        self.assertIn("node_modules", A.DOSSIERS_IGNORES)
        A.enregistrer_reglages({"dossiers_ignores_en_plus": []})
        A.reglages()
        self.assertNotIn("archives", A.DOSSIERS_IGNORES)

    def test_un_outil_coupe_n_est_plus_propose_au_modele(self):
        from lutin import dialogue
        noms = lambda r: {t["function"]["name"] for t in dialogue.outils_du_mode(r)}  # noqa: E731
        base = dict(A.reglages(), mode="polyvalent")
        self.assertIn("executer", noms(base))
        A.enregistrer_reglages({"outils_desactives": ["executer", "web_lire"]})
        coupe = dict(A.reglages(), mode="polyvalent")
        self.assertNotIn("executer", noms(coupe))
        self.assertNotIn("web_lire", noms(coupe))
        self.assertIn("lire", noms(coupe))


if __name__ == "__main__":
    unittest.main()
