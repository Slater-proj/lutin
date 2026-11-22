"""La page Modèles de LM Studio et de Colibri, côté serveur : catalogue GGUF (Hugging Face simulé), quantifications, modèles installés, suppression sûre, catalogue de Colibri dans la même forme.
Aucun réseau, aucun vrai programme."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-mg-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import colibri as CO  # noqa: E402
from lutin import exllamav3_catalog as C  # noqa: E402
from lutin import lmstudio as L  # noqa: E402
from lutin import lmstudio_catalog as LC  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engines, server  # noqa: E402


def faux_hf(fichiers=None, depots=None, appels=None):
    def f(url, entetes=None):
        if appels is not None:
            appels.append(url)
        if "/tree/" in url:
            return 200, {}, json.dumps(fichiers or []).encode()
        if "/api/models?" in url:
            return 200, {}, json.dumps(depots or []).encode()
        return 404, {}, b""
    return f


def fichier(nom, go):
    return {"type": "file", "path": nom, "size": int(go * 1e9)}


class CatalogueGguf(unittest.TestCase):
    def setUp(self):
        C.CACHE.clear()

    def test_la_communaute_officielle_est_la_valeur_par_defaut_et_tous_les_auteurs_un_choix(self):
        appels = []
        depot = {"id": "lmstudio-community/Qwen3-8B-GGUF", "downloads": 900, "likes": 12, "lastModified": "2026-11-05T10:00:00Z", "pipeline_tag": "text-generation", "tags": ["gguf", "license:apache-2.0"]}
        r = LC.search("qwen", "recent", False, 1, faux_hf(depots=[depot, {"id": "x/autre-modele", "tags": ["exl3"]}], appels=appels))
        LC.search("qwen", "populaire", True, 1, faux_hf(depots=[depot], appels=appels))
        self.assertIn("author=lmstudio-community", appels[0])
        self.assertIn("filter=gguf", appels[1])
        self.assertNotIn("author=", appels[1])
        self.assertEqual([m["id"] for m in r["modeles"]], ["lmstudio-community/Qwen3-8B-GGUF"])
        self.assertGreater(r["modeles"][0]["estimation_go"], 5, "8B à environ 4,85 bits")

    def test_les_fichiers_sont_regroupes_par_quantification_sans_les_projecteurs_d_images(self):
        arbre = [fichier("Qwen3-8B-Q8_0.gguf", 8.7), fichier("Qwen3-8B-Q4_K_M.gguf", 5.0), fichier("mmproj-Qwen3-8B-F16.gguf", 1.2), fichier("Qwen3-8B.imatrix.gguf", 0.4), fichier("README.md", 0.00001),
                 fichier("Gros-Q4_K_M-00001-of-00002.gguf", 20), fichier("Gros-Q4_K_M-00002-of-00002.gguf", 18), {"type": "directory", "path": "sous-dossier"}]
        q = LC.quantizations("lmstudio-community/Qwen3-8B-GGUF", faux_hf(arbre))
        self.assertEqual([(x["revision"], x["go"], x["fichiers"]) for x in q], [("Q8_0", 8.7, 1), ("Q4_K_M", 43.0, 3)])
        with self.assertRaises(ValueError):
            LC.quantizations("--help", faux_hf())


class Suppression(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-mg-s-"))

    def test_lm_studio_n_efface_que_le_fichier_d_un_modele_de_sa_liste(self):
        racine = self.tmp / "models"
        (racine / "pub" / "modele").mkdir(parents=True)
        (racine / "pub" / "modele" / "a.gguf").write_bytes(b"x")
        (self.tmp / "ailleurs.txt").write_text("à garder", encoding="utf-8")
        liste = lambda: [{"nom": "a", "chemin": "pub/modele/a.gguf"}, {"nom": "piege", "chemin": "../ailleurs.txt"}, {"nom": "vide", "chemin": ""}]  # noqa: E731
        with mock.patch.object(L, "models_folder", lambda: racine):
            for mauvais in ("inconnu", "piege", "vide"):
                with self.assertRaises(ValueError, msg=mauvais):
                    L.remove_model(mauvais, liste)
            self.assertTrue((self.tmp / "ailleurs.txt").is_file())
            self.assertTrue(L.remove_model("a", liste))
        self.assertFalse((racine / "pub").exists(), "les dossiers laissés vides disparaissent aussi")
        self.assertTrue(racine.is_dir(), "mais pas le dossier des modèles lui-même")

    def test_colibri_liste_ses_modeles_et_ne_supprime_que_ceux_de_son_dossier(self):
        d = {"donnees": self.tmp}
        racine = CO.folder_models(d)
        (racine / "deepseek-v4").mkdir(parents=True)
        (racine / "deepseek-v4" / "poids.bin").write_bytes(b"x" * 2000)
        autre = self.tmp / "ailleurs" / "mon-modele"
        autre.mkdir(parents=True)
        (autre / "poids.bin").write_bytes(b"y")
        liste = CO.installed_models(d, str(autre))
        self.assertEqual([(m["nom"], m["supprimable"]) for m in liste], [("deepseek-v4", True), ("mon-modele", False)])
        for mauvais in ("", "..", "../ailleurs", "a/b", "mon-modele"):
            with self.assertRaises(ValueError, msg=repr(mauvais)):
                CO.remove_model(mauvais, d)
        self.assertTrue(autre.is_dir())
        self.assertTrue(CO.remove_model("deepseek-v4", d))
        self.assertEqual([m["nom"] for m in CO.installed_models(d, "")], [])


class Moteur(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-mg-m-"))
        self.ancien = dict(engines.CONTEXT)
        engines.CONTEXT["donnees"] = lambda: self.tmp
        self.mo = engines.ENGINES["openai"]
        self.addCleanup(self.remettre)

    def remettre(self):
        cfg = ml.read_config()
        for identifier in ("openai", "lmstudio", "colibri"):
            cfg.pop(identifier, None)
        ml.write_config(cfg)
        engines.CONTEXT.clear()
        engines.CONTEXT.update(self.ancien)

    def test_supprimer_un_modele_lm_studio_passe_par_lutin(self):
        self.mo = engines.ENGINES["lmstudio"]          # an engine of its own since ADR 0020
        appels = []
        with mock.patch.object(L, "remove_model", lambda nom: appels.append(nom)):
            self.mo.supprimer_modele("a")
        self.assertEqual(appels, ["a"])
        with mock.patch.object(L, "remove_model", mock.Mock(side_effect=PermissionError())):
            with self.assertRaises(ml.EngineError) as e:
                self.mo.supprimer_modele("a")
        self.assertIn("arrête LM Studio", str(e.exception))

    def test_colibri_est_arrete_avant_que_son_modele_soit_efface(self):
        self.mo = engines.ENGINES["colibri"]
        suivi = []
        with mock.patch.object(ml.OpenAIEngine, "actif", lambda self: True), mock.patch.object(CO, "stop", lambda *a, **k: suivi.append("arret") or True), \
                mock.patch.object(CO, "remove_model", lambda nom, d: suivi.append(("supprime", nom))):
            self.mo.supprimer_modele("m")
        self.assertEqual(suivi, ["arret", ("supprime", "m")])

    def test_un_serveur_non_gere_ne_supprime_rien(self):
        with self.assertRaises(ml.EngineError):          # « openai »: a server reached by its address
            self.mo.supprimer_modele("x")


class CatalogueColibri(unittest.TestCase):
    def test_le_catalogue_de_colibri_a_la_forme_des_autres(self):
        brut = [{"id": "enorme-1t", "go": 900.0, "ok": False, "statut": "needs-disk", "raison": "il manque 400 Go de disque"}, {"id": "moyen-200b", "go": 120.0, "ok": True, "statut": "ready", "raison": ""},
                {"id": "petit-70b", "go": 40.0, "ok": True, "statut": "ready", "raison": ""}]
        mo = mock.Mock(_dossiers=lambda: {})
        with mock.patch.object(CO, "catalogue", lambda d: brut):
            r = server.Handler._catalogue_colibri(mo, [{"nom": "petit-70b-q4"}], "")
            self.assertEqual([m["id"] for m in r["modeles"]], ["petit-70b", "moyen-200b", "enorme-1t"], "ce qui tient d'abord, du plus petit au plus gros")
            self.assertEqual([m["adequation"]["niveau"] for m in r["modeles"]], ["bien", "bien", "trop_gros"])
            self.assertIn("400 Go", r["modeles"][2]["adequation"]["texte"], "la raison de Colibri est montrée telle quelle")
            self.assertEqual([bool(m["installes"]) for m in r["modeles"]], [True, False, False])
            self.assertTrue(all(m["direct"] for m in r["modeles"]) and r["suite"] is False)
            self.assertEqual([m["id"] for m in server.Handler._catalogue_colibri(mo, [], "moyen")["modeles"]], ["moyen-200b"])


class Routes(unittest.TestCase):
    def test_les_trois_serveurs_geres_ont_les_memes_routes(self):
        """ADR 0020: one family of routes for every engine, its identifier in the path; the three managed servers are among the engines it serves."""
        from lutin import api_v1, engines
        famille = {r["path"] for r in api_v1.table() if r["path"].startswith("/api/v1/engines/{id}/models")}
        self.assertTrue({"/api/v1/engines/{id}/models", "/api/v1/engines/{id}/models/search", "/api/v1/engines/{id}/models/variants"} <= famille)
        for serveur_gere in ("exllamav3", "lmstudio", "colibri"):
            self.assertIn(serveur_gere, engines.ENGINES)


if __name__ == "__main__":
    unittest.main()
