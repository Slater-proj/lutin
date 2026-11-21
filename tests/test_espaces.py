"""Les dossiers de travail : vérification (messages précis, délai), changement de chemin, déplacement (même disque, autre disque, échec, restes) et navigateur de dossiers."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-espaces-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)

from lutin import core  # noqa: E402,F401  (toujours avant espaces : ses modules lisent l'état de moteur)
from lutin import workspace_manager, workspaces  # noqa: E402


def cfg_avec(*dossiers):
    """Une configuration : le premier est le dossier principal, les suivants des dossiers ajoutés."""
    liste = [{"id": "d{}".format(i), "nom": Path(d).name, "chemin": str(d)} for i, d in enumerate(dossiers[1:], 1)]
    return {"emplacements": {"travail": str(dossiers[0]), "travaux": liste, "travail_actif": ""}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="espaces-")).resolve()
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def dossier(self, nom, fichiers=("a.txt",)):
        d = self.tmp / nom
        d.mkdir(parents=True, exist_ok=True)
        for f in fichiers:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("contenu " + f, encoding="utf-8")
        return d


class Diagnostic(Base):
    def test_un_dossier_normal_est_utilisable(self):
        self.assertIsNone(workspaces.diagnostic(self.dossier("ok")))

    def test_inexistant(self):
        self.assertIn("n'existe pas", workspaces.diagnostic(self.tmp / "absent"))

    def test_un_fichier_n_est_pas_un_dossier(self):
        f = self.tmp / "f.txt"
        f.write_text("x")
        self.assertIn("fichier", workspaces.diagnostic(f))

    def test_un_partage_reseau_introuvable_dit_quoi_verifier(self):
        reseau = Path(chr(92) * 2 + "nas" + chr(92) + "partage")
        with mock.patch.object(workspaces, "with_timeout", return_value=(True, (False, False, False))):
            message = workspaces.diagnostic(reseau)
        self.assertIn("réseau", message)
        self.assertIn("compte Windows", message, "la piste : le partage est ouvert avec un autre compte")

    def test_acces_refuse(self):
        with mock.patch.object(workspaces, "with_timeout", return_value=(False, PermissionError("non"))):
            self.assertIn("Accès refusé", workspaces.diagnostic(self.tmp))

    def test_un_dossier_qui_ne_repond_pas_rend_la_main(self):
        debut = time.time()
        fini, _ = workspaces.with_timeout(lambda: time.sleep(3), delai=0.2)
        self.assertIsNone(fini)
        self.assertLess(time.time() - debut, 1.5, "on n'attend pas la minute que Windows donnerait à un partage éteint")

    def test_verifier_chemin_lit_les_deux_ecritures_d_un_chemin_reseau_et_les_guillemets(self):
        d = self.dossier("avec espace")
        for texte in (str(d), '"{}"'.format(d), str(d) + os.sep):
            self.assertEqual(workspaces.check_path(texte), d)

    def test_la_racine_d_un_disque_est_refusee(self):
        with self.assertRaisesRegex(workspaces.WorkError, "disque entier"):
            workspaces.check_path(self.tmp.anchor)

    def test_les_dossiers_de_lutin_sont_refuses(self):
        lutin = self.dossier("lutin-donnees")
        (lutin / "sous").mkdir()
        with self.assertRaisesRegex(workspaces.WorkError, "dossiers de Lutin"):
            workspaces.check_path(lutin / "sous", [lutin])


class ChangerLeChemin(Base):
    def test_le_dossier_deplace_a_la_main_retrouve_son_chemin(self):
        ancien, nouveau = self.dossier("avant"), self.dossier("apres")
        cfg = cfg_avec(self.dossier("principal"), ancien)
        t = workspaces.change_path(cfg, "d1", str(nouveau))
        self.assertEqual(t["chemin"], str(nouveau))
        self.assertEqual(cfg["emplacements"]["travaux"][0]["chemin"], str(nouveau))

    def test_le_principal_aussi(self):
        principal, nouveau = self.dossier("principal"), self.dossier("nouveau")
        cfg = cfg_avec(principal)
        workspaces.change_path(cfg, workspaces.MAIN, str(nouveau))
        self.assertEqual(cfg["emplacements"]["travail"], str(nouveau))

    def test_refus_inconnu_inexistant_et_doublon(self):
        a, b = self.dossier("a"), self.dossier("b")
        cfg = cfg_avec(self.dossier("p"), a, b)
        with self.assertRaisesRegex(workspaces.WorkError, "inconnu"):
            workspaces.change_path(cfg, "zzz", str(a))
        with self.assertRaisesRegex(workspaces.WorkError, "n'existe pas"):
            workspaces.change_path(cfg, "d1", str(self.tmp / "absent"))
        with self.assertRaisesRegex(workspaces.WorkError, "déjà dans la liste"):
            workspaces.change_path(cfg, "d1", str(b))


class Deplacer(Base):
    def test_meme_disque_les_fichiers_suivent(self):
        source, parent = self.dossier("projet", ("a.txt", "sous/b.txt")), self.dossier("ailleurs", ())
        cfg = cfg_avec(self.dossier("principal"), source)
        t, restes = workspaces.move(cfg, "d1", str(parent))
        self.assertEqual((t["chemin"], restes), (str(parent / "projet"), []))
        self.assertFalse(source.exists())
        self.assertEqual((parent / "projet" / "sous" / "b.txt").read_text(encoding="utf-8"), "contenu sous/b.txt")

    def test_le_principal_se_deplace_et_se_renomme(self):
        principal, parent = self.dossier("principal"), self.dossier("ailleurs", ())
        cfg = cfg_avec(principal)
        workspaces.move(cfg, workspaces.MAIN, str(parent), "Mon projet")
        self.assertEqual(cfg["emplacements"]["travail"], str(parent / "Mon projet"))

    def test_un_nom_avec_des_caracteres_interdits_est_nettoye(self):
        source, parent = self.dossier("projet"), self.dossier("ailleurs", ())
        cfg = cfg_avec(self.dossier("principal"), source)
        t, _ = workspaces.move(cfg, "d1", str(parent), 'a/b:c?"')
        self.assertEqual(Path(t["chemin"]).parent, parent)
        self.assertNotIn("/", Path(t["chemin"]).name)

    def test_autre_disque_copie_puis_supprime_l_ancien(self):
        source, parent = self.dossier("projet", ("a.txt", "sous/b.txt")), self.dossier("ailleurs", ())
        cfg = cfg_avec(self.dossier("principal"), source)
        with mock.patch.object(workspaces.os, "rename", side_effect=OSError("autre disque")):
            t, restes = workspaces.move(cfg, "d1", str(parent))
        self.assertEqual(restes, [])
        self.assertTrue((Path(t["chemin"]) / "sous" / "b.txt").is_file())
        self.assertFalse(source.exists())

    def test_copie_qui_echoue_rien_ne_change_et_aucun_reste(self):
        source, parent = self.dossier("projet"), self.dossier("ailleurs", ())
        cfg = cfg_avec(self.dossier("principal"), source)
        with mock.patch.object(workspaces.os, "rename", side_effect=OSError("autre disque")), mock.patch.object(workspaces.shutil, "copytree", side_effect=OSError("disque plein")):
            with self.assertRaisesRegex(workspaces.WorkError, "rien n'a changé.*disque plein"):
                workspaces.move(cfg, "d1", str(parent))
        self.assertTrue((source / "a.txt").is_file(), "l'original n'a pas bougé")
        self.assertFalse((parent / "projet").exists(), "pas de copie à moitié faite")
        self.assertEqual(cfg["emplacements"]["travaux"][0]["chemin"], str(source), "la liste n'a pas bougé")

    def test_ce_qui_n_a_pas_pu_etre_supprime_est_liste(self):
        source, parent = self.dossier("projet"), self.dossier("ailleurs", ())
        cfg = cfg_avec(self.dossier("principal"), source)

        def rmtree_qui_bloque(chemin, onerror=None, **kw):
            onerror(os.remove, str(Path(chemin) / "a.txt"), None)
        with mock.patch.object(workspaces.os, "rename", side_effect=OSError("autre disque")), mock.patch.object(workspaces.shutil, "rmtree", side_effect=rmtree_qui_bloque):
            t, restes = workspaces.move(cfg, "d1", str(parent))
        self.assertEqual(restes, [str(source / "a.txt")], "dit où est resté ce qu'on n'a pas pu enlever")
        self.assertEqual(t["chemin"], str(parent / "projet"), "la copie est complète : on travaille dessus")

    def test_refus(self):
        source, parent = self.dossier("projet"), self.dossier("ailleurs", ())
        deja = self.dossier("ailleurs/projet")
        cfg = cfg_avec(self.dossier("principal"), source)
        with self.assertRaisesRegex(workspaces.WorkError, "existe déjà"):
            workspaces.move(cfg, "d1", str(parent))
        self.assertTrue(deja.is_dir())
        with self.assertRaisesRegex(workspaces.WorkError, "dans lui-même"):
            workspaces.move(cfg, "d1", str(source), "sous")
        with self.assertRaisesRegex(workspaces.WorkError, "déjà là"):
            workspaces.move(cfg, "d1", str(source.parent))
        with self.assertRaisesRegex(workspaces.WorkError, "inconnu"):
            workspaces.move(cfg, "zzz", str(parent))
        lutin = self.dossier("lutin")
        with self.assertRaisesRegex(workspaces.WorkError, "dossiers de Lutin"):
            workspaces.move(cfg, "d1", str(lutin), "x", [lutin])
        self.assertTrue(source.is_dir(), "après tous ces refus, rien n'a bougé")


class Navigateur(Base):
    def test_liste_les_sous_dossiers_seulement_tries(self):
        self.dossier("b", ("f.txt",))
        self.dossier("A", ())
        (self.tmp / "fichier.txt").write_text("x")
        r = workspace_manager.list_folders(str(self.tmp))
        self.assertEqual([d["nom"] for d in r["dossiers"]], ["A", "b"], "pas de fichiers ; ordre sans tenir compte des majuscules")
        self.assertEqual(r["chemin"], str(self.tmp))
        self.assertEqual(r["parent"], str(self.tmp.parent))
        self.assertTrue(all(os.path.isabs(d["chemin"]) for d in r["dossiers"]))

    def test_sans_chemin_les_points_de_depart(self):
        r = workspace_manager.list_folders("")
        self.assertEqual((r["chemin"], r["parent"]), ("", None))
        chemins = [d["chemin"] for d in r["dossiers"]]
        self.assertIn(str(Path.home()), chemins)
        if os.name == "nt":
            self.assertTrue(any(c.endswith(chr(92)) and c[1:2] == ":" for c in chemins), "les disques")

    def test_la_racine_d_un_disque_remonte_aux_points_de_depart(self):
        r = workspace_manager.list_folders(self.tmp.anchor)
        self.assertEqual(r["parent"], "")

    def test_erreurs_precises(self):
        with self.assertRaisesRegex(ValueError, "n'existe pas"):
            workspace_manager.list_folders(str(self.tmp / "absent"))

    def test_beaucoup_de_dossiers_sont_tronques(self):
        for i in range(5):
            self.dossier("d{}".format(i), ())
        with mock.patch.object(workspace_manager, "MAX_FOLDERS", 3):
            r = workspace_manager.list_folders(str(self.tmp))
        self.assertEqual((len(r["dossiers"]), r["tronque"]), (3, True))


if __name__ == "__main__":
    unittest.main()
