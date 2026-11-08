"""`lutin colibri` : installation vérifiée (somme SHA-256 obligatoire), décompression sans sortie du dossier, démarrage et arrêt par les commandes de Colibri, adresse locale seulement. Aucun réseau, aucun vrai Colibri : archive fabriquée et faux processus."""
import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401

from lutin import colibri as C  # noqa: E402


def zip_colibri(extra=None):
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("coli", "# script\n")
        z.writestr("openai_server.py", "# serveur\n")
        for nom, contenu in (extra or {}).items():
            z.writestr(nom, contenu)
    return tampon.getvalue()


class Flux:
    def __init__(self, donnees):
        self.donnees, self.pos = donnees, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        bloc = self.donnees[self.pos:self.pos + n]
        self.pos += len(bloc)
        return bloc


class Reseau:
    """Un faux GitHub : l'API de la dernière version, le SHA256SUMS.txt et l'archive."""

    def __init__(self, archive, somme=None, nom="colibri-v2.1.0-windows-x86_64.zip", avec_sommes=True):
        self.archive, self.nom, self.avec_sommes = archive, nom, avec_sommes
        self.somme = somme or hashlib.sha256(archive).hexdigest()
        self.demandes = []

    def http(self, url, entetes=None, delai=10):
        self.demandes.append(url)
        if url.endswith("/releases/latest"):
            return 200, {}, b'{"tag_name": "v2.1.0"}'
        if url.endswith("SHA256SUMS.txt"):
            return (200, {}, "{}  {}\n".format(self.somme, self.nom).encode()) if self.avec_sommes else (404, {}, b"")
        raise AssertionError(url)

    def ouvrir(self, requete, timeout=0):
        self.demandes.append(requete.full_url)
        return Flux(self.archive)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-colibri-"))
        self.dossiers = {"donnees": self.tmp / "donnees"}


class Installation(Base):
    def installer(self, reseau, **kw):
        return C.installer(None, self.dossiers, http=reseau.http, ouvrir=reseau.ouvrir, systeme="win32", architecture="AMD64", dire=lambda t: None, **kw)

    def test_installation_verifiee(self):
        reseau = Reseau(zip_colibri())
        version, racine = self.installer(reseau)
        self.assertEqual(version, "2.1.0")
        self.assertTrue((racine / "coli").is_file())
        self.assertIn("https://github.com/JustVugg/colibri/releases/download/v2.1.0/colibri-v2.1.0-windows-x86_64.zip", reseau.demandes)
        self.assertEqual(C.installee(self.dossiers)[0], "2.1.0")
        self.assertEqual(list((self.dossiers["donnees"] / "engines" / "colibri").glob("*.partiel")), [], "pas de dossier provisoire oublié")

    def test_somme_fausse_n_installe_rien(self):
        with self.assertRaises(ValueError):
            self.installer(Reseau(zip_colibri(), somme="0" * 64))
        self.assertIsNone(C.installee(self.dossiers))

    def test_pas_de_sommes_publiees_refuse_pour_un_programme_tiers(self):
        with self.assertRaises(ValueError):
            self.installer(Reseau(zip_colibri(), avec_sommes=False))
        self.assertIsNone(C.installee(self.dossiers))

    def test_archive_qui_sort_du_dossier_refusee(self):
        archive = zip_colibri({"../evade.txt": "x"})
        with self.assertRaises(ValueError) as e:
            self.installer(Reseau(archive))
        self.assertIn("sortirait", str(e.exception))
        self.assertFalse((self.dossiers["donnees"] / "engines" / "evade.txt").exists())
        self.assertFalse((self.tmp / "evade.txt").exists())
        self.assertIsNone(C.installee(self.dossiers))

    def test_archive_sans_script_coli_refusee(self):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr("autre.txt", "x")
        with self.assertRaises(ValueError):
            self.installer(Reseau(tampon.getvalue()))
        self.assertIsNone(C.installee(self.dossiers))

    def test_deuxieme_installation_ne_retelecharge_pas(self):
        reseau = Reseau(zip_colibri())
        self.installer(reseau)
        avant = len(reseau.demandes)
        self.installer(reseau)
        self.assertEqual([u for u in reseau.demandes[avant:] if u.endswith(".zip")], [], "déjà installé : l'archive n'est pas retéléchargée")

    def test_version_et_systeme_valides(self):
        with self.assertRaises(ValueError):
            C.installer("2.1.0; rm", self.dossiers, systeme="win32", architecture="AMD64", dire=lambda t: None)
        with self.assertRaises(ValueError):
            C.nom_archive("2.1.0", "freebsd", "x86_64")
        self.assertEqual(C.nom_archive("2.1.0", "linux", "x86_64"), "colibri-v2.1.0-linux-x86_64.tar.gz")
        self.assertEqual(C.nom_archive("2.1.0", "darwin", "arm64"), "colibri-v2.1.0-macos-arm64.tar.gz")
        with self.assertRaises(ValueError):
            C.nom_archive("2.1.0", "darwin", "x86_64")          # pas d'archive Intel pour macOS

    def test_tar_avec_lien_refuse(self):
        archive = self.tmp / "a.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("coli")
            info.size = 0
            tf.addfile(info, io.BytesIO(b""))
            lien = tarfile.TarInfo("lien")
            lien.type = tarfile.SYMTYPE
            lien.linkname = "/etc/passwd"
            tf.addfile(lien)
        with self.assertRaises(ValueError):
            C.extraire(archive, self.tmp / "sortie")


class Demarrage(Base):
    def preparer(self):
        reseau = Reseau(zip_colibri())
        C.installer("2.1.0", self.dossiers, http=reseau.http, ouvrir=reseau.ouvrir, systeme="win32", architecture="AMD64", dire=lambda t: None)
        modele = self.tmp / "modele"
        modele.mkdir()
        return modele

    def test_la_commande_est_locale_et_porte_le_modele(self):
        cmd = C.commande_serveur("/x", "/m", 8123, python="py")
        self.assertEqual(cmd, ["py", str(Path("/x") / "coli"), "serve", "--host", "127.0.0.1", "--port", "8123", "--model", "/m"])
        self.assertNotIn("0.0.0.0", cmd)

    def test_demarrer_sans_installation_ou_sans_modele(self):
        with self.assertRaises(ValueError):
            C.demarrer(str(self.tmp), dossiers=self.dossiers)
        modele = self.preparer()
        with self.assertRaises(ValueError):
            C.demarrer(str(self.tmp / "absent"), dossiers=self.dossiers)
        self.assertTrue(modele.is_dir())

    def test_demarrage_reussi_attend_la_reponse(self):
        modele = self.preparer()
        lances = []
        proc = mock.Mock()
        proc.poll.return_value = None
        reponses = iter([False, False, True])
        port = C.demarrer(str(modele), 8001, self.dossiers, lancer=lambda cmd, **kw: (lances.append((cmd, kw)), proc)[1], repond_=lambda p: next(reponses), dormir=lambda s: None)
        self.assertEqual(port, 8001)
        cmd, kw = lances[0]
        self.assertIn("--port", cmd)
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")

    def test_arret_au_demarrage_montre_la_fin_du_journal(self):
        modele = self.preparer()
        proc = mock.Mock()

        def lancer(cmd, **kw):
            kw["stdout"].write(b"erreur : modele illisible")
            kw["stdout"].flush()
            proc.poll.return_value = 1
            return proc
        with self.assertRaises(ValueError) as e:
            C.demarrer(str(modele), 8001, self.dossiers, lancer=lancer, repond_=lambda p: False, dormir=lambda s: None)
        self.assertIn("modele illisible", str(e.exception))

    def test_arreter_appelle_coli_stop(self):
        self.preparer()
        appels = []
        ok = C.arreter(8000, self.dossiers, lancer=lambda cmd, **kw: (appels.append(cmd), mock.Mock(returncode=0))[1])
        self.assertTrue(ok)
        self.assertEqual(appels[0][2:], ["stop", "--port", "8000"])


if __name__ == "__main__":
    unittest.main()
