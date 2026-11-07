"""Modèles compatibles avec le moteur choisi : la liste ne propose jamais un modèle que le moteur ne peut pas faire tourner ; rôles propres à chaque moteur ; banc indépendant d'Ollama."""
import unittest

import context  # noqa: F401
from lutin import moteur as _m  # noqa: F401  (avant les autres : import circulaire sinon)
from lutin import bench, compat_modeles, moteurs


class FauxMoteur:
    def __init__(self, ident, nom, grille, genre="ollama"):
        self.id, self.nom, self._grille, self._genre = ident, nom, grille, genre

    def grille(self):
        return self._grille

    def telechargeable(self):
        return {"genre": self._genre, "possible": True, "raison": ""}


TOUT = {f: ("natif", "") for f in ("outils", "reflexion", "vision")}
CATALOGUE = {"modeles": [
    {"id": "a:8b", "nom": "A", "go": 5.0, "kv_mo_1k": 100, "capacites": ["outils"], "notes": {"polyvalent": 8, "rapide": 5, "creatif": 5, "code": 5}, "ctx_max": 32768, "params_b": 8, "actifs_b": 8},
    {"id": "v:7b", "nom": "V", "go": 5.0, "kv_mo_1k": 100, "capacites": ["outils", "vision"], "notes": {"polyvalent": 9, "rapide": 5, "creatif": 5, "code": 5}, "ctx_max": 32768, "params_b": 7, "actifs_b": 7},
]}


class Compatibilite(unittest.TestCase):
    def test_ollama_accepte_tout_le_catalogue(self):
        mo = FauxMoteur("ollama", "Ollama", TOUT)
        for m in CATALOGUE["modeles"]:
            self.assertTrue(compat_modeles.evaluer(m, mo)["compatible"])

    def test_une_capacite_non_supportee_exclut_le_modele_avec_la_raison(self):
        grille = dict(TOUT, vision=("non", "pas d'images ici"))
        mo = FauxMoteur("x", "Moteur X", grille)
        r = compat_modeles.evaluer(CATALOGUE["modeles"][1], mo)
        self.assertFalse(r["compatible"])
        self.assertIn("vision", r["raisons"][0])
        self.assertIn("pas d'images ici", r["raisons"][0])
        self.assertTrue(compat_modeles.evaluer(CATALOGUE["modeles"][0], mo)["compatible"])

    def test_une_capacite_non_testee_est_un_avertissement_pas_un_refus(self):
        mo = FauxMoteur("x", "Moteur X", dict(TOUT, vision=("non_teste", "")))
        r = compat_modeles.evaluer(CATALOGUE["modeles"][1], mo)
        self.assertTrue(r["compatible"])
        self.assertTrue(r["avertissements"])

    def test_un_serveur_externe_ne_propose_que_ses_modeles(self):
        mo = FauxMoteur("openai", "Serveur", TOUT, genre="aucun")
        self.assertFalse(compat_modeles.evaluer(CATALOGUE["modeles"][0], mo)["compatible"])
        self.assertTrue(compat_modeles.evaluer(CATALOGUE["modeles"][0], mo, installes=["a:8b"])["compatible"])

    def test_quantification_et_memoire(self):
        self.assertEqual(compat_modeles.quantification("qwen3:8b-q8_0"), "Q8_0")
        self.assertEqual(compat_modeles.quantification("qwen3:8b-q4_K_M"), "Q4_K_M")
        self.assertEqual(compat_modeles.quantification("qwen3:8b"), "par défaut")
        r = compat_modeles.evaluer(CATALOGUE["modeles"][0], FauxMoteur("ollama", "Ollama", TOUT))
        self.assertEqual(r["format"], "GGUF")
        self.assertGreater(r["memoire_go"], 5.0)

    def test_le_catalogue_filtre_ne_garde_que_le_compatible(self):
        mo = FauxMoteur("x", "Moteur X", dict(TOUT, vision=("non", "")))
        f = compat_modeles.filtrer(CATALOGUE, mo)
        self.assertEqual([m["id"] for m in f["modeles"]], ["a:8b"])

    def test_les_vrais_moteurs_ont_une_grille_utilisable(self):
        """Le catalogue livré, filtré par chaque vrai moteur, garde au moins un modèle à outils (sinon Lutin n'aurait rien à proposer)."""
        for ident in ("ollama", "llamacpp"):
            mo = moteurs.MOTEURS[ident]
            f = compat_modeles.filtrer(_m._CATALOGUE, mo)
            self.assertTrue(any("outils" in m["capacites"] for m in f["modeles"]), ident)


class Installation(unittest.TestCase):
    def test_un_modele_incompatible_n_est_jamais_installe(self):
        from unittest import mock
        from lutin import dialogue
        vision = next(m for m in _m._CATALOGUE["modeles"] if "vision" in m["capacites"])
        mo = FauxMoteur("ollama", "Moteur X", dict(TOUT, vision=("non", "pas d'images")))
        with mock.patch.object(dialogue, "moteur_actuel", lambda *a, **k: mo), mock.patch.object(dialogue, "etat_moteur", lambda: {"installes": []}):
            with self.assertRaises(ValueError) as e:
                dialogue.installer_modele(vision["id"])
        self.assertIn("vision", str(e.exception))
        self.assertNotIn(vision["id"], dialogue.PULLS, "aucun téléchargement n'a commencé")


class BancIndependant(unittest.TestCase):
    def test_le_banc_parle_au_moteur_choisi(self):
        class Moteur:
            id = "llamacpp"

            def __init__(self):
                self.appels = []

            def chat(self, corps, delai=60):
                self.appels.append(corps)
                return {"message": {"content": "Bonjour"}, "eval_count": 100, "eval_duration": 2_000_000_000, "prompt_eval_count": 30, "prompt_eval_duration": 1_000_000_000}
        mo = Moteur()
        banc = bench.Banc(bench.AdaptateurMoteur(mo), "m", 4096)
        v = banc.vitesse()
        self.assertEqual(v["tok_s"], 50.0)
        self.assertEqual(mo.appels[0]["model"], "m")

    def test_une_panne_du_moteur_devient_une_erreur_du_banc(self):
        class Panne:
            def chat(self, corps, delai=60):
                raise ValueError("le serveur ne répond pas")
        with self.assertRaises(bench.ErreurOllama):
            bench.Banc(bench.AdaptateurMoteur(Panne()), "m").vitesse()


if __name__ == "__main__":
    unittest.main()
