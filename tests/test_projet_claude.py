"""Un projet Claude (CLAUDE.md, .claude/) comme contexte : détection, imports, copie, consignes du modèle, rappel, API et ligne de commande."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-claude-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")
for d in ("projet", "donnees", "memoire", "config"):
    (_TEMP / d).mkdir(exist_ok=True)
(_TEMP / "config" / "config.json").write_text(json.dumps({"schema": 1, "installe": True, "emplacements": {"travail": str(_TEMP / "projet"), "travaux": [], "travail_actif": ""}}), encoding="utf-8")

from lutin import cli, config, projet_claude  # noqa: E402
from lutin import moteur as A  # noqa: E402


def fabriquer(racine):
    """Un dépôt « homelab » : CLAUDE.md avec un import, un skill, des commandes (dont une dans un sous-dossier), un agent, une règle, un dossier lourd et un .git."""
    racine = Path(racine)
    (racine / ".claude" / "skills" / "deploy").mkdir(parents=True)
    (racine / ".claude" / "commands" / "infra").mkdir(parents=True)
    (racine / ".claude" / "agents").mkdir(parents=True)
    (racine / ".claude" / "rules").mkdir(parents=True)
    (racine / "docs").mkdir()
    (racine / "node_modules" / "x").mkdir(parents=True)
    (racine / ".git").mkdir()
    (racine / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (racine / "CLAUDE.md").write_text("# Homelab\nTout tourne sous Proxmox.\n@docs/reseau.md\n@../secret.md\n", encoding="utf-8")
    (racine / "docs" / "reseau.md").write_text("Le LAN est en 192.168.1.0/24.", encoding="utf-8")
    (_TEMP / "secret.md").write_text("MOT DE PASSE", encoding="utf-8")
    (racine / ".claude" / "skills" / "deploy" / "SKILL.md").write_text("---\nname: deploiement\ndescription: >\n  Déployer un service\n  sur le cluster\n---\nÉtapes...\n", encoding="utf-8")
    (racine / ".claude" / "commands" / "sauvegarde.md").write_text("---\ndescription: Lancer la sauvegarde\n---\nFais la sauvegarde de $ARGUMENTS", encoding="utf-8")
    (racine / ".claude" / "commands" / "infra" / "dns.md").write_text("# Mettre à jour le DNS\n", encoding="utf-8")
    (racine / ".claude" / "agents" / "revue.md").write_text("---\nname: revue\ndescription: Relit les changements\n---\n", encoding="utf-8")
    (racine / ".claude" / "rules" / "style.md").write_text("Pas de tabulations.", encoding="utf-8")
    (racine / "node_modules" / "x" / "gros.js").write_text("x" * 1000, encoding="utf-8")
    return racine


class Detection(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.depot = fabriquer(Path(self.t.name) / "homelab")

    def tearDown(self):
        self.t.cleanup()

    def test_en_tete_markdown(self):
        self.assertEqual(projet_claude.frontmatter("---\nname: a\ndescription: \"Un texte\"\n---\ncorps"), {"name": "a", "description": "Un texte"})
        self.assertEqual(projet_claude.frontmatter("---\ndescription: >\n  deux\n  lignes\n---\n")["description"], "deux lignes")
        self.assertEqual(projet_claude.frontmatter("pas d'en-tête"), {})
        self.assertEqual(projet_claude.frontmatter("---\nnon refermé"), {"non refermé": ""} if False else {})

    def test_detecte_tout_ce_qui_est_utile(self):
        d = projet_claude.detecter(self.depot)
        self.assertEqual(d["contexte"], ["CLAUDE.md"])
        self.assertEqual([(s["nom"], s["description"], s["chemin"]) for s in d["skills"]], [("deploiement", "Déployer un service sur le cluster", ".claude/skills/deploy/SKILL.md")])
        self.assertEqual({c["nom"]: c["description"] for c in d["commandes"]}, {"sauvegarde": "Lancer la sauvegarde", "infra:dns": "Mettre à jour le DNS"})
        self.assertEqual([a["nom"] for a in d["agents"]], ["revue"])
        self.assertEqual(d["regles"], [".claude/rules/style.md"])
        self.assertEqual(projet_claude.resume(d), "CLAUDE.md, 1 skill(s), 2 commande(s), 1 agent(s), 1 règle(s)")

    def test_un_dossier_ordinaire_n_est_pas_un_projet_claude(self):
        vide = Path(self.t.name) / "vide"
        vide.mkdir()
        self.assertTrue(projet_claude.est_vide(projet_claude.detecter(vide)))
        self.assertTrue(projet_claude.est_vide(projet_claude.detecter(Path(self.t.name) / "absent")))
        self.assertEqual(projet_claude.bloc_prompt(vide), "")

    def test_les_imports_restent_dans_le_projet(self):
        texte = projet_claude.texte_contexte(self.depot)
        self.assertIn("Tout tourne sous Proxmox.", texte)
        self.assertIn("[docs/reseau.md]\nLe LAN est en 192.168.1.0/24.", texte)
        self.assertNotIn("MOT DE PASSE", texte, "un import qui sort du projet est ignoré")
        self.assertLessEqual(len(projet_claude.texte_contexte(self.depot, 40)), 40)

    def test_le_morceau_de_consignes_dans_les_deux_langues(self):
        fr = projet_claude.bloc_prompt(self.depot)
        self.assertIn("# PROJET CLAUDE", fr)
        self.assertIn(".claude/skills/deploy/SKILL.md (deploiement) : Déployer un service sur le cluster", fr)
        self.assertIn("(infra:dns)", fr)
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            en = projet_claude.bloc_prompt(self.depot)
        self.assertIn("# CLAUDE PROJECT", en)
        self.assertIn("## Commands (.claude/commands)", en)
        self.assertNotIn("PROJET CLAUDE", en)


class Copie(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.depot = fabriquer(Path(self.t.name) / "homelab")

    def tearDown(self):
        self.t.cleanup()

    def test_la_copie_garde_l_historique_et_saute_les_dossiers_lourds(self):
        vers = Path(self.t.name) / "copie"
        projet_claude.copier(self.depot, vers)
        self.assertTrue((vers / "CLAUDE.md").is_file())
        self.assertTrue((vers / ".claude" / "skills" / "deploy" / "SKILL.md").is_file())
        self.assertTrue((vers / ".git" / "HEAD").is_file())
        self.assertFalse((vers / "node_modules").exists())
        self.assertTrue((self.depot / "node_modules" / "x" / "gros.js").is_file(), "l'original n'est pas touché")

    def test_refus_clairs(self):
        base = Path(self.t.name)
        (base / "plein").mkdir()
        (base / "plein" / "a.txt").write_text("a", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "pas vide"):
            projet_claude.copier(self.depot, base / "plein")
        with self.assertRaisesRegex(ValueError, "dans le projet"):
            projet_claude.copier(self.depot, self.depot / "sous" / "copie")
        with self.assertRaisesRegex(ValueError, "dans le projet"):
            projet_claude.copier(self.depot, base)
        with self.assertRaisesRegex(ValueError, "n'existe pas"):
            projet_claude.copier(base / "absent", base / "x")
        with mock.patch.object(projet_claude, "COPIE_MAX_OCTETS", 100):
            with self.assertRaisesRegex(ValueError, "trop gros"):
                projet_claude.copier(self.depot, base / "gros")
        self.assertFalse((base / "gros").exists())


class DansLeMoteur(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.depot = fabriquer(Path(self.t.name) / "homelab")
        self.avant = A.RACINE
        A.definir_racine(str(self.depot))

    def tearDown(self):
        A.definir_racine(str(self.avant))
        self.t.cleanup()

    def test_les_consignes_du_modele_contiennent_le_projet(self):
        consignes = A.consignes_systeme(A.reglages())
        self.assertIn("# PROJET CLAUDE", consignes)
        self.assertIn("Tout tourne sous Proxmox.", consignes)
        self.assertIn("Déployer un service sur le cluster", consignes)

    def test_le_rappel_cherche_dans_claude_md_et_dans_le_dossier_claude(self):
        noms = {p.relative_to(self.depot).as_posix() for p in A.sources_rappel() if self.depot in p.parents}
        self.assertTrue({"CLAUDE.md", ".claude/skills/deploy/SKILL.md", ".claude/commands/sauvegarde.md", ".claude/rules/style.md"} <= noms, noms)

    def test_le_modele_peut_lire_un_skill_du_projet(self):
        self.assertIn("Étapes...", A.outil_lire(".claude/skills/deploy/SKILL.md"))

    def test_import_sur_place_puis_copie_par_l_api(self):
        autre = fabriquer(Path(self.t.name) / "autre")
        r = A.importer_projet_claude(str(autre), "ici")
        self.assertEqual((r["mode"], r["actif"], Path(r["chemin"]).resolve()), ("ici", True, autre.resolve()))
        self.assertEqual(Path(A.RACINE).resolve(), autre.resolve())
        self.assertIn("1 skill(s)", r["resume"])
        copie = Path(self.t.name) / "ma-copie"
        r = A.importer_projet_claude(str(self.depot), "copie", str(copie), "Copie du homelab")
        self.assertEqual(Path(r["chemin"]).resolve(), copie.resolve())
        self.assertTrue((copie / "CLAUDE.md").is_file())
        self.assertIn("Copie du homelab", [t["nom"] for t in r["travaux"]["liste"]])
        self.assertEqual(Path(A.RACINE).resolve(), copie.resolve(), "le dossier copié devient le dossier actif")

    def test_refus_de_l_api(self):
        with self.assertRaisesRegex(ValueError, "n'existe pas"):
            A.importer_projet_claude(str(Path(self.t.name) / "absent"), "ici")
        ordinaire = Path(self.t.name) / "ordinaire"
        ordinaire.mkdir()
        with self.assertRaisesRegex(ValueError, "pas un projet Claude"):
            A.importer_projet_claude(str(ordinaire), "ici")
        with self.assertRaisesRegex(ValueError, "Mode inconnu"):
            A.importer_projet_claude(str(self.depot), "fusion")


class LigneDeCommande(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LUTIN_HOME": str(Path(self.t.name) / "home"), "LUTIN_LANGUE": "fr"})
        self.env.start()
        os.environ.pop("LUTIN_CONFIG", None)
        self.depot = fabriquer(Path(self.t.name) / "homelab")

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def lancer(self, *argv, reponse=None):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            if reponse is None:
                code = cli.principal(list(argv))
            else:
                args = cli.parseur().parse_args(list(argv))
                code = cli.commande_importer(args, entree=lambda invite: reponse)
        return code, sortie.getvalue()

    def travaux(self):
        return config.charger(config.dossiers())["emplacements"]["travaux"]

    def test_copie_demandee(self):
        vers = Path(self.t.name) / "copie"
        code, sortie = self.lancer("importer", str(self.depot), "--copie", "--vers", str(vers))
        self.assertEqual(code, 0, sortie)
        self.assertIn("Trouvé dans", sortie)
        self.assertIn("1 skill(s)", sortie)
        self.assertTrue((vers / "CLAUDE.md").is_file())
        self.assertEqual([Path(t["chemin"]).resolve() for t in self.travaux()], [vers.resolve()])

    def test_sur_place_demande(self):
        code, sortie = self.lancer("importer", str(self.depot), "--ici", "--nom", "Homelab")
        self.assertEqual(code, 0, sortie)
        self.assertEqual([(t["nom"], Path(t["chemin"]).resolve()) for t in self.travaux()], [("Homelab", self.depot.resolve())])

    def test_question_posee_et_copie_par_defaut(self):
        vers = Path(self.t.name) / "copie2"
        code, sortie = self.lancer("importer", str(self.depot), "--vers", str(vers), reponse="")
        self.assertEqual(code, 0, sortie)
        self.assertIn("[conseillé]", sortie)
        self.assertTrue((vers / "CLAUDE.md").is_file(), "sans réponse : la copie, qui ne touche pas à l'original")
        code, sortie = self.lancer("importer", str(self.depot), reponse="2")
        self.assertEqual(code, 0, sortie)
        self.assertIn(self.depot.resolve(), [Path(t["chemin"]).resolve() for t in self.travaux()])

    def test_erreurs(self):
        self.assertEqual(self.lancer("importer", str(Path(self.t.name) / "absent"), "--ici")[0], 2)
        ordinaire = Path(self.t.name) / "ordinaire"
        ordinaire.mkdir()
        code, sortie = self.lancer("importer", str(ordinaire), "--ici")
        self.assertEqual(code, 2)
        self.assertIn("pas un projet Claude", sortie)
        self.assertEqual(self.travaux(), [])
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            code, sortie = self.lancer("importer", str(ordinaire), "--ici")
        self.assertIn("is not a Claude project", sortie)


if __name__ == "__main__":
    unittest.main()
