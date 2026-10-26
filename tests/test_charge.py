"""Ne pas écraser le PC : cartes intégrées ignorées pour choisir les modèles, cœurs utilisés et durée de garde réglables, mêmes options pour toutes les requêtes."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-charge-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")
for d in ("projet", "donnees", "memoire", "config"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import catalogue, selection  # noqa: E402
from lutin import moteur as A  # noqa: E402
from lutin.machine import Gpu, Profil, est_integree  # noqa: E402


class CartesIntegrees(unittest.TestCase):
    def test_reconnues_a_leur_nom(self):
        for nom, fab in (("Intel(R) UHD Graphics 770", "intel"), ("AMD Radeon(TM) Graphics", "amd"), ("AMD Radeon 780M Graphics", "amd"), ("Intel(R) Arc(TM) Graphics", "intel"),
                         ("Intel(R) Iris(R) Xe Graphics", "intel"), ("Intel(R) HD Graphics 630", "intel"), ("AMD Radeon(TM) Vega 8 Graphics", "amd")):
            self.assertTrue(est_integree(Gpu(nom, fab, 4.0)), nom)

    def test_les_vraies_cartes_ne_sont_pas_touchees(self):
        for nom, fab in (("NVIDIA GeForce RTX 4060", "nvidia"), ("AMD Radeon RX 7800 XT", "amd"), ("Intel(R) Arc(TM) A770 Graphics", "intel"), ("AMD Radeon RX 6800M", "amd")):
            self.assertFalse(est_integree(Gpu(nom, fab, 8.0)), nom)

    def test_une_carte_declaree_a_la_main_est_toujours_crue(self):
        self.assertFalse(est_integree(Gpu("AMD Radeon 780M Graphics", "amd", 8.0, 0.0, "déclarée (LUTIN_GPU)")))

    def test_pc_avec_carte_integree_et_32_go_se_choisit_comme_un_pc_sans_carte(self):
        p = Profil(systeme="windows", cpu="Ryzen 7 7840U", coeurs=8, ram_go=32.0, ram_libre_go=24.0, gpus=[Gpu("AMD Radeon(TM) Graphics", "amd", 4.0, 0.0, "registre")])
        self.assertTrue(p.sans_gpu())
        self.assertIsNone(p.gpu_principal())
        self.assertEqual(p.budget_go(), 19.2, "60 % de la RAM, pas 85 % des 4 Go de la carte intégrée")
        self.assertEqual(p.classe(), "sans_gpu")
        self.assertIn("non utilisée", p.resume())
        choix = selection.choisir(p, catalogue.charger())
        retenu = choix["polyvalent"]
        self.assertIsNotNone(retenu)
        self.assertGreater(retenu.modele["go"], 4, "un modèle bien plus gros que la mémoire de la carte intégrée")

    def test_une_vraie_carte_a_cote_d_une_carte_integree_gagne(self):
        p = Profil(ram_go=32.0, gpus=[Gpu("Intel(R) UHD Graphics 770", "intel", 0.5), Gpu("NVIDIA GeForce RTX 4060", "nvidia", 8.0, 7.0, "nvidia-smi")])
        self.assertEqual(p.gpu_principal().nom, "NVIDIA GeForce RTX 4060")
        self.assertFalse(p.sans_gpu())


class ReglagesDeCharge(unittest.TestCase):
    def setUp(self):
        Path(_TEMP / "donnees" / "reglages.json").unlink(missing_ok=True)

    def test_par_defaut_tout_est_automatique(self):
        r = A.reglages()
        self.assertIsNone(r["num_thread"])
        self.assertIsNone(r["garde_min"])
        self.assertNotIn("num_thread", A.options_modele(r, 0.5))
        self.assertEqual(A.options_modele(r, 0.5, num_predict=9), {"num_ctx": r["num_ctx"], "temperature": 0.5, "num_predict": 9})

    def test_les_valeurs_sont_bornees_et_les_absurdites_deviennent_automatique(self):
        for brut, attendu in ((4, 4), ("6", 6), (0, 1), (9999, 256), ("", None), (None, None), ("beaucoup", None), (3.7, 3)):
            r = A.enregistrer_reglages({"num_thread": brut})
            self.assertEqual(r["num_thread"], attendu, repr(brut))
        for brut, attendu in ((0, 0), (2, 2), (-5, 0), (100000, 240), ("", None)):
            self.assertEqual(A.enregistrer_reglages({"garde_min": brut})["garde_min"], attendu, repr(brut))

    def test_les_coeurs_vont_dans_toutes_les_requetes_au_modele(self):
        A.enregistrer_reglages({"num_thread": 3})
        r = A.reglages()
        for temperature in (0, 0.2, 0.3, 0.4, r["temperature"]):
            self.assertEqual(A.options_modele(r, temperature)["num_thread"], 3)
        source = (Path(__file__).resolve().parent.parent / "src" / "lutin" / "moteur.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('{"num_ctx": r["num_ctx"]'), 1, "toute requête passe par options_modele (la seule construction du dictionnaire) : un jeu d'options différent ferait recharger le modèle")

    def test_duree_de_garde(self):
        self.assertEqual(A.duree_garde(), "30m", "automatique : comme avant")
        A.enregistrer_reglages({"liberer_si_comfy": False})
        self.assertIsNone(A.duree_garde(), "automatique, sans ComfyUI : le délai d'Ollama")
        self.assertEqual(A.avec_garde({"model": "x"}), {"model": "x"})
        A.enregistrer_reglages({"garde_min": 2})
        self.assertEqual(A.duree_garde(), "2m")
        self.assertEqual(A.avec_garde({"model": "x"})["keep_alive"], "2m")
        A.enregistrer_reglages({"garde_min": 0})
        self.assertEqual(A.avec_garde({"model": "x"})["keep_alive"], "0m", "0 : libéré dès la fin de la réponse")

    def test_la_page_propose_les_reglages_et_les_profils(self):
        page = A.page_web()
        for attendu in ('id="iThreads"', 'id="iGarde"', 'id="selProfil"', "ETAT.cpus"):
            self.assertIn(attendu, page)
        self.assertEqual(json.loads(json.dumps({"cpus": os.cpu_count() or 1}))["cpus"], os.cpu_count() or 1)


if __name__ == "__main__":
    unittest.main()
