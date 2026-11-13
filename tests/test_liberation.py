"""« Libérer la VRAM » libère ce qui est vraiment chargé : llama.cpp et, sur demande, le serveur géré par Lutin — pas seulement les modèles d'Ollama (elle répondait « aucun modèle en mémoire » avec 22 Go chargés)."""
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-lib-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engines  # noqa: E402


class Fil:
    def __init__(self, vivant=True):
        self.vivant = vivant

    def poll(self):
        return None if self.vivant else 0


class Liberation(unittest.TestCase):
    def setUp(self):
        self.arrets = []
        self.llama = engines.MOTEURS["llamacpp"]
        self.avant = ml.SERVEUR.get("proc")
        self.addCleanup(lambda: ml.SERVEUR.update(proc=self.avant))
        self.p1 = mock.patch.object(type(self.llama), "arreter", lambda s: self.arrets.append("llama.cpp"))
        self.p1.start()
        self.addCleanup(self.p1.stop)

    def sans_ollama(self):
        return mock.patch.object(_m, "ollama_json", side_effect=urllib.error.URLError("refusé"))

    def test_un_modele_llamacpp_charge_est_libere_meme_sans_ollama(self):
        ml.SERVEUR["proc"] = Fil(True)
        with self.sans_ollama():
            r = _m.liberer_vram()
        self.assertEqual(self.arrets, ["llama.cpp"])
        self.assertIn("llama.cpp", r["message"])
        self.assertNotIn("Aucun modèle", r["message"])

    def test_rien_de_charge_le_dit_sans_mentir(self):
        ml.SERVEUR["proc"] = None
        with self.sans_ollama():
            r = _m.liberer_vram()
        self.assertEqual(self.arrets, [])
        self.assertIn("déjà libre", r["message"])
        ml.SERVEUR["proc"] = Fil(False)          # un serveur déjà arrêté
        with self.sans_ollama():
            _m.liberer_vram()
        self.assertEqual(self.arrets, [])

    def test_le_serveur_gere_n_est_arrete_que_sur_demande_du_bouton(self):
        ml.SERVEUR["proc"] = None
        gere = engines.MOTEURS["openai"]
        with mock.patch.object(type(gere), "arreter_gere", lambda s: self.arrets.append("gere") or True), self.sans_ollama():
            _m.liberer_vram()          # garde-fous, passage de relais à ComfyUI : le serveur géré ne se redémarre pas tout seul, on ne le coupe pas en douce
            self.assertEqual(self.arrets, [])
            r = _m.liberer_vram(tout=True)          # le bouton « Libérer la VRAM »
        self.assertEqual(self.arrets, ["gere"])
        self.assertIn("Déchargé", r["message"])

    def test_ollama_et_llamacpp_ensemble(self):
        ml.SERVEUR["proc"] = Fil(True)
        envoyes = []
        with mock.patch.object(_m, "ollama_json", return_value={"models": [{"name": "qwen3:8b"}]}), mock.patch.object(_m.urllib.request, "urlopen", lambda req, timeout=0: envoyes.append(req.full_url)):
            r = _m.liberer_vram()
        self.assertEqual(self.arrets, ["llama.cpp"])
        self.assertEqual(len(envoyes), 1)
        self.assertIn("qwen3:8b", r["message"])
        self.assertIn("llama.cpp", r["message"])


class DejaCharge(unittest.TestCase):
    def test_un_modele_deja_charge_ne_reclame_pas_sa_place_une_seconde_fois(self):
        """Avec llama.cpp (qui ne dit pas la taille chargée), le garde-fou réclamait la taille du modèle EN PLUS de celui déjà en mémoire : « Pas assez de mémoire » pour un modèle qui tournait."""
        from lutin import health
        self.assertEqual(health.taille_modele("x", {"taille": 0, "vram": 0}), 0)
        self.assertEqual(health.taille_modele("x", {"taille": 5 * 10 ** 9}), 5 * 10 ** 9)


if __name__ == "__main__":
    unittest.main()
