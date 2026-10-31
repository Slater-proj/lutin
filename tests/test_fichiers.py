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

    def test_une_piece_jointe_se_retelecharge_sous_son_vrai_nom_et_s_ouvre_par_une_copie(self):
        from lutin import pieces
        ident, nom, _ = pieces.enregistrer("# Notes\nbonjour".encode("utf-8"), "mes notes.md")
        octets, mime, vrai_nom = fichiers.piece_lire(ident, "mes notes.md")
        self.assertEqual((octets, vrai_nom), ("# Notes\nbonjour".encode("utf-8"), "mes notes.md"))
        with mock.patch.object(fichiers.sys, "platform", "linux"), mock.patch.object(fichiers.subprocess, "Popen", lambda cmd: self.ouvertures.append(cmd)):
            fichiers.piece_ouvrir(ident, "mes notes.md")
            with self.assertRaises(ValueError):
                fichiers.piece_ouvrir(ident, "script.bat")
        copie = Path(self.ouvertures[0][1])
        self.assertEqual(copie.name, "mes notes.md", "la copie porte le vrai nom")
        self.assertEqual(copie.read_text(encoding="utf-8"), "# Notes\nbonjour")
        with self.assertRaises(ValueError):
            fichiers.piece_lire("../../etc/passwd", "x")

    def test_le_registre_liste_nettoie_et_supprime_pour_faire_le_menage(self):
        a, b = _m.RACINE / "docs" / "a.pdf", _m.RACINE / "docs" / "b.docx"
        a.parent.mkdir(exist_ok=True)
        a.write_bytes(b"%PDF" + b"x" * 2000)
        b.write_bytes(b"PK" + b"y" * 500)
        ident, (a_id, b_id) = self.conversation(a, b)
        fichiers.enregistrer([dict(fichiers.entree(a), genre="fichier"), dict(fichiers.entree(b), genre="fichier")], ident)
        fichiers.enregistrer([dict(fichiers.entree(a), genre="fichier")], ident)                     # une seule fois chacun
        r = fichiers.lister()
        noms = [x["nom"] for x in r["liste"] if x["conversation"] == ident]
        self.assertEqual(sorted(noms), ["a.pdf", "b.docx"])
        self.assertGreaterEqual(r["total"], 2500)
        b.unlink()                                                                                   # supprimé à la main : il quitte la liste tout seul
        self.assertEqual([x["nom"] for x in fichiers.lister()["liste"] if x["conversation"] == ident], ["a.pdf"])
        res = fichiers.supprimer_selection([a_id, "n-importe-quoi"])
        self.assertEqual(res["supprimes"], 1)
        self.assertGreaterEqual(res["libere"], 2000)
        self.assertFalse(a.exists())
        self.assertEqual([x for x in fichiers.lister()["liste"] if x["conversation"] == ident], [])
        restantes = [c["id"] for c in _m.conv_lire(ident)["messages"][0].get("fichiers_joints", [])]
        self.assertNotIn(a_id, restantes, "la carte du fichier supprimé a disparu de la conversation")

    def test_le_registre_supprime_aussi_quand_la_conversation_n_existe_plus_et_refuse_hors_des_dossiers(self):
        f = _m.RACINE / "docs" / "orphelin.md"
        f.parent.mkdir(exist_ok=True)
        f.write_text("# x", encoding="utf-8")
        dehors = _TEMP / "intouchable.pdf"
        dehors.write_bytes(b"x")
        fichiers.enregistrer([dict(fichiers.entree(f), genre="fichier"), dict(fichiers.entree(dehors), genre="fichier")], "deadbeef")
        ids = [fichiers.identifiant(f), fichiers.identifiant(dehors)]
        res = fichiers.supprimer_selection(ids)
        self.assertFalse(f.exists(), "conversation disparue : le fichier est supprimé quand même")
        self.assertTrue(dehors.exists(), "hors des dossiers permis : jamais touché")
        self.assertEqual(res["supprimes"], 1)
        self.assertEqual(len(res["ignores"]), 1)

    def test_les_cases_d_accord_automatique_survivent_a_un_autre_enregistrement_hors_local(self):
        from lutin import securite
        vrai = _m.SECURITE
        _m.SECURITE = securite.Securite(niveau=securite.RESEAU)
        try:
            _m.enregistrer_reglages({"auto_commandes": True, "auto_ecriture": True}, de_confiance=True)
            self.assertTrue(_m.reglages(de_confiance=True)["auto_commandes"], "le navigateur de cette machine les garde")
            self.assertFalse(_m.reglages()["auto_commandes"], "un appareil appairé non")
            _m.enregistrer_reglages({"web": False}, de_confiance=False)                              # un téléphone change un autre réglage
            self.assertTrue(_m.reglages(de_confiance=True)["auto_commandes"], "...sans effacer les cases de l'utilisateur")
            _m.enregistrer_reglages({"auto_commandes": False}, de_confiance=False)                   # ...et ne peut pas les décocher ni les cocher
            self.assertTrue(_m.reglages(de_confiance=True)["auto_commandes"])
        finally:
            _m.enregistrer_reglages({"auto_commandes": False, "auto_ecriture": False, "web": True}, de_confiance=True)
            _m.SECURITE = vrai

    def test_ouvrir_n_est_propose_que_sur_une_machine_avec_un_bureau(self):
        import os
        vrai = os.environ.get("LUTIN_DOCKER")
        try:
            os.environ["LUTIN_DOCKER"] = "1"
            self.assertFalse(fichiers.ouverture_possible(), "dans un conteneur : jamais")
            os.environ.pop("LUTIN_DOCKER", None)
            with mock.patch.object(fichiers.sys, "platform", "win32"):
                self.assertTrue(fichiers.ouverture_possible())
            with mock.patch.object(fichiers.sys, "platform", "linux"):
                os.environ.pop("DISPLAY", None)
                os.environ.pop("WAYLAND_DISPLAY", None)
                self.assertFalse(fichiers.ouverture_possible(), "Linux sans écran (serveur Debian) : non")
        finally:
            if vrai is not None:
                os.environ["LUTIN_DOCKER"] = vrai

    def test_creer_document_attache_le_fichier_au_resultat(self):
        ctx = {"accord": lambda t, d, df, auto=False: True, "essai": False, "auto_ecriture": False, "stop": None, "tour": {"id": "t", "conversation": "abcdef01", "fichiers": {}}, "conv": {"id": "abcdef01"}}
        revue.appeler_outil("creer_document", {"chemin": "docs/rapport.pdf", "contenu": "# Rapport"}, ctx)
        revue.appeler_outil("creer_document", {"chemin": "docs/rapport.md", "contenu": "# Rapport"}, ctx)
        self.assertEqual([Path(p).name for p in ctx["fichiers_joints"]], ["rapport.pdf", "rapport.md"])


if __name__ == "__main__":
    unittest.main()
