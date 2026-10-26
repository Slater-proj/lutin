"""Reprendre les données d'un autre assistant : choix par catégorie, rien d'écrasé, archives sûres, réglages dangereux jamais repris."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-reprise-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")
for d in ("projet", "donnees", "memoire", "config"):
    (_TEMP / d).mkdir(exist_ok=True)
(_TEMP / "config" / "config.json").write_text(json.dumps({"schema": 1, "installe": True, "emplacements": {"travail": str(_TEMP / "projet"), "travaux": [], "travail_actif": ""}}), encoding="utf-8")

from lutin import cli, reprise, sauvegarde  # noqa: E402
from lutin import moteur as A  # noqa: E402


def conversation(ident, titre="Une conversation", **plus):
    return dict({"id": ident, "titre": titre, "date": "2026-10-01T10:00:00", "maj": "2026-10-02T10:00:00.000", "resume": "", "messages": [{"role": "user", "content": "bonjour"}]}, **plus)


def ancien_assistant(base):
    """Un dossier d'assistant comme l'ancien : donnees/, memoire/ et skills/ dans le dossier du projet, au-dessus."""
    base = Path(base)
    projet = base / "projet"
    assistant = projet / "assistant"
    (assistant / "donnees" / "conversations").mkdir(parents=True)
    (assistant / "memoire").mkdir()
    (projet / "skills").mkdir()
    c = assistant / "donnees" / "conversations"
    (c / "a1b2c3d4.json").write_text(json.dumps(conversation("a1b2c3d4", "Première", annulable={"fichiers": ["x"]}, travail="inconnu")), encoding="utf-8")
    (c / "b2c3d4e5.json").write_text(json.dumps(conversation("b2c3d4e5", "Deuxième")), encoding="utf-8")
    (c / "b2c3d4e5.json.bak").write_text("{}", encoding="utf-8")
    (c / "cassee.json").write_text("{pas du json", encoding="utf-8")
    (c / "mauvais.json").write_text(json.dumps({"id": "../evil", "messages": []}), encoding="utf-8")
    (assistant / "donnees" / "reglages.json").write_text(json.dumps({"modele": "huihui_ai/Qwen3.8-abliterated:27b", "num_ctx": 32768, "temperature": 0.7, "auto_ecriture": True,
                                                                     "auto_commandes": True, "avance": True, "tours_max": 20, "inconnu": 1}), encoding="utf-8")
    (assistant / "memoire" / "CONTEXTE.md").write_text("# Mon contexte\nJe fais un jeu.\n", encoding="utf-8")
    (assistant / "memoire" / "MEMOIRE.md").write_text("# Notes\n- une note\n", encoding="utf-8")
    (projet / "skills" / "univers.md").write_text("# Univers\n", encoding="utf-8")
    (projet / "skills" / "regles.md").write_text("# Règles\n", encoding="utf-8")
    (projet / "skills" / "pas-un-skill.txt").write_text("x", encoding="utf-8")
    return assistant


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.assistant = ancien_assistant(self.t.name)
        self.lutin = Path(self.t.name) / "lutin"
        self.dossiers = {"config": self.lutin / "config", "donnees": self.lutin / "donnees", "memoire": self.lutin / "memoire", "cache": self.lutin / "cache"}
        for d in self.dossiers.values():
            d.mkdir(parents=True)
        (self.dossiers["config"] / "config.json").write_text("{}", encoding="utf-8")
        self.travail = Path(self.t.name) / "travail"
        self.travail.mkdir()

    def tearDown(self):
        self.t.cleanup()

    def reprendre(self, source=None, choix=reprise.CATEGORIES, **kw):
        with reprise.ouvrir(source or self.assistant) as d:
            return reprise.importer(d, self.dossiers, choix, racine_travail=self.travail, workspaces=kw.pop("workspaces", ()), **kw)


class Detection(Base):
    def test_ce_qui_est_trouve(self):
        with reprise.ouvrir(self.assistant) as d:
            self.assertEqual(reprise.decrire(d), {"conversations": 4, "memoire": ["CONTEXTE.md", "MEMOIRE.md"], "skills": 2, "reglages": True})
            self.assertTrue(d["dossier_skills"].endswith("skills"))

    def test_on_peut_donner_le_dossier_donnees_ou_un_dossier_de_skills(self):
        with reprise.ouvrir(self.assistant / "donnees") as d:
            self.assertEqual(reprise.decrire(d)["conversations"], 4)
            self.assertEqual(reprise.decrire(d)["skills"], 2, "les skills sont cherchés au-dessus de l'assistant")
        autre = Path(self.t.name) / "mes-skills"
        autre.mkdir()
        (autre / "a.md").write_text("# a", encoding="utf-8")
        with reprise.ouvrir(self.assistant, str(autre)) as d:
            self.assertEqual(reprise.decrire(d)["skills"], 1)

    def test_rien_a_reprendre_ou_mauvaise_source(self):
        vide = Path(self.t.name) / "vide"
        vide.mkdir()
        with self.assertRaisesRegex(reprise.ErreurReprise, "Rien à reprendre"):
            reprise.ouvrir(vide).__enter__()
        with self.assertRaisesRegex(reprise.ErreurReprise, "n'existe pas"):
            reprise.ouvrir(Path(self.t.name) / "absent").__enter__()
        texte = Path(self.t.name) / "a.txt"
        texte.write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(reprise.ErreurReprise, "archive .zip"):
            reprise.ouvrir(texte).__enter__()


class Import(Base):
    def test_tout_reprendre(self):
        r = self.reprendre()
        self.assertEqual(r["conversations"], {"importees": 2, "deja_presentes": 0, "illisibles": 2})
        c = json.loads((self.dossiers["donnees"] / "conversations" / "a1b2c3d4.json").read_text(encoding="utf-8"))
        self.assertEqual(c["titre"], "Première")
        self.assertEqual(c["maj"], "2026-10-02T10:00:00.000", "les dates d'origine sont gardées : l'ordre des conversations ne change pas")
        self.assertNotIn("annulable", c)
        self.assertNotIn("travail", c, "un dossier de travail inconnu ici est oublié")
        self.assertFalse((self.dossiers["donnees"] / "conversations" / "b2c3d4e5.json.bak").exists())
        self.assertEqual(sorted(p.name for p in (self.travail / "skills").iterdir()), ["regles.md", "univers.md"])
        self.assertEqual((self.dossiers["memoire"] / "CONTEXTE.md").read_text(encoding="utf-8"), "# Mon contexte\nJe fais un jeu.\n")
        self.assertTrue(Path(r["sauvegarde"]).is_file())
        with zipfile.ZipFile(r["sauvegarde"]) as z:
            self.assertIn("manifeste.json", z.namelist())

    def test_un_dossier_de_travail_connu_est_garde(self):
        (self.assistant / "donnees" / "conversations" / "a1b2c3d4.json").write_text(json.dumps(conversation("a1b2c3d4", travail="principal")), encoding="utf-8")
        self.reprendre(choix=("conversations",), workspaces=("principal",))
        importee = self.dossiers["donnees"] / "conversations" / "a1b2c3d4.json"
        self.assertEqual(json.loads(importee.read_text(encoding="utf-8"))["travail"], "principal")

    def test_les_reglages_dangereux_ne_sont_jamais_repris(self):
        r = self.reprendre(choix=("reglages",))
        reglages = json.loads((self.dossiers["donnees"] / "reglages.json").read_text(encoding="utf-8"))
        self.assertEqual(reglages, {"num_ctx": 32768, "temperature": 0.7, "tours_max": 20})
        self.assertEqual(sorted(r["reglages"]["laisses"]), ["auto_commandes", "auto_ecriture", "avance", "modele"])

    def test_les_reglages_existants_sont_completes_pas_remplaces(self):
        (self.dossiers["donnees"] / "reglages.json").write_text(json.dumps({"modele": "qwen3:8b", "web": False}), encoding="utf-8")
        self.reprendre(choix=("reglages",))
        reglages = json.loads((self.dossiers["donnees"] / "reglages.json").read_text(encoding="utf-8"))
        self.assertEqual((reglages["modele"], reglages["web"], reglages["num_ctx"]), ("qwen3:8b", False, 32768))

    def test_seulement_ce_qui_est_choisi(self):
        r = self.reprendre(choix=("skills",))
        self.assertEqual(list(r), ["choix", "sauvegarde", "skills"])
        self.assertEqual(list(self.dossiers["donnees"].glob("conversations/*")), [])
        self.assertFalse((self.dossiers["memoire"] / "CONTEXTE.md").exists())
        with self.assertRaisesRegex(reprise.ErreurReprise, "Rien n'est choisi"):
            self.reprendre(choix=())

    def test_rien_n_est_ecrase_sans_le_dire(self):
        self.reprendre()
        (self.dossiers["donnees"] / "conversations" / "a1b2c3d4.json").write_text(json.dumps(conversation("a1b2c3d4", "Modifiée ici")), encoding="utf-8")
        (self.travail / "skills" / "univers.md").write_text("# Mon univers à moi", encoding="utf-8")
        (self.dossiers["memoire"] / "MEMOIRE.md").write_text("# Notes de Lutin\n- autre chose\n", encoding="utf-8")
        r = self.reprendre()
        self.assertEqual(r["conversations"]["deja_presentes"], 2)
        self.assertEqual(json.loads((self.dossiers["donnees"] / "conversations" / "a1b2c3d4.json").read_text(encoding="utf-8"))["titre"], "Modifiée ici")
        self.assertEqual((self.travail / "skills" / "univers.md").read_text(encoding="utf-8"), "# Mon univers à moi")
        self.assertEqual(len(r["memoire"]["a_cote"]), 1)
        self.assertEqual((self.dossiers["memoire"] / "MEMOIRE.md").read_text(encoding="utf-8"), "# Notes de Lutin\n- autre chose\n")
        self.assertTrue(any(p.name.startswith("MEMOIRE.importe-") for p in self.dossiers["memoire"].iterdir()))
        r = self.reprendre(ecraser=True)
        self.assertEqual(json.loads((self.dossiers["donnees"] / "conversations" / "a1b2c3d4.json").read_text(encoding="utf-8"))["titre"], "Première")
        self.assertEqual((self.travail / "skills" / "univers.md").read_text(encoding="utf-8"), "# Univers\n")

    def test_la_memoire_de_depart_non_touchee_est_remplacee_sans_perte(self):
        from lutin import config as _config
        _config.preparer(self.dossiers)
        self.assertIn("Mémoire de Lutin", (self.dossiers["memoire"] / "MEMOIRE.md").read_text(encoding="utf-8"))
        r = self.reprendre(choix=("memoire",))
        self.assertEqual(sorted(r["memoire"]["posees"]), ["CONTEXTE.md", "MEMOIRE.md"])
        self.assertEqual(r["memoire"]["a_cote"], [])
        self.assertIn("Je fais un jeu", (self.dossiers["memoire"] / "CONTEXTE.md").read_text(encoding="utf-8"))

    def test_skills_refuses_sans_dossier_de_travail_et_noms_dangereux(self):
        with reprise.ouvrir(self.assistant) as d:
            with self.assertRaisesRegex(reprise.ErreurReprise, "Pas de dossier de travail"):
                reprise.importer(d, self.dossiers, ("skills",), racine_travail=None)
        self.assertEqual(reprise.RE_NOM_MD.match("../x.md"), None)
        self.assertEqual(reprise.RE_NOM_MD.match("a/b.md"), None)
        self.assertIsNotNone(reprise.RE_NOM_MD.match("mon skill-2.md"))


class Archives(Base):
    def test_une_sauvegarde_de_lutin_se_reprend(self):
        self.reprendre(choix=("conversations", "memoire", "reglages"))
        archive = Path(self.t.name) / "sauvegarde.zip"
        sauvegarde.exporter({k: self.dossiers[k] for k in ("config", "donnees", "memoire")}, str(archive))
        ailleurs = Path(self.t.name) / "ailleurs"
        self.dossiers = {k: ailleurs / k for k in ("config", "donnees", "memoire", "cache")}
        for d in self.dossiers.values():
            d.mkdir(parents=True)
        (ailleurs / "config" / "config.json").write_text("{}", encoding="utf-8")
        with reprise.ouvrir(archive) as d:
            self.assertEqual(reprise.decrire(d)["conversations"], 2)
            r = reprise.importer(d, self.dossiers, ("conversations", "memoire"), racine_travail=self.travail)
        self.assertEqual(r["conversations"]["importees"], 2)
        self.assertTrue((ailleurs / "memoire" / "MEMOIRE.md").is_file())

    def test_une_archive_qui_sort_de_ses_dossiers_est_refusee(self):
        mauvaise = Path(self.t.name) / "mauvaise.zip"
        with zipfile.ZipFile(mauvaise, "w") as z:
            z.writestr("donnees/conversations/a1b2c3d4.json", json.dumps(conversation("a1b2c3d4")))
            z.writestr("../evil.md", "x")
        with self.assertRaisesRegex(reprise.ErreurReprise, "sortirait"):
            reprise.ouvrir(mauvaise).__enter__()
        absolue = Path(self.t.name) / "absolue.zip"
        with zipfile.ZipFile(absolue, "w") as z:
            z.writestr("/etc/passwd", "x")
        with self.assertRaisesRegex(reprise.ErreurReprise, "sortirait"):
            reprise.ouvrir(absolue).__enter__()
        cassee = Path(self.t.name) / "cassee.zip"
        cassee.write_bytes(b"pas un zip")
        with self.assertRaisesRegex(reprise.ErreurReprise, "pas lisible"):
            reprise.ouvrir(cassee).__enter__()


class DansLeMoteurEtLaLigneDeCommande(Base):
    def test_fonctions_du_moteur(self):
        trouve = A.reprise_detecter(str(self.assistant))
        self.assertEqual((trouve["conversations"], trouve["skills"]), (4, 2))
        avant = A.RACINE
        try:
            A.definir_racine(str(self.travail))
            r = A.reprise_importer(str(self.assistant), ["skills", "conversations"])
        finally:
            A.definir_racine(str(avant))
        self.assertEqual(len(r["skills"]["importes"]), 2)
        self.assertEqual(r["conversations"]["importees"], 2)
        self.assertTrue(any("Conversations" in ligne for ligne in r["resume"]))
        self.assertTrue((_TEMP / "donnees" / "conversations" / "a1b2c3d4.json").is_file())

    def lancer(self, *argv, reponse=None):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            if reponse is None:
                code = cli.principal(list(argv))
            else:
                args = cli.parseur().parse_args(list(argv))
                code = cli.commande_reprendre(args, entree=lambda invite: reponse)
        return code, sortie.getvalue()

    def test_ligne_de_commande(self):
        with mock.patch.dict(os.environ, {"LUTIN_HOME": str(Path(self.t.name) / "home"), "LUTIN_LANGUE": "fr"}):
            os.environ.pop("LUTIN_CONFIG", None)
            code, sortie = self.lancer("reprendre", str(self.assistant), "--skills")
            self.assertEqual(code, 2, "pas de dossier de travail : refusé avant d'écrire quoi que ce soit")
            self.assertEqual(list((Path(self.t.name) / "home").rglob("conversations/*.json")), [])
            self.assertEqual(self.lancer("travaux", "ajouter", str(self.travail))[0], 0)
            code, sortie = self.lancer("reprendre", str(self.assistant), "--conversations", "--skills")
            self.assertEqual(code, 0, sortie)
            self.assertIn("Conversations : 2 reprises", sortie)
            self.assertIn("Skills : 2 repris", sortie)
            code, sortie = self.lancer("reprendre", str(self.assistant), reponse="3")
            self.assertEqual(code, 0, sortie)
            self.assertIn("déjà présents", sortie, "seuls les skills (3) ont été demandés : déjà là")
            self.assertNotIn("Conversations : ", sortie.split("Trouvé dans")[1].split("Skills : ")[-1])
            code, sortie = self.lancer("reprendre", str(self.assistant), "--tout")
            self.assertEqual(code, 0, sortie)
            self.assertIn("Réglages : ", sortie)
            code, sortie = self.lancer("reprendre", str(Path(self.t.name) / "absent"), "--tout")
            self.assertEqual(code, 2)
        with mock.patch.dict(os.environ, {"LUTIN_HOME": str(Path(self.t.name) / "home"), "LUTIN_LANGUE": "en"}):
            os.environ.pop("LUTIN_CONFIG", None)
            code, sortie = self.lancer("reprendre", str(self.assistant), "--memoire")
            self.assertIn("Memory: ", sortie)
            self.assertIn("Before the import, Lutin's state was kept in", sortie)


if __name__ == "__main__":
    unittest.main()
