"""Catalogue MCP : valeurs contrôlées, version exacte, programme absent signalé, connecteur cassé retiré, branchement réel de bout en bout (serveur de démonstration), tout le catalogue cohérent."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-mcpcat-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import mcp, mcp_catalog  # noqa: E402

SRC = str(Path(__file__).resolve().parent.parent / "src")


def chercher_tout(nom):
    return "/usr/bin/" + nom


def chercher_rien(nom):
    return None


class Catalogue(unittest.TestCase):
    def setUp(self):
        mcp.ecrire({"serveurs": {}})

    def test_chaque_entree_est_complete_et_epinglee(self):
        entrees = mcp_catalog.charger()
        self.assertGreaterEqual(len(entrees), 8)
        ids = [e["id"] for e in entrees]
        self.assertEqual(len(ids), len(set(ids)), "pas de doublon")
        for e in entrees:
            self.assertIn(e["execution"], ("npx", "uvx", "http"), e["id"])
            for texte in ("nom", "description"):
                self.assertTrue(e[texte].get("fr") and e[texte].get("en"), (e["id"], texte, "les deux langues"))
            for c in e.get("champs", []):
                self.assertTrue(c["libelle"].get("fr") and c["libelle"].get("en"), (e["id"], c["cle"]))
                self.assertIn(c["type"], ("dossier", "fichier", "url", "secret"))
            if e["execution"] != "http":
                self.assertRegex(e["version"], r"^\d+(\.\d+)+$", "une version exacte, jamais « latest » : " + e["id"])
                self.assertTrue(e["paquet"])
            else:
                self.assertTrue(e["url"].startswith("{"))

    def test_la_commande_porte_la_version_exacte_et_le_chemin_complet(self):
        dossier = str(_TEMP)
        commande, url, entetes = mcp_catalog.construire(mcp_catalog.entree("fichiers"), {"dossiers": dossier + "\n" + dossier}, chercher_tout)
        self.assertEqual(commande[:3], ["/usr/bin/npx", "-y", "@modelcontextprotocol/server-filesystem@2.2.0"])
        self.assertEqual(commande[3:], [dossier, dossier])
        self.assertEqual((url, entetes), ("", {}))
        commande, _, _ = mcp_catalog.construire(mcp_catalog.entree("git"), {"depot": dossier}, chercher_tout)
        self.assertEqual(commande[:4], ["/usr/bin/uv", "tool", "run", "mcp-server-git@2026.11.4"])
        self.assertEqual(commande[4:], ["--repository", dossier])

    def test_les_valeurs_sont_controlees(self):
        e = mcp_catalog.entree("git")
        for mauvaise in ("", "/dossier/qui/n/existe/pas/xyz", "--config=evil"):
            with self.assertRaises(ValueError, msg=mauvaise):
                mcp_catalog.construire(e, {"depot": mauvaise}, chercher_tout)
        with self.assertRaises(ValueError):          # un fichier n'est pas un dossier
            mcp_catalog.construire(e, {"depot": __file__}, chercher_tout)
        with self.assertRaises(ValueError):          # une seule valeur pour un champ simple
            mcp_catalog.construire(e, {"depot": str(_TEMP) + "\n" + str(_TEMP)}, chercher_tout)
        with self.assertRaises(ValueError):          # trop de dossiers
            mcp_catalog.construire(mcp_catalog.entree("fichiers"), {"dossiers": "\n".join([str(_TEMP)] * 11)}, chercher_tout)
        with self.assertRaises(ValueError):
            mcp_catalog.construire(mcp_catalog.entree("home-assistant"), {"adresse": "ftp://x", "jeton": "t"}, chercher_tout)
        with self.assertRaises(ValueError):          # le jeton est obligatoire pour Home Assistant
            mcp_catalog.construire(mcp_catalog.entree("home-assistant"), {"adresse": "http://ha.local:8123/api/mcp"}, chercher_tout)

    def test_un_serveur_distant_prend_l_adresse_et_le_jeton_en_entete(self):
        _, url, entetes = mcp_catalog.construire(mcp_catalog.entree("home-assistant"), {"adresse": "http://ha.local:8123/api/mcp", "jeton": "abc"}, chercher_rien)
        self.assertEqual((url, entetes), ("http://ha.local:8123/api/mcp", {"Authorization": "Bearer abc"}))
        _, url, entetes = mcp_catalog.construire(mcp_catalog.entree("n8n"), {"adresse": "https://n8n.exemple.fr/mcp/x"}, chercher_rien)
        self.assertEqual(entetes, {}, "le jeton de n8n est facultatif : sans jeton, pas d'en-tête")

    def test_un_programme_absent_est_dit_avec_la_marche_a_suivre(self):
        entrees = {e["id"]: e for e in mcp_catalog.liste(chercher_rien)}
        self.assertIn("Node.js", entrees["fichiers"]["manque"])
        self.assertIn("uv", entrees["pages-web"]["manque"])
        self.assertEqual(entrees["home-assistant"]["manque"], "", "un serveur distant n'a besoin d'aucun programme")
        self.assertIn("Lutin installera", entrees["pages-web"]["manque"])
        self.assertEqual(entrees["pages-web"]["outil"], "uv")
        self.assertEqual(entrees["fichiers"]["outil"], "node")

    def test_le_programme_manquant_est_installe_au_passage_apres_controle_des_valeurs(self):
        installes = []

        def hors_ligne(nom):
            installes.append(nom)
            raise ValueError("Mode hors ligne")
        with self.assertRaises(ValueError) as e:
            mcp_catalog.installer("pages-web", {}, chercher_rien, hors_ligne)
        self.assertEqual(installes, ["uv"], "uv est installé par Lutin au passage")
        self.assertIn("hors ligne", str(e.exception))
        self.assertEqual(mcp.lire()["serveurs"], {}, "rien n'est resté")
        installes.clear()
        with self.assertRaises(ValueError):          # une saisie fausse : rien n'est téléchargé
            mcp_catalog.installer("git", {"depot": "/n/existe/pas"}, chercher_rien, hors_ligne)
        self.assertEqual(installes, [])

    def test_un_connecteur_qui_ne_repond_pas_est_retire(self):
        with self.assertRaises(ValueError) as e:
            mcp_catalog.installer("pages-web", {}, lambda nom: sys.executable.replace("python", "programme-introuvable"))
        self.assertIn("pas été branché", str(e.exception))
        self.assertEqual(mcp.lire()["serveurs"], {}, "un connecteur cassé ne reste pas dans la liste")

    def test_branchement_reel_de_bout_en_bout_avec_le_serveur_de_demonstration(self):
        """Une entrée du catalogue lancée pour de vrai : le serveur de démonstration de Lutin joue le rôle du serveur npx/uvx."""
        entree = {"id": "demo", "nom": {"fr": "Démo", "en": "Demo"}, "execution": "uvx", "paquet": "lutin.mcp_demo", "version": "1", "champs": [], "arguments": [], "description": {"fr": "x", "en": "x"}}
        avant = (mcp_catalog.charger, mcp_catalog.programme)
        mcp_catalog.charger = lambda: [entree]
        mcp_catalog.programme = lambda execution, chercher=None: sys.executable
        original = mcp_catalog.construire

        def construire(e, saisie, chercher=None):
            commande, url, entetes = original(e, saisie, chercher)
            return [sys.executable, "-m", "lutin.mcp_demo"], url, entetes
        mcp_catalog.construire = construire
        try:
            mcp.ecrire({"serveurs": {}})
            ancien_env = os.environ.get("PYTHONPATH")
            os.environ["PYTHONPATH"] = SRC + (os.pathsep + ancien_env if ancien_env else "")
            try:
                r = mcp_catalog.installer("demo", {})
            finally:
                if ancien_env is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = ancien_env
            self.assertGreaterEqual(r["outils"], 1)
            serveur = mcp.lire()["serveurs"][r["id"]]
            self.assertEqual(serveur["catalogue"], "demo")
            self.assertTrue(serveur["lecture_seule"], "reste en lecture seule")
            lecture = [n for n, o in serveur["outils"].items() if o["lecture"]]
            self.assertEqual(r["autorises"], len(lecture))
            self.assertTrue(all(serveur["outils"][n]["autorise"] == serveur["outils"][n]["lecture"] for n in serveur["outils"]), "seuls les outils en lecture sont autorisés d'emblée")
            with self.assertRaises(ValueError) as e:
                mcp_catalog.installer("demo", {})
            self.assertIn("déjà", str(e.exception))
            self.assertTrue(mcp_catalog.liste()[0]["installe"])
            mcp.fermer()
        finally:
            mcp_catalog.charger, mcp_catalog.programme = avant
            mcp_catalog.construire = original

    def test_le_fichier_du_catalogue_est_du_json_valide(self):
        self.assertEqual(json.loads(mcp_catalog.FICHIER.read_text(encoding="utf-8"))["version"], 1)


if __name__ == "__main__":
    unittest.main()
