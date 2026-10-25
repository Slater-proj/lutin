import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import prochaine_version  # noqa: E402
import verifier_catalogue  # noqa: E402
from lutin import catalogue  # noqa: E402

CAT = catalogue.charger()


class VerifierCatalogue(unittest.TestCase):
    def test_tout_existe(self):
        manquants, incertains = verifier_catalogue.disparus(CAT, lambda url, h=None: (200, {}, b""))
        self.assertEqual((manquants, incertains), ([], []))

    def test_un_modele_disparu_est_signale_mais_pas_une_panne_reseau(self):
        def http(url, h=None):
            if "/qwen3/manifests/8b" in url:
                return 404, {}, b""
            if "/gpt-oss/" in url:
                raise OSError("hors ligne")
            if "/llama3.2/" in url:
                return 503, {}, b""
            return 200, {}, b""
        manquants, incertains = verifier_catalogue.disparus(CAT, http)
        self.assertEqual([m[0] for m in manquants], ["qwen3:8b"])
        self.assertTrue({"gpt-oss:20b", "llama3.2:3b"} <= {i[0] for i in incertains})


class ProchaineVersion(unittest.TestCase):
    def test_derniere_etiquette_stable_la_plus_haute(self):
        self.assertEqual(prochaine_version.derniere_etiquette(["v0.1.0", "v0.10.2", "v0.9.9", "v1.0.0-rc1", "foo", "release-3"]), (0, 10, 2))
        self.assertIsNone(prochaine_version.derniere_etiquette([]))
        self.assertIsNone(prochaine_version.derniere_etiquette(["v1.0", "latest"]))

    def test_niveau_selon_les_commits(self):
        n = prochaine_version.niveau_de_changement
        self.assertEqual(n(["fix: une faute"]), "correctif")
        self.assertEqual(n(["docs: readme", "chore: nettoyage"]), "correctif")
        self.assertEqual(n(["Merge pull request #4 from x/y"]), "correctif")
        self.assertEqual(n(["fix: a", "feat: b", "docs: c"]), "mineur")
        self.assertEqual(n(["feat(ui): bouton"]), "mineur")
        self.assertEqual(n(["feat!: nouveau format"]), "majeur")
        self.assertEqual(n(["refactor(api)!: renommage"]), "majeur")
        self.assertEqual(n(["feat: x\n\nBREAKING CHANGE: ancien format supprimé"]), "majeur")
        self.assertEqual(n(["fix: a", "feat!: b"]), "majeur", "une rupture l'emporte sur le reste")
        self.assertEqual(n([]), "correctif")

    def test_version_suivante(self):
        s = prochaine_version.suivante
        self.assertEqual(s(None, "majeur"), (0, 1, 0), "première publication")
        self.assertEqual(s((0, 3, 1), "majeur"), (0, 4, 0), "tant que la majeure est 0, une rupture ne fait qu'une mineure")
        self.assertEqual(s((1, 2, 3), "majeur"), (2, 0, 0))
        self.assertEqual(s((1, 2, 3), "mineur"), (1, 3, 0))
        self.assertEqual(s((1, 2, 3), "correctif"), (1, 2, 4))

    def test_calcul_release_et_rc(self):
        c = prochaine_version.calcul
        r = c(["v0.2.0"], ["feat: a"], "release")
        self.assertEqual((r["version"], r["etiquette"], r["publier"], r["base"]), ("0.3.0", "v0.3.0", "true", "0.2.0"))
        self.assertEqual(c(["v0.2.0"], ["fix: a"], "release", etiquettes_de_head=["v0.2.0"])["publier"], "false", "HEAD déjà publié : rien à faire")
        self.assertEqual(c([], ["feat: a"], "release")["version"], "0.1.0")
        rc = c(["v0.2.0"], ["fix: a"], "rc", branche="Feature/Ma_Branche-2", numero=17)
        self.assertEqual((rc["version"], rc["etiquette"], rc["publier"]), ("0.2.1rc17+feature.ma.branche.2", "", "true"), "une candidate n'a jamais d'étiquette")

    def test_versions_valides_pour_pip(self):
        """Les versions produites sont de vraies versions PEP 440 (pip les accepte)."""
        import re
        pep440 = re.compile(r"^\d+\.\d+\.\d+(rc\d+)?(\+[a-z0-9]+(\.[a-z0-9]+)*)?$")
        for v in (prochaine_version.calcul(["v1.0.0"], ["fix: a"], "release")["version"], prochaine_version.calcul([], [], "rc", "é/ç--x", 3)["version"],
                  prochaine_version.calcul(["v0.1.0"], ["feat: a"], "rc", "///", 1)["version"]):
            self.assertRegex(v, pep440)

    def test_avec_un_vrai_depot_git(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                return subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"] + list(a), cwd=d, capture_output=True, text=True, check=True).stdout

            def version(*extra):
                r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "prochaine_version.py")] + list(extra), cwd=d, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                return dict(ligne.split("=", 1) for ligne in r.stdout.splitlines())
            git("init", "-q", "-b", "main")
            git("commit", "-q", "--allow-empty", "-m", "feat: début")
            self.assertEqual(version("--mode", "release")["version"], "0.1.0")
            git("tag", "v0.1.0")
            self.assertEqual(version("--mode", "release")["publier"], "false", "HEAD est déjà l'étiquette v0.1.0")
            git("commit", "-q", "--allow-empty", "-m", "fix: une correction")
            self.assertEqual(version("--mode", "release")["version"], "0.1.1")
            git("commit", "-q", "--allow-empty", "-m", "feat: une fonction")
            r = version("--mode", "release")
            self.assertEqual((r["version"], r["etiquette"], r["publier"]), ("0.2.0", "v0.2.0", "true"))
            rc = version("--mode", "rc", "--branche", "ma-branche", "--numero", "9")
            self.assertEqual((rc["version"], rc["etiquette"]), ("0.2.0rc9+ma.branche", ""))
            self.assertNotIn("v0.2.0", git("tag", "--list"), "le calcul ne crée aucune étiquette")


if __name__ == "__main__":
    unittest.main()
