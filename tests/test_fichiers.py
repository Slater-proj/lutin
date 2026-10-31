"""Les fichiers produits pendant une conversation : carte avec Ouvrir (application choisie par le système), Télécharger et Supprimer, sans jamais sortir des dossiers permis."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-fichiers-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import fichiers, revue  # noqa: E402


class Fichiers(unittest.TestCase):
    def setUp(self):
        self.ouvertures = []
        self.vrai_config = _m.config_lue
        _m.config_lue = lambda: {}

    def tearDown(self):
        _m.config_lue = self.vrai_config

    def conversation(self, *chemins):
        c = _m.conv_nouvelle()
        c["messages"] = [{"role": "tool", "tool_name": "creer_document", "content": "ok", "fichiers_joints": [fichiers.entree(p) for p in chemins]}]
        _m.conv_ecrire(c)
        return c["id"], [fichiers.entree(p)["id"] for p in chemins]

    def test_telechargement_d_un_fichier_inscrit(self):
        f = _m.RACINE / "docs" / "bilan.pdf"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"%PDF-1.4 contenu")
        ident, (fid,) = self.conversation(f)
        octets, mime, nom = fichiers.lire(ident, fid)
        self.assertEqual((octets, mime, nom), (b"%PDF-1.4 contenu", "application/pdf", "bilan.pdf"))

    def test_un_fichier_non_inscrit_ou_hors_des_dossiers_permis_est_refuse(self):
        dehors = _TEMP / "secret.pdf"
        dehors.write_bytes(b"x")
        ident, (fid,) = self.conversation(dehors)
        with self.assertRaises(ValueError):
            fichiers.lire(ident, fid)                                              # inscrit, mais hors des dossiers de travail
        with self.assertRaises(ValueError):
            fichiers.lire(ident, "0123456789ab")                                    # jamais inscrit
        with self.assertRaises(ValueError):
            fichiers.ouvrir(ident, fid)

    def test_ouvrir_demande_au_systeme_et_refuse_les_programmes(self):
        document = _m.RACINE / "docs" / "note.docx"
        programme = _m.RACINE / "docs" / "outil.exe"
        document.parent.mkdir(exist_ok=True)
        document.write_bytes(b"PK")
        programme.write_bytes(b"MZ")
        ident, (d_id, p_id) = self.conversation(document, programme)
        with mock.patch.object(fichiers.sys, "platform", "linux"), mock.patch.object(fichiers.subprocess, "Popen", lambda cmd: self.ouvertures.append(cmd)):
            self.assertTrue(fichiers.ouvrir(ident, d_id)["ok"])
            with self.assertRaises(ValueError):
                fichiers.ouvrir(ident, p_id)
        self.assertEqual(self.ouvertures, [["xdg-open", str(document.resolve())]])

    def test_supprimer_efface_le_fichier_et_la_carte(self):
        f = _m.RACINE / "docs" / "a_effacer.md"
        f.parent.mkdir(exist_ok=True)
        f.write_text("# x", encoding="utf-8")
        ident, (fid,) = self.conversation(f)
        self.assertTrue(fichiers.supprimer(ident, fid)["fichier_supprime"])
        self.assertFalse(f.exists())
        self.assertNotIn("fichiers_joints", _m.conv_lire(ident)["messages"][0])
        with self.assertRaises(ValueError):
            fichiers.supprimer(ident, fid)

    def test_supprimer_ne_touche_jamais_un_fichier_hors_des_dossiers_permis(self):
        dehors = _TEMP / "precieux.pdf"
        dehors.write_bytes(b"x")
        ident, (fid,) = self.conversation(dehors)
        self.assertFalse(fichiers.supprimer(ident, fid)["fichier_supprime"])
        self.assertTrue(dehors.exists())

    def test_creer_document_attache_le_fichier_au_resultat(self):
        ctx = {"accord": lambda t, d, df, auto=False: True, "essai": False, "auto_ecriture": False, "stop": None, "tour": {"id": "t", "conversation": "abcdef01", "fichiers": {}}, "conv": {"id": "abcdef01"}}
        revue.appeler_outil("creer_document", {"chemin": "docs/rapport.pdf", "contenu": "# Rapport"}, ctx)
        revue.appeler_outil("creer_document", {"chemin": "docs/rapport.md", "contenu": "# Rapport"}, ctx)
        self.assertEqual([Path(p).name for p in ctx["fichiers_joints"]], ["rapport.pdf", "rapport.md"])


if __name__ == "__main__":
    unittest.main()
