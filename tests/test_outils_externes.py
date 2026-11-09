"""uv et Node.js installés (et retirés) par Lutin en un clic : somme vérifiée, archive sûre, ancien programme gardé si la nouvelle installation échoue, venv de repli par uv. Aucun réseau : archives fabriquées."""
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import outils_externes as O  # noqa: E402


def zip_uv():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("uv.exe", b"MZ" + b"x" * 100)
        z.writestr("uvx.exe", b"MZ" + b"y" * 100)
    return b.getvalue()


def tar_node(lien_sortant=False):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:xz") as t:
        for nom, contenu in (("node-v1-linux-x64/bin/node", b"#!node"), ("node-v1-linux-x64/lib/node_modules/npm/bin/npx-cli.js", b"//npx")):
            i = tarfile.TarInfo(nom)
            i.size = len(contenu)
            t.addfile(i, io.BytesIO(contenu))
        lien = tarfile.TarInfo("node-v1-linux-x64/bin/npx")
        lien.type = tarfile.SYMTYPE
        lien.linkname = "../../../../../etc/passwd" if lien_sortant else "../lib/node_modules/npm/bin/npx-cli.js"
        t.addfile(lien)
    return b.getvalue()


class Faux:
    """Un « réseau » : les sommes publiées et le fichier à télécharger."""

    def __init__(self, archive, somme=None, sommes_ok=True):
        self.archive = archive
        self.somme = somme or hashlib.sha256(archive).hexdigest()
        self.sommes_ok = sommes_ok

    def http(self, url, entetes=None):
        if not self.sommes_ok:
            return 404, {}, b""
        if url.endswith(".sha256"):
            return 200, {}, (self.somme + "  fichier").encode()
        return 200, {}, "".join("{}  {}\n".format(self.somme, n) for n in (O.archive_node("linux", "x86_64"), O.archive_node("windows", "amd64"))).encode()

    def telecharger(self, url, destination, progression=None, taille_min=0):
        Path(destination).write_bytes(self.archive)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-outils-"))
        self.dossiers = {"donnees": self.tmp}
        self.sans_systeme = lambda nom: None          # rien d'installé sur « la machine »

    def installer(self, nom, faux, systeme="windows", arch="amd64"):
        return O.installer(nom, self.dossiers, lambda t: None, faux.http, faux.telecharger, systeme, arch)


class Installation(Base):
    def test_les_noms_d_archive_selon_le_systeme(self):
        self.assertEqual(O.archive_uv("windows", "AMD64"), "uv-x86_64-pc-windows-msvc.zip")
        self.assertEqual(O.archive_uv("linux", "aarch64"), "uv-aarch64-unknown-linux-gnu.tar.gz")
        self.assertEqual(O.archive_uv("darwin", "arm64"), "uv-aarch64-apple-darwin.tar.gz")
        self.assertEqual(O.archive_node("windows", "x86_64"), "node-v{}-win-x64.zip".format(O.VERSION_NODE))
        self.assertEqual(O.archive_node("linux", "x86_64"), "node-v{}-linux-x64.tar.xz".format(O.VERSION_NODE))
        with self.assertRaises(ValueError):
            O.archive_uv("freebsd", "x86_64")

    def test_uv_s_installe_et_se_trouve(self):
        exe = self.installer("uv", Faux(zip_uv()))
        self.assertTrue(Path(exe).is_file())
        self.assertEqual(O.chemin("uv", self.dossiers, self.sans_systeme), exe)
        self.assertTrue(O.par_lutin("uv", self.dossiers))

    def test_la_somme_fausse_n_installe_rien(self):
        with self.assertRaises(ValueError) as e:
            self.installer("uv", Faux(zip_uv(), somme="0" * 64))
        self.assertIn("corrompu", str(e.exception))
        self.assertFalse(O.par_lutin("uv", self.dossiers))
        self.assertFalse((O.dossier(dossiers=self.dossiers) / "uv.partiel").exists(), "pas de reste")

    def test_sans_somme_publiee_rien_n_est_installe(self):
        with self.assertRaises(ValueError) as e:
            self.installer("uv", Faux(zip_uv(), sommes_ok=False))
        self.assertIn("somme", str(e.exception))
        self.assertFalse(O.par_lutin("uv", self.dossiers))

    @unittest.skipIf(os.name == "nt", "les liens symboliques d'une archive Linux : testés sous Linux")
    def test_node_garde_ses_liens_internes_et_npx_se_trouve(self):
        exe = self.installer("node", Faux(tar_node()), "linux", "x86_64")
        self.assertTrue(exe.endswith("node"))
        npx = O.chemin("npx", self.dossiers, self.sans_systeme)
        self.assertTrue(npx.endswith("npx"), npx)
        self.assertEqual(O.dossiers_a_ajouter_au_path("node", self.dossiers), [str(Path(exe).parent)])

    def test_un_lien_qui_sort_du_dossier_est_refuse(self):
        archive = self.tmp / "piege.tar.xz"
        archive.write_bytes(tar_node(lien_sortant=True))
        with self.assertRaises(ValueError):
            O.extraire_sur(archive, self.tmp / "sortie")

    def test_un_fichier_zip_qui_sort_du_dossier_est_refuse(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("../dehors.txt", b"x")
        archive = self.tmp / "piege.zip"
        archive.write_bytes(b.getvalue())
        with self.assertRaises(ValueError):
            O.extraire_sur(archive, self.tmp / "sortie2")
        self.assertFalse((self.tmp / "dehors.txt").exists())

    def test_archive_sans_le_programme_refusee(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("lisez-moi.txt", b"rien")
        with self.assertRaises(ValueError) as e:
            self.installer("uv", Faux(b.getvalue()))
        self.assertIn("introuvable", str(e.exception))

    def test_une_nouvelle_installation_qui_echoue_garde_l_ancienne(self):
        exe = self.installer("uv", Faux(zip_uv()))
        with self.assertRaises(ValueError):
            self.installer("uv", Faux(zip_uv(), somme="1" * 64))
        self.assertTrue(Path(exe).is_file(), "l'ancienne version est intacte")


class Retrait(Base):
    def test_on_retire_ce_que_lutin_a_installe_et_rien_d_autre(self):
        self.installer("uv", Faux(zip_uv()))
        O.desinstaller("uv", self.dossiers)
        self.assertFalse(O.par_lutin("uv", self.dossiers))
        with self.assertRaises(ValueError) as e:          # un programme de la machine ne se retire pas d'ici
            O.desinstaller("uv", self.dossiers)
        self.assertIn("pas installé", str(e.exception))
        with self.assertRaises(ValueError):
            O.desinstaller("inconnu", self.dossiers)

    def test_l_etat_distingue_installe_par_lutin_et_installe_sur_la_machine(self):
        vide = {e["nom"]: e for e in O.etat(self.dossiers, lancer=mock.Mock(), chercher=self.sans_systeme)}
        self.assertFalse(vide["uv"]["installe"])
        machine = {e["nom"]: e for e in O.etat(self.dossiers, lancer=mock.Mock(return_value=mock.Mock(stdout="uv 9.9.9")), chercher=lambda n: "/usr/bin/" + n)}
        self.assertTrue(machine["uv"]["installe"])
        self.assertFalse(machine["uv"]["par_lutin"])
        self.assertEqual(machine["uv"]["version"], "9.9.9")


class EnvironnementPython(Base):
    def test_le_module_venv_suffit_quand_il_existe(self):
        appels = []

        def executer(cmd, **kw):
            appels.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        O.creer_venv(self.tmp / "venv", self.dossiers, lambda t: None, executer, installer_uv=lambda *a: self.fail("pas besoin de uv"))
        self.assertEqual(appels, [[sys.executable, "-m", "venv", str(self.tmp / "venv")]])

    def test_sans_le_module_venv_uv_est_installe_puis_cree_l_environnement(self):
        """Le Python fourni avec l'installateur Windows n'a pas « venv » : c'était l'erreur « No module named venv »."""
        appels, installe = [], []

        def executer(cmd, **kw):
            appels.append(cmd)
            if "venv" in cmd[:3] and cmd[0] == sys.executable:
                return mock.Mock(returncode=1, stdout="", stderr="No module named venv")
            return mock.Mock(returncode=0, stdout="", stderr="")

        def faux_installer(nom, dossiers, dire):
            installe.append(nom)
            return "/outils/uv"
        with mock.patch.object(O, "chemin", return_value=""):
            O.creer_venv(self.tmp / "venv", self.dossiers, lambda t: None, executer, faux_installer)
        self.assertEqual(installe, ["uv"])
        self.assertEqual(appels[-1], ["/outils/uv", "venv", "--seed", "--python", "3.12", str(self.tmp / "venv")])

    def test_un_uv_deja_la_n_est_pas_reinstalle(self):
        def executer(cmd, **kw):
            return mock.Mock(returncode=1 if cmd[0] == sys.executable else 0, stdout="", stderr="")
        with mock.patch.object(O, "chemin", return_value="/usr/bin/uv"):
            O.creer_venv(self.tmp / "venv", self.dossiers, lambda t: None, executer, lambda *a: self.fail("uv est déjà là"))

    def test_l_echec_final_dit_pourquoi(self):
        def executer(cmd, **kw):
            return mock.Mock(returncode=1, stdout="", stderr="pas de réseau")
        with mock.patch.object(O, "chemin", return_value="/usr/bin/uv"), self.assertRaises(ValueError) as e:
            O.creer_venv(self.tmp / "venv", self.dossiers, lambda t: None, executer)
        self.assertIn("pas de réseau", str(e.exception))


if __name__ == "__main__":
    unittest.main()
