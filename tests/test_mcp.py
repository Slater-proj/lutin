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

from lutin import mcp, modes, change_review  # noqa: E402
from lutin import core as _m  # noqa: E402

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
        mcp.write({"serveurs": {}})
        cls.ident = mcp.add("Démonstration", [sys.executable, "-m", "lutin.mcp_demo"], env={"PYTHONPATH": SRC, "LUTIN_DEMO_FICHIER": str(NOTES)})
        cls.nombre = mcp.refresh(cls.ident)

    @classmethod
    def tearDownClass(cls):
        mcp.close()

    def setUp(self):
        mcp.set_value(self.ident, lecture_seule=True)
        for o in ("heure", "additionner", "noter"):
            mcp.set_value(self.ident, outil=o, autorise=False)
        NOTES.unlink(missing_ok=True)

    def test_le_serveur_apparait_avec_ses_outils_mais_aucun_n_est_donne_au_modele(self):
        self.assertEqual(self.ident, "demonstration")
        self.assertEqual(self.nombre, 3)
        v = mcp.view()[0]
        self.assertEqual({o["nom"]: o["lecture"] for o in v["outils"]}, {"heure": True, "additionner": True, "noter": False})
        self.assertEqual(mcp.exposed_tools(), [], "rien n'est autorisé : rien n'est proposé")
        self.assertNotIn(SRC.replace(chr(92), chr(92) * 2), json.dumps(v), "les valeurs d'environnement (secrets) ne sortent pas, seulement leurs noms")
        self.assertEqual(v["cles_env"], ["LUTIN_DEMO_FICHIER", "PYTHONPATH"])

    def test_autorisation_outil_par_outil_et_lecture_seule(self):
        mcp.set_value(self.ident, outil="heure", autorise=True)
        mcp.set_value(self.ident, outil="noter", autorise=True)
        noms = [t["function"]["name"] for t in mcp.exposed_tools()]
        self.assertEqual(noms, ["mcp__demonstration__heure"], "lecture seule par défaut : « noter » modifie quelque chose, il n'est pas proposé")
        mcp.set_value(self.ident, lecture_seule=False)
        self.assertEqual({t["function"]["name"] for t in mcp.exposed_tools()}, {"mcp__demonstration__heure", "mcp__demonstration__noter"})
        self.assertEqual([t["function"]["name"] for t in mcp.exposed_tools(mode_lecture_seulement=True)], ["mcp__demonstration__heure"], "le mode « recherche » ne garde que la lecture")

    def test_appel_en_lecture_resultat_non_fiable_et_accord_automatique_suspendu(self):
        mcp.set_value(self.ident, outil="additionner", autorise=True)
        ctx = contexte()
        r = change_review.call_tool("mcp__demonstration__additionner", {"a": 2, "b": 3}, ctx)
        self.assertIn(mcp.MARKER, r[:80])
        self.assertIn("5.0", r)
        self.assertTrue(ctx["web_lu"], "après un appel externe, l'accord automatique est suspendu")
        self.assertEqual(ctx["demandes"], [], "une lecture ne demande pas d'accord")

    def test_un_outil_non_autorise_n_est_pas_appelable(self):
        with self.assertRaises(_m.ErreurOutil):
            change_review.call_tool("mcp__demonstration__heure", {}, contexte())

    def test_le_refus_est_respecte(self):
        mcp.set_value(self.ident, lecture_seule=False)
        mcp.set_value(self.ident, outil="noter", autorise=True)
        ctx = contexte(accorde=False)
        r = change_review.call_tool("mcp__demonstration__noter", {"texte": "ne doit pas exister"}, ctx)
        self.assertIn("Refusé", r)
        self.assertFalse(NOTES.exists(), "refusé : rien n'a été écrit par le connecteur")
        self.assertEqual(len(ctx["demandes"]), 1)
        self.assertFalse(ctx["demandes"][0][2], "jamais d'accord automatique pour un connecteur")

    def test_accord_donne_action_faite_et_journalisee(self):
        mcp.set_value(self.ident, lecture_seule=False)
        mcp.set_value(self.ident, outil="noter", autorise=True)
        r = change_review.call_tool("mcp__demonstration__noter", {"texte": "bonjour"}, contexte(accorde=True))
        self.assertIn(mcp.MARKER, r[:80])
        self.assertEqual(NOTES.read_text(encoding="utf-8"), "bonjour\n")
        journal = _m.lire_journal(20)
        self.assertIn("mcp__demonstration__noter", json.dumps(journal, ensure_ascii=False))

    def test_lecture_seule_refuse_meme_un_appel_force(self):
        mcp.set_value(self.ident, outil="noter", autorise=True)
        with self.assertRaises(_m.ErreurOutil):
            change_review.call_tool("mcp__demonstration__noter", {"texte": "x"}, contexte())
        self.assertFalse(NOTES.exists())

    def test_programme_introuvable_et_mauvaises_entrees(self):
        ident = mcp.add("Fantôme", ["programme-qui-n-existe-pas-xyz"])
        with self.assertRaises(ValueError) as e:
            mcp.refresh(ident)
        self.assertIn("introuvable", str(e.exception))
        mcp.remove(ident)
        with self.assertRaises(ValueError):
            mcp.add("Deux", ["a"], url="http://x")
        with self.assertRaises(ValueError):
            mcp.add("Sans", None)
        with self.assertRaises(ValueError):
            mcp.add("Web", url="ftp://x")
        with self.assertRaises(ValueError):
            mcp.add("Démonstration", ["a"])

    def test_la_ligne_de_commande_ajoute_actualise_autorise_et_retire(self):
        """Dans Docker la page ne peut pas modifier les connecteurs : `lutin mcp …` le fait."""
        import contextlib
        import io
        from lutin import cli
        ancienne = mcp.read()
        self.addCleanup(lambda: mcp.write(ancienne))
        def commande(action, nom=None, cible=None, env=()):
            with contextlib.redirect_stdout(io.StringIO()) as sortie:
                code = cli.commande_mcp(type("A", (), {"action": action, "nom": nom, "cible": cible, "env": list(env)})())
            return code, sortie.getvalue()
        code, texte = commande("lister")
        self.assertEqual(code, 0)
        self.assertIn("demonstration", texte)
        code, texte = commande("ajouter", "Autre", "https://exemple.org/mcp")
        self.assertEqual(code, 0)
        self.assertIn("autre", texte)
        self.assertEqual(mcp.read()["serveurs"]["autre"]["type"], "http")
        code, texte = commande("ajouter", "Autre", "https://exemple.org/mcp")
        self.assertEqual(code, 1, "un nom déjà pris est refusé")
        code, texte = commande("retirer", "Autre")
        self.assertEqual(code, 0)
        self.assertNotIn("autre", mcp.read()["serveurs"])
        code, texte = commande("autoriser", "Démonstration", "heure")
        self.assertEqual(code, 0)
        self.assertTrue(mcp.read()["serveurs"]["demonstration"]["outils"]["heure"]["autorise"])
        commande("interdire", "Démonstration", "heure")

    def test_les_cles_d_acces_se_valident_se_remplacent_et_ne_sortent_jamais(self):
        ident = mcp.add("Distant", url="http://127.0.0.1:9/mcp", env={}, entetes={"Authorization": "Bearer secret-123"})
        try:
            v = [x for x in mcp.view() if x["id"] == ident][0]
            self.assertEqual(v["cles_entetes"], ["Authorization"])
            self.assertNotIn("secret-123", json.dumps(mcp.view()), "la valeur d'un en-tête ne sort jamais")
            mcp.set_value(ident, env={"TOKEN": "abc"})          # remplace les variables, les en-têtes restent
            v = [x for x in mcp.view() if x["id"] == ident][0]
            self.assertEqual((v["cles_env"], v["cles_entetes"]), (["TOKEN"], ["Authorization"]))
            mcp.set_value(ident, env={}, entetes={})
            v = [x for x in mcp.view() if x["id"] == ident][0]
            self.assertEqual((v["cles_env"], v["cles_entetes"]), ([], []))
            for mauvais in ({"env": {"a b": "x"}}, {"env": {"A": "ligne1\nligne2"}}, {"entetes": {"X Y": "1"}}, {"entetes": {"Authorization": "a\r\nb: c"}}, {"env": {str(i): "x" for i in range(31)}}):
                with self.assertRaises(ValueError, msg=str(mauvais)[:40]):
                    mcp.set_value(ident, **mauvais)
            with self.assertRaises(ValueError):
                mcp.add("Mauvais", url="http://127.0.0.1:9/mcp", entetes={"X\nY": "1"})
        finally:
            mcp.remove(ident)

    def test_modes(self):
        self.assertTrue(modes.without_tools("discussion"))
        self.assertTrue(modes.read_only("recherche"))
        self.assertFalse(modes.read_only("technique"))

    def test_noms(self):
        self.assertEqual(mcp.parse_name("mcp__home_assistant__turn_on-light"), ("home_assistant", "turn_on-light"))
        self.assertEqual(mcp.parse_name("lire"), (None, None))


class Limite(unittest.TestCase):
    def test_les_outils_au_dela_de_la_limite_sont_comptes_pas_ecartes_en_silence(self):
        """Au-delà de OUTILS_MAX outils autorisés, le modèle n'en reçoit que les premiers : la page dit combien sont écartés."""
        avant = mcp.read()
        outils = {"outil%02d" % i: {"description": "x", "schema": {}, "lecture": True, "autorise": True} for i in range(mcp.MAX_TOOLS + 7)}
        try:
            mcp.write({"serveurs": {"gros": {"nom": "Gros", "type": "stdio", "commande": ["x"], "actif": True, "lecture_seule": True, "outils": outils}}})
            self.assertEqual(len(mcp.exposed_tools()), mcp.MAX_TOOLS)
            self.assertEqual(mcp.limit_tools(), {"max": mcp.MAX_TOOLS, "exposables": mcp.MAX_TOOLS + 7, "ecartes": 7})
        finally:
            mcp.write(avant)
        self.assertEqual(mcp.limit_tools()["ecartes"], 0)


if __name__ == "__main__":
    unittest.main()
