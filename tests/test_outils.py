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
            # Release channel (ADR 0004): with the file in the repository, main publishes pre-releases of the target and never a « latest » version
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "release_channel.json").write_text('{"channel": "alpha", "target": "1.0.0"}', encoding="utf-8")
            r = version("--mode", "release")
            self.assertEqual((r["version"], r["etiquette"], r["prerelease"], r["publier"]), ("1.0.0a1", "v1.0.0a1", "true", "true"))
            git("tag", "v1.0.0a1")
            self.assertEqual(version("--mode", "release")["publier"], "false", "HEAD already carries the pre-release tag")
            git("commit", "-q", "--allow-empty", "-m", "fix: next")
            self.assertEqual(version("--mode", "release")["version"], "1.0.0a2")
            self.assertEqual(version("--mode", "rc", "--branche", "modernization", "--numero", "4")["version"], "1.0.0.dev4+modernization")
            (Path(d) / "tools" / "release_channel.json").write_text("{not json", encoding="utf-8")
            broken = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "prochaine_version.py"), "--mode", "release"], cwd=d, capture_output=True, text=True)
            self.assertEqual((broken.returncode, broken.stdout), (2, ""), "an unreadable channel file stops the release instead of publishing a stable version by accident")


class ReleaseChannel(unittest.TestCase):
    """What `main` publishes is decided by tools/release_channel.json (docs/adr/0004-release-cadence.md)."""
    ALPHA = {"channel": "alpha", "target": "1.0.0"}

    def test_without_a_file_nothing_changes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(prochaine_version.lire_canal(Path(d) / "absent.json"), {"channel": "stable", "target": ""})
        r = prochaine_version.calcul(["v0.50.3"], ["fix: a"], "release")
        self.assertEqual((r["version"], r["prerelease"]), ("0.50.4", "false"))

    def test_pre_releases_are_numbered_per_phase_and_never_stable(self):
        c = prochaine_version.calcul
        self.assertEqual(c(["v0.50.3"], ["feat: a"], "release", canal=self.ALPHA)["version"], "1.0.0a1", "the target, whatever the commits say")
        r = c(["v0.50.3", "v1.0.0a1", "v1.0.0a7", "v0.9.0a9", "v1.0.0b2"], ["fix: a"], "release", canal=self.ALPHA)
        self.assertEqual((r["version"], r["etiquette"], r["prerelease"], r["base"]), ("1.0.0a8", "v1.0.0a8", "true", "0.50.3"), "pre-release tags never become the base")
        self.assertEqual(c(["v0.50.3", "v1.0.0a7"], [], "release", canal={"channel": "beta", "target": "1.0.0"})["version"], "1.0.0b1")
        self.assertEqual(c(["v0.50.3", "v1.0.0b3"], [], "release", canal={"channel": "rc", "target": "1.0.0"})["version"], "1.0.0rc1")
        self.assertEqual(c(["v0.50.3"], [], "release", canal=self.ALPHA, etiquettes_de_head=["v1.0.0a1"])["publier"], "false")

    def test_the_stable_channel_reaches_the_target_then_counts_as_usual(self):
        stable = {"channel": "stable", "target": "1.0.0"}
        r = prochaine_version.calcul(["v0.50.3", "v1.0.0rc2"], ["fix: a"], "release", canal=stable)
        self.assertEqual((r["version"], r["prerelease"]), ("1.0.0", "false"))
        self.assertEqual(prochaine_version.calcul(["v0.50.3", "v1.0.0"], ["fix: a"], "release", canal=stable)["version"], "1.0.1")

    def test_a_target_already_published_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            prochaine_version.calcul(["v1.0.0"], ["fix: a"], "release", canal=self.ALPHA)

    def test_branch_candidates_sort_below_every_pre_release(self):
        rc = prochaine_version.calcul(["v0.50.3"], ["fix: a"], "rc", branche="modernization", numero=12, canal=self.ALPHA)
        self.assertEqual((rc["version"], rc["etiquette"], rc["prerelease"]), ("1.0.0.dev12+modernization", "", "false"))
        self.assertRegex(rc["version"], r"^\d+\.\d+\.\d+\.dev\d+\+[a-z0-9.]+$")

    def test_a_wrong_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "release_channel.json"
            for wrong in ('{"channel": "alpha"}', '{"channel": "nightly", "target": "1.0.0"}', '{"channel": "beta", "target": "1.0"}', "[]", "{not json"):
                f.write_text(wrong, encoding="utf-8")
                with self.assertRaises(ValueError, msg=wrong):
                    prochaine_version.lire_canal(f)
            f.write_text('{"channel": "rc", "target": "2.1.0"}', encoding="utf-8")
            self.assertEqual(prochaine_version.lire_canal(f), {"channel": "rc", "target": "2.1.0"})

    def test_this_branch_publishes_pre_releases_only(self):
        """The guard of the migration: if this branch reaches main, what comes out is 1.0.0aN, never a version offered as the latest."""
        canal = prochaine_version.lire_canal(Path(__file__).resolve().parent.parent / "tools" / "release_channel.json")
        self.assertIn(canal["channel"], prochaine_version.PHASES)
        workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("prerelease: ${{ needs.version.outputs.prerelease == 'true' }}", workflow)
        self.assertIn('if [ "${{ steps.v.outputs.prerelease }}" = "true" ]', workflow, "a pre-release never takes the Docker tag :latest")


class CheminReseau(unittest.TestCase):
    """Un chemin réseau perd un antislash de tête en passant par le JSON d'un petit modèle : Lutin le rend à la commande."""

    def test_le_chemin_reseau_de_la_demande_est_retabli_dans_la_commande(self):
        from lutin import moteur  # noqa: F401  (avant outils : import circulaire sinon)
        from lutin import outils as o
        B = chr(92)
        unc = B * 2 + "NAS" + B + "Partage" + B + "Dossier" + B + "sorties"
        demande = "dis-moi ce qu'il y a ici " + unc
        self.assertEqual(o.reparer_unc("dir " + unc[1:], demande), "dir " + unc, "un antislash perdu est rendu")
        self.assertEqual(o.reparer_unc("dir " + unc, demande), "dir " + unc, "déjà correct : inchangé")
        lecteur = "dir C:" + B + "NAS" + B + "Partage" + B + "Dossier" + B + "sorties"
        self.assertEqual(o.reparer_unc(lecteur, demande), lecteur, "un chemin de lecteur n'est jamais touché")
        self.assertEqual(o.reparer_unc("dir " + unc[1:], "bonjour"), "dir " + unc[1:], "la demande ne parle d'aucun chemin réseau : rien n'est deviné")


class DonneesReservees(unittest.TestCase):
    def test_l_assistant_ne_lit_ni_n_ecrit_le_dossier_des_donnees(self):
        """Jetons, canaux de notification et clés vivent dans le dossier de données : même s'il est dans le projet, l'outil de lecture le refuse."""
        from lutin import moteur as m
        from lutin import outils
        with tempfile.TemporaryDirectory() as t:
            racine, donnees = Path(t).resolve(), Path(t).resolve() / "donnees"
            donnees.mkdir()
            (donnees / "notifications.json").write_text("{}", encoding="utf-8")
            (racine / "ok.txt").write_text("x", encoding="utf-8")
            avant = (m.RACINE, m.DONNEES)
            m.RACINE, m.DONNEES = racine, donnees
            try:
                self.assertEqual(outils.chemin_sur("ok.txt"), racine / "ok.txt")
                for ecriture in (False, True):
                    with self.assertRaises(m.ErreurOutil):
                        outils.chemin_sur("donnees/notifications.json", ecriture)
                with self.assertRaises(m.ErreurOutil):
                    outils.chemin_sur("donnees")
            finally:
                m.RACINE, m.DONNEES = avant


if __name__ == "__main__":
    unittest.main()
