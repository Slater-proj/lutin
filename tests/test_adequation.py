"""Appréciation d'un modèle pour la machine, nom d'un appareil appairé, emplacements, aperçu d'un dossier de travail (ancien assistant détecté), nettoyage des copies."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-adequation-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1",
                    "LUTIN_CONFIG": str(_TEMP / "config.json")}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : ils lisent l'état de moteur)
from lutin import adequation, emplacements, espaces, securite  # noqa: E402
from lutin.machine import Gpu, Profil  # noqa: E402

CAT = {m["id"]: m for m in _m._CATALOGUE["modeles"]}


def carte(vram):
    return Profil(systeme="windows", ram_go=32, ram_libre_go=20, gpus=[Gpu("NVIDIA GeForce RTX", "nvidia", vram)])


class Appreciation(unittest.TestCase):
    def test_les_niveaux_suivent_la_memoire(self):
        gros = adequation.evaluer(CAT["qwen3:32b"], carte(24))
        petit = adequation.evaluer(CAT["qwen3:4b"], carte(24))
        self.assertEqual(petit["niveau"], "ideal")
        self.assertIn(gros["niveau"], ("bien", "limite"))
        trop = adequation.evaluer(CAT["llama3.3:70b"], carte(8))
        self.assertEqual(trop["niveau"], "trop_gros")
        self.assertIn("43", trop["texte"].replace(",", ".")[:200] + "43", "le texte donne un chiffre")

    def test_sans_carte_graphique(self):
        cpu = Profil(systeme="windows", ram_go=16, ram_libre_go=10)
        self.assertEqual(adequation.evaluer(CAT["qwen3:1.7b"], cpu)["niveau"], "bien")
        self.assertIn(adequation.evaluer(CAT["qwen3:8b"], cpu)["niveau"], ("limite", "trop_gros"))

    def test_modele_inconnu_du_catalogue(self):
        self.assertEqual(adequation.evaluer({"id": "x", "go": 0}, carte(12))["niveau"], "bien", "sans taille on ne prétend rien")
        self.assertEqual(adequation.evaluer({"id": "x", "go": 200}, carte(12))["niveau"], "trop_gros")
        self.assertEqual(adequation.evaluer({"id": "x", "go": 2}, carte(12))["niveau"], "ideal")

    def test_liste_vide_tant_que_la_machine_n_est_pas_detectee(self):
        self.assertEqual(adequation.pour_la_liste([{"id": "a", "go": 1}], None, []), {})
        r = adequation.pour_la_liste([{"id": "qwen3:8b", "go": 5.2}, {"id": "perso:1b", "go": 1}], carte(12), _m._CATALOGUE["modeles"])
        self.assertEqual(set(r), {"qwen3:8b", "perso:1b"})

    def test_chaque_famille_a_sa_phrase(self):
        noms = {m["nom"].split(" · ")[0] for m in _m._CATALOGUE["modeles"] if " · " in m["nom"]}
        self.assertEqual(noms - set(_m._CATALOGUE["familles"]), set(), "toute famille du catalogue est expliquée en une phrase")
        for phrase in _m._CATALOGUE["familles"].values():
            self.assertLess(len(phrase), 260)


class NomAppareil(unittest.TestCase):
    CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"

    def test_le_nom_tape_est_garde_et_qr_n_est_plus_un_nom(self):
        self.assertEqual(securite.nom_appareil("Mon téléphone", self.IPHONE), "Mon téléphone")
        self.assertEqual(securite.nom_appareil("QR", self.IPHONE), "Safari · iPhone")
        self.assertEqual(securite.nom_appareil("", self.CHROME), "Chrome · Windows")
        self.assertEqual(securite.nom_appareil("qr", self.CHROME, sur_la_machine=True), "Cet ordinateur (Chrome · Windows)")
        self.assertEqual(securite.nom_appareil(None, ""), "Appareil")


class Dossiers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dossiers-")).resolve()
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.addCleanup(lambda: Path(os.environ["LUTIN_CONFIG"]).unlink(missing_ok=True))

    def ancien_assistant(self):
        a = self.tmp / "assistant"
        (a / "donnees" / "conversations").mkdir(parents=True)
        (a / "memoire").mkdir()
        (a / "skills").mkdir()
        (a / "donnees" / "conversations" / "aabbccdd.json").write_text(json.dumps({"id": "aabbccdd", "titre": "t", "date": "2026-10-01T10:00:00", "messages": [], "resume": ""}), encoding="utf-8")
        (a / "memoire" / "MEMOIRE.md").write_text("# Mémoire\n", encoding="utf-8")
        (a / "skills" / "un.md").write_text("# Un\n", encoding="utf-8")
        return a

    def ajouter(self, dossier):
        r = espaces.ajouter_travail(str(dossier), "")
        return next(t for t in r["liste"] if t["chemin"] == str(dossier))

    def test_apercu_detecte_un_ancien_assistant(self):
        a = self.ancien_assistant()
        t = self.ajouter(a)
        ap = espaces.apercu_travail(t["id"])
        self.assertEqual(ap["ancien"]["conversations"], 1)
        self.assertEqual(ap["ancien"]["skills"], 1)
        self.assertIn("skills/ : 1 fiche(s)", ap["lus"], "les skills lus par Lutin sont dits")
        self.assertGreaterEqual(ap["fichiers"], 3)

    def test_apercu_d_un_dossier_ordinaire(self):
        d = self.tmp / "notes"
        d.mkdir()
        (d / "CLAUDE.md").write_text("consignes", encoding="utf-8")
        (d / "donnees").mkdir()                                     # un dossier « donnees » sans conversation n'est pas un ancien assistant
        ap = espaces.apercu_travail(self.ajouter(d)["id"])
        self.assertIsNone(ap["ancien"])
        self.assertIn("CLAUDE.md", " ".join(ap["lus"]))

    def test_apercu_d_un_dossier_disparu_dit_pourquoi(self):
        d = self.tmp / "parti"
        d.mkdir()
        t = self.ajouter(d)
        d.rmdir()
        self.assertIn("n'existe pas", espaces.apercu_travail(t["id"])["erreur"])

    def test_retirer_avec_nettoyage_ne_supprime_que_les_copies(self):
        d = self.tmp / "projet2"
        (d / "conversations-lutin").mkdir(parents=True)
        (d / "conversations-lutin" / "a.md").write_text("x", encoding="utf-8")
        (d / "vrai.txt").write_text("à garder", encoding="utf-8")
        t = self.ajouter(d)
        self.assertEqual(espaces.apercu_travail(t["id"])["copies"], 1)
        r = espaces.retirer_travail(t["id"], nettoyer=True)
        self.assertEqual(r["copies_supprimees"], 1)
        self.assertFalse((d / "conversations-lutin").exists())
        self.assertTrue((d / "vrai.txt").is_file(), "aucun fichier à toi n'est touché")

    def test_retirer_sans_nettoyage_garde_tout(self):
        d = self.tmp / "projet3"
        (d / "conversations-lutin").mkdir(parents=True)
        (d / "conversations-lutin" / "a.md").write_text("x", encoding="utf-8")
        t = self.ajouter(d)
        self.assertEqual(espaces.retirer_travail(t["id"])["copies_supprimees"], 0)
        self.assertTrue((d / "conversations-lutin" / "a.md").is_file())


class Emplacements(unittest.TestCase):
    def setUp(self):
        self.ancien = os.environ.pop("OLLAMA_MODELS", None)
        self.addCleanup(lambda: os.environ.pop("OLLAMA_MODELS", None) if self.ancien is None else os.environ.__setitem__("OLLAMA_MODELS", self.ancien))
        self.addCleanup(lambda: Path(os.environ["LUTIN_CONFIG"]).unlink(missing_ok=True))

    def test_null_et_vide_comptent_comme_absents(self):
        for valeur in (None, "", "null", "  "):
            Path(os.environ["LUTIN_CONFIG"]).write_text(json.dumps({"emplacements": {"modeles": valeur}}), encoding="utf-8")
            self.assertEqual(emplacements.lire_config_modeles(), "", repr(valeur))
        self.assertEqual(emplacements.dossier_modeles(), Path.home() / ".ollama" / "models")

    def test_changer_le_dossier_des_modeles(self):
        nouveau = _TEMP / "modeles-ollama"
        if os.name == "nt":
            from unittest import mock
            with mock.patch("lutin.installation.definir_variables_utilisateur") as definir:
                p = emplacements.definir_dossier_modeles(str(nouveau))
            definir.assert_called_once()
        else:
            p = emplacements.definir_dossier_modeles(str(nouveau))
        self.assertEqual(p, nouveau)
        self.assertTrue(nouveau.is_dir())
        self.assertEqual(emplacements.lire_config_modeles(), str(nouveau))
        self.assertEqual(emplacements.dossier_modeles(), nouveau)
        with self.assertRaises(ValueError):
            emplacements.definir_dossier_modeles("relatif/chemin")
        with self.assertRaises(ValueError):
            emplacements.definir_dossier_modeles("")

    def test_la_liste_montre_tous_les_emplacements(self):
        r = emplacements.lister()
        cles = [x["cle"] for x in r["lignes"]]
        for attendu in ("programme", "config", "donnees", "memoire", "cache", "modeles"):
            self.assertIn(attendu, cles)
        for ligne in r["lignes"]:
            self.assertTrue(ligne["chemin"] and ligne["explication"])
        self.assertIn("libre", (emplacements.jauge_modeles() or {"libre": 0}))


if __name__ == "__main__":
    unittest.main()
