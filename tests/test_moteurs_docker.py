"""Les moteurs dans Docker : l'image est légère, Lutin installe Ollama / llama.cpp dans un volume depuis la page."""
import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import context  # noqa: F401
from lutin import moteurs, moteurs_docker as md

_TEMP = Path(tempfile.gettempdir())


def archive(fichiers):
    """Une archive tar (en mémoire) : {nom: octets}."""
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as t:
        for nom, contenu in fichiers.items():
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(contenu))
    return tampon.getvalue()


class Dossier(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=_TEMP))
        self.avant = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: True, hors_ligne=lambda: False)
        patcher = unittest.mock.patch.dict(os.environ, {"LUTIN_DOCKER": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("LUTIN_MOTEURS", None)
        os.environ.pop("OLLAMA_URL", None)

    def tearDown(self):
        moteurs.CONTEXTE.clear()
        moteurs.CONTEXTE.update(self.avant)

    def test_hors_docker_rien(self):
        self.assertIsNone(md.dossier_moteurs({}))

    def test_sans_montage_les_moteurs_vont_dans_le_volume_des_donnees(self):
        self.assertEqual(md.dossier_moteurs(monte=lambda d: False), self.tmp / "engines")

    def test_dossier_choisi_par_variable(self):
        with unittest.mock.patch.dict(os.environ, {"LUTIN_MOTEURS": "/autre"}):
            self.assertEqual(md.dossier_moteurs(), Path("/autre"))

    def test_point_de_montage_reconnu(self):
        info = self.tmp / "mountinfo"
        info.write_text("36 35 98:0 / /engines rw,noatime - ext4 /dev/sda1 rw\n37 35 98:0 / /data rw - ext4 /dev/sda1 rw\n", encoding="utf-8")
        self.assertTrue(md.est_monte("/engines", str(info)))
        self.assertFalse(md.est_monte("/models", str(info)))
        self.assertFalse(md.est_monte("/engines", str(self.tmp / "absent")))


class Extraction(unittest.TestCase):
    def test_extrait_le_programme_et_ses_bibliotheques(self):
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        md.extraire_tar(io.BytesIO(archive({"bin/ollama": b"x", "lib/ollama/libggml.so": b"y"})), d)
        self.assertEqual((d / "bin" / "ollama").read_bytes(), b"x")
        self.assertTrue((d / "lib" / "ollama" / "libggml.so").is_file())

    def test_refuse_de_sortir_du_dossier(self):
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        with self.assertRaises(ValueError):
            md.extraire_tar(io.BytesIO(archive({"../evade.txt": b"x"})), d / "sous")
        self.assertFalse((d / "evade.txt").exists())

    def test_refuse_un_lien_vers_l_exterieur(self):
        tampon = io.BytesIO()
        with tarfile.open(fileobj=tampon, mode="w") as t:
            info = tarfile.TarInfo("bin/lien")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../../etc/passwd"
            t.addfile(info)
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        with self.assertRaises(ValueError):
            md.extraire_tar(io.BytesIO(tampon.getvalue()), d)


class Installation(Dossier):
    def release(self, contenu, bon_digest=True):
        h = hashlib.sha256(contenu).hexdigest() if bon_digest else "0" * 64
        return {"tag_name": "v9.9.9", "assets": [{"name": "ollama-linux-amd64.tar.zst", "size": len(contenu), "digest": "sha256:" + h, "browser_download_url": "https://exemple.invalid/ollama.tar.zst"},
                                                 {"name": "ollama-linux-amd64-rocm.tar.zst", "size": 1, "digest": "", "browser_download_url": "https://exemple.invalid/rocm.tar.zst"}]}

    def installer(self, contenu, **kw):
        def telecharger(url, destination, progression=None, taille_min=0):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contenu)
            return destination
        etapes = []
        md.installer_ollama(lambda t, f, n: etapes.append(t), http_json=lambda url: self.release(contenu, **kw), telecharger=telecharger, ouvrir_archive=lambda f: open(f, "rb"))
        return etapes

    def test_installe_dans_le_dossier_des_moteurs_et_retient_la_version(self):
        with unittest.mock.patch("platform.machine", return_value="x86_64"):
            self.installer(archive({"bin/ollama": b"prog", "lib/ollama/a.so": b"lib"}))
        exe = md.ollama_installe_par_lutin()
        self.assertEqual(Path(exe), self.tmp / "engines" / "ollama" / "bin" / "ollama")
        self.assertEqual((self.tmp / "engines" / "ollama" / "version.txt").read_text(encoding="utf-8"), "v9.9.9")
        self.assertEqual(md.chemin_ollama(), exe)
        self.assertFalse((self.tmp / "engines" / "ollama" / "telechargement").exists())          # l'archive de 1,5 Go ne reste pas sur le disque

    def test_une_archive_corrompue_est_refusee(self):
        with unittest.mock.patch("platform.machine", return_value="x86_64"):
            with self.assertRaises(ValueError) as e:
                self.installer(archive({"bin/ollama": b"prog"}), bon_digest=False)
        self.assertIn("corrompu", str(e.exception))
        self.assertEqual(md.ollama_installe_par_lutin(), "")

    def test_archive_sans_programme(self):
        with unittest.mock.patch("platform.machine", return_value="x86_64"):
            with self.assertRaises(ValueError):
                self.installer(archive({"lib/ollama/a.so": b"lib"}))

    def test_rocm_ajoute_son_archive(self):
        r = self.release(b"x")
        self.assertEqual(len(md.fichiers_ollama(r, "x86_64", rocm=True)), 2)
        self.assertEqual(len(md.fichiers_ollama(r, "x86_64")), 1)
        self.assertEqual(md.fichiers_ollama(r, "riscv"), [])

    def test_desinstaller_garde_les_modeles(self):
        with unittest.mock.patch("platform.machine", return_value="x86_64"):
            self.installer(archive({"bin/ollama": b"prog"}))
        modeles = self.tmp / "modeles"
        modeles.mkdir()
        (modeles / "gros.bin").write_bytes(b"1")
        with unittest.mock.patch.object(md, "arreter_ollama"):
            md.desinstaller_ollama()
        self.assertEqual(md.ollama_installe_par_lutin(), "")
        self.assertTrue((modeles / "gros.bin").is_file())


class Actions(Dossier):
    def test_pas_installe_on_peut_l_installer(self):
        a = md.actions_ollama(installe=False, actif=False, hors_ligne=False)
        self.assertTrue(a["installer"]["possible"])
        self.assertFalse(a["desinstaller"]["possible"])
        self.assertFalse(a["demarrer"]["possible"])

    def test_hors_ligne_rien_a_telecharger(self):
        self.assertFalse(md.actions_ollama(False, False, True)["installer"]["possible"])

    def test_autre_conteneur_rien_n_est_gere_ici(self):
        with unittest.mock.patch.dict(os.environ, {"OLLAMA_URL": "http://ollama:11434"}):
            a = md.actions_ollama(True, True, False)
        self.assertTrue(all(not v["possible"] for v in a.values()))
        self.assertIn("docker compose", a["installer"]["raison"])

    def test_ollama_de_l_ancienne_image_ne_se_desinstalle_pas_ici(self):
        a = md.actions_ollama(True, False, False)          # installé (dans le PATH), pas par Lutin
        self.assertFalse(a["desinstaller"]["possible"])
        self.assertTrue(a["demarrer"]["possible"])

    def test_llamacpp_s_installe_aussi_dans_docker(self):
        from lutin import moteur_llamacpp as ml
        mo = ml.MoteurLlamaCpp()
        self.assertEqual(mo.dossier_defaut(), self.tmp / "engines" / "llamacpp")
        a = mo.actions()
        self.assertIn("installer", a)
        self.assertNotIn("indique son adresse", a["installer"]["raison"])
        self.assertEqual(mo.dossier_modeles().name, "gguf")          # à côté des modèles d'Ollama, dans le volume des modèles


if __name__ == "__main__":
    unittest.main()
