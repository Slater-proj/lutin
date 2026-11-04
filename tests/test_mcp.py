"""Client MCP : un serveur de démonstration lancé en local apparaît, est autorisé outil par outil, et le refus est respecté."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-mcp-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import mcp, modes, revue  # noqa: E402
from lutin import moteur as _m  # noqa: E402

SRC = str(Path(__file__).resolve().parent.parent / "src")
NOTES = _TEMP / "notes.txt"


def contexte(accorde=True):
    demandes = []

    def accord(titre, detail, diff, auto=False):
        demandes.append((titre, detail, auto))
        return accorde
    return {"accord": accord, "demandes": demandes, "stop": threading.Event(), "identite": "test"}


class Mcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mcp.ecrire({"serveurs": {}})
        cls.ident = mcp.ajouter("Démonstration", [sys.executable, "-m", "lutin.mcp_demo"], env={"PYTHONPATH": SRC, "LUTIN_DEMO_FICHIER": str(NOTES)})
        cls.nombre = mcp.actualiser(cls.ident)

    @classmethod
    def tearDownClass(cls):
        mcp.fermer()

    def setUp(self):
        mcp.regler(self.ident, lecture_seule=True)
        for o in ("heure", "additionner", "noter"):
            mcp.regler(self.ident, outil=o, autorise=False)
        NOTES.unlink(missing_ok=True)

    def test_le_serveur_apparait_avec_ses_outils_mais_aucun_n_est_donne_au_modele(self):
        self.assertEqual(self.ident, "demonstration")
        self.assertEqual(self.nombre, 3)
        v = mcp.vue()[0]
        self.assertEqual({o["nom"]: o["lecture"] for o in v["outils"]}, {"heure": True, "additionner": True, "noter": False})
        self.assertEqual(mcp.outils_exposes(), [], "rien n'est autorisé : rien n'est proposé")
        self.assertNotIn(SRC.replace(chr(92), chr(92) * 2), json.dumps(v), "les valeurs d'environnement (secrets) ne sortent pas, seulement leurs noms")
        self.assertEqual(v["cles_env"], ["LUTIN_DEMO_FICHIER", "PYTHONPATH"])

    def test_autorisation_outil_par_outil_et_lecture_seule(self):
        mcp.regler(self.ident, outil="heure", autorise=True)
        mcp.regler(self.ident, outil="noter", autorise=True)
        noms = [t["function"]["name"] for t in mcp.outils_exposes()]
        self.assertEqual(noms, ["mcp__demonstration__heure"], "lecture seule par défaut : « noter » modifie quelque chose, il n'est pas proposé")
        mcp.regler(self.ident, lecture_seule=False)
        self.assertEqual({t["function"]["name"] for t in mcp.outils_exposes()}, {"mcp__demonstration__heure", "mcp__demonstration__noter"})
        self.assertEqual([t["function"]["name"] for t in mcp.outils_exposes(mode_lecture_seulement=True)], ["mcp__demonstration__heure"], "le mode « recherche » ne garde que la lecture")

    def test_appel_en_lecture_resultat_non_fiable_et_accord_automatique_suspendu(self):
        mcp.regler(self.ident, outil="additionner", autorise=True)
        ctx = contexte()
        r = revue.appeler_outil("mcp__demonstration__additionner", {"a": 2, "b": 3}, ctx)
        self.assertIn(mcp.MARQUEUR, r[:80])
        self.assertIn("5.0", r)
        self.assertTrue(ctx["web_lu"], "après un appel externe, l'accord automatique est suspendu")
        self.assertEqual(ctx["demandes"], [], "une lecture ne demande pas d'accord")

    def test_un_outil_non_autorise_n_est_pas_appelable(self):
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("mcp__demonstration__heure", {}, contexte())

    def test_le_refus_est_respecte(self):
        mcp.regler(self.ident, lecture_seule=False)
        mcp.regler(self.ident, outil="noter", autorise=True)
        ctx = contexte(accorde=False)
        r = revue.appeler_outil("mcp__demonstration__noter", {"texte": "ne doit pas exister"}, ctx)
        self.assertIn("Refusé", r)
        self.assertFalse(NOTES.exists(), "refusé : rien n'a été écrit par le connecteur")
        self.assertEqual(len(ctx["demandes"]), 1)
        self.assertFalse(ctx["demandes"][0][2], "jamais d'accord automatique pour un connecteur")

    def test_accord_donne_action_faite_et_journalisee(self):
        mcp.regler(self.ident, lecture_seule=False)
        mcp.regler(self.ident, outil="noter", autorise=True)
        r = revue.appeler_outil("mcp__demonstration__noter", {"texte": "bonjour"}, contexte(accorde=True))
        self.assertIn(mcp.MARQUEUR, r[:80])
        self.assertEqual(NOTES.read_text(encoding="utf-8"), "bonjour\n")
        journal = _m.lire_journal(20)
        self.assertIn("mcp__demonstration__noter", json.dumps(journal, ensure_ascii=False))

    def test_lecture_seule_refuse_meme_un_appel_force(self):
        mcp.regler(self.ident, outil="noter", autorise=True)
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("mcp__demonstration__noter", {"texte": "x"}, contexte())
        self.assertFalse(NOTES.exists())

    def test_programme_introuvable_et_mauvaises_entrees(self):
        ident = mcp.ajouter("Fantôme", ["programme-qui-n-existe-pas-xyz"])
        with self.assertRaises(ValueError) as e:
            mcp.actualiser(ident)
        self.assertIn("introuvable", str(e.exception))
        mcp.supprimer(ident)
        with self.assertRaises(ValueError):
            mcp.ajouter("Deux", ["a"], url="http://x")
        with self.assertRaises(ValueError):
            mcp.ajouter("Sans", None)
        with self.assertRaises(ValueError):
            mcp.ajouter("Web", url="ftp://x")
        with self.assertRaises(ValueError):
            mcp.ajouter("Démonstration", ["a"])

    def test_modes(self):
        self.assertTrue(modes.sans_outils("discussion"))
        self.assertTrue(modes.lecture_seule("recherche"))
        self.assertFalse(modes.lecture_seule("technique"))

    def test_noms(self):
        self.assertEqual(mcp.analyser_nom("mcp__home_assistant__turn_on-light"), ("home_assistant", "turn_on-light"))
        self.assertEqual(mcp.analyser_nom("lire"), (None, None))


if __name__ == "__main__":
    unittest.main()
