"""Les outils `trouver` (fichiers par nom) et `calculer` (calcul exact, sans exécuter de code)."""
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import moteur as _m
from lutin import outils_utiles as u


class Calculer(unittest.TestCase):
    def test_calculs_exacts(self):
        for expr, attendu in [("17 * 23 + 4", "395"), ("(1250 * 1.2) / 3", "500"), ("2 ** 10", "1024"), ("sqrt(144)", "12"), ("80 * 0.15", "12"), ("10 / 4", "2.5"), ("7 // 2", "3"), ("7 % 3", "1"),
                              ("3,5 * 2", "7"), ("2^8", "256"), ("max(1, 9, 4)", "9"), ("round(3.14159, 2)", "3.14"), ("0.1 + 0.2", "0.3"), ("-(2 + 3)", "-5"), ("pi", "3.14159265359"), ("5 × 6", "30"), ("9 ÷ 3", "3")]:
            self.assertTrue(u.outil_calculer(expr).endswith("= " + attendu), expr + " -> " + u.outil_calculer(expr))

    def test_grands_nombres_resumes(self):
        self.assertIn("chiffres", u.outil_calculer("factorial(200)"))
        self.assertTrue(u.outil_calculer("2 ** 100").endswith("= 1267650600228229401496703205376"))

    def test_rien_d_autre_que_des_calculs(self):
        for mauvais in ["__import__('os').system('dir')", "open('x')", "[1,2][0]", "'a' * 3", "x + 1", "lambda: 1", "(1).__class__", "sqrt(1, key=2)", "True + 1", "", "1 +", "abs.__call__(1)", "9" * 400]:
            with self.assertRaises(_m.ErreurOutil, msg=mauvais[:30]):
                u.outil_calculer(mauvais)

    def test_garde_fous(self):
        for abus in ["9 ** 9 ** 9", "10 ** 100000", "factorial(100000)", "2 ** 100000", "-" * 60 + "1"]:
            with self.assertRaises(_m.ErreurOutil, msg=abus[:30]):
                u.outil_calculer(abus)
        with self.assertRaises(_m.ErreurOutil):
            u.outil_calculer("1 / 0")
        self.assertTrue(u.outil_calculer("1e300 * 10").endswith("= 1e+301"))


class Trouver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=str(_m.RACINE))
        self.dossier = Path(self.tmp.name)
        (self.dossier / "sous" / "profond").mkdir(parents=True)
        (self.dossier / "node_modules").mkdir()
        for f in ("a.py", "test_un.py", "sous/test_deux.py", "sous/profond/Notes.MD", "sous/univers.md", "node_modules/test_cache.py"):
            (self.dossier / f).write_text("x", encoding="utf-8")
        self.rel = self.dossier.relative_to(_m.RACINE).as_posix()

    def tearDown(self):
        self.tmp.cleanup()

    def test_motifs(self):
        r = u.outil_trouver("test_*.py", self.rel)
        self.assertIn("test_un.py", r)
        self.assertIn("sous/test_deux.py", r)
        self.assertNotIn("test_cache.py", r, "les dossiers techniques sont ignorés")
        self.assertIn("univers.md", u.outil_trouver("univers", self.rel), "un mot sans joker est un morceau de nom")
        self.assertIn("Notes.MD", u.outil_trouver("*.md", self.rel), "la casse ne compte pas")
        self.assertEqual(len(u.outil_trouver("*.py", self.rel).splitlines()), 3)

    def test_sans_resultat_et_erreurs(self):
        self.assertIn("Aucun fichier", u.outil_trouver("*.zzz", self.rel))
        for mauvais in [("", "."), ("*.py", "../.."), ("*.py", self.rel + "/a.py")]:
            with self.assertRaises(_m.ErreurOutil, msg=str(mauvais)):
                u.outil_trouver(*mauvais)

    def test_liste_coupee(self):
        for i in range(u.MAX_TROUVES + 20):
            (self.dossier / "sous" / "f{}.txt".format(i)).write_text("x", encoding="utf-8")
        r = u.outil_trouver("*.txt", self.rel)
        self.assertEqual(len(r.splitlines()), u.MAX_TROUVES + 1)
        self.assertIn("liste coupée", r)


if __name__ == "__main__":
    unittest.main()
