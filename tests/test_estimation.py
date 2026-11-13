"""Estimation avant chargement : où le modèle ira, quand ça sature, préréglage des modèles à experts, mode prudent, écart avec les mesures du banc."""
import unittest

import context  # noqa: F401
from lutin import memory_estimate


class Profil:
    def __init__(self, budget, ram, ram_libre=None, gpu=True):
        self._budget, self.ram_go, self.ram_libre_go, self._gpu = budget, ram, ram_libre if ram_libre is not None else ram * 0.6, gpu

    def budget_go(self):
        return self._budget

    def sans_gpu(self):
        return not self._gpu


DENSE = {"id": "d:8b", "go": 5.0, "kv_mo_1k": 128, "ctx_max": 32768, "params_b": 8, "actifs_b": 8}
EXPERTS = {"id": "e:30b", "go": 18.0, "kv_mo_1k": 48, "ctx_max": 32768, "params_b": 30, "actifs_b": 3}


class Niveaux(unittest.TestCase):
    def test_tient_sur_la_carte(self):
        e = memory_estimate.estimer(DENSE, 8192, Profil(budget=20, ram=32))
        self.assertEqual(e["niveau"], "tient")
        self.assertEqual(e["sur_ram_go"], 0.0)

    def test_deborde_en_memoire_vive(self):
        e = memory_estimate.estimer(DENSE, 8192, Profil(budget=4, ram=32))
        self.assertEqual(e["niveau"], "partiel")
        self.assertGreater(e["sur_ram_go"], 0.5)

    def test_trop_gros_est_dit_avant_le_chargement(self):
        e = memory_estimate.estimer(EXPERTS, 8192, Profil(budget=6, ram=10, ram_libre=5))
        self.assertEqual(e["niveau"], "trop_gros")
        self.assertIn("Ne tient pas", e["texte"])

    def test_sature_quand_il_ne_reste_presque_rien(self):
        e = memory_estimate.estimer(DENSE, 8192, Profil(budget=0.1, ram=12, ram_libre=7.5))
        self.assertEqual(e["niveau"], "sature")

    def test_sans_carte_tout_est_en_memoire_vive(self):
        e = memory_estimate.estimer(DENSE, 8192, Profil(budget=12, ram=32, gpu=False))
        self.assertEqual(e["sur_carte_go"], 0.0)
        self.assertGreater(e["sur_ram_go"], 5.0)

    def test_machine_inconnue(self):
        self.assertEqual(memory_estimate.estimer(DENSE, 8192, None)["niveau"], "inconnu")

    def test_un_cache_plus_leger_pese_moins(self):
        a = memory_estimate.estimer(DENSE, 16384, Profil(budget=20, ram=32), cache="f16")
        b = memory_estimate.estimer(DENSE, 16384, Profil(budget=20, ram=32), cache="q4_0")
        self.assertGreater(a["kv_go"], b["kv_go"] * 3)


class Experts(unittest.TestCase):
    def test_carte_de_24_go_et_32_go_de_ram(self):
        """Le cas de la feuille de route : 24 Go de carte + 32 Go de RAM, modèle à experts de 30 milliards (18 Go) avec une grande conversation."""
        profil = Profil(budget=24 * 0.85, ram=32, ram_libre=24)
        gros = dict(EXPERTS, go=40.0)
        p = memory_estimate.preset_experts(gros, profil)
        self.assertIsNotNone(p)
        self.assertTrue(0 < p["part"] < 1)
        self.assertTrue(1 <= p["n_cpu_moe"] <= p["couches"])
        self.assertIn("--n-cpu-moe", p["texte"])

    def test_inutile_si_ca_tient(self):
        self.assertIsNone(memory_estimate.preset_experts(EXPERTS, Profil(budget=40, ram=64)))

    def test_inutile_pour_un_modele_dense_ou_sans_carte(self):
        self.assertIsNone(memory_estimate.preset_experts(DENSE, Profil(budget=2, ram=32)))
        self.assertIsNone(memory_estimate.preset_experts(EXPERTS, Profil(budget=2, ram=32, gpu=False)))

    def test_impossible_meme_avec_tous_les_experts_dehors(self):
        self.assertIsNone(memory_estimate.preset_experts(dict(EXPERTS, go=200.0), Profil(budget=8, ram=32, ram_libre=10)))

    def test_les_conseils_citent_le_preset(self):
        profil = Profil(budget=24 * 0.85, ram=32, ram_libre=24)
        e = memory_estimate.estimer(dict(EXPERTS, go=40.0), 8192, profil, experts_cpu=0.0)
        self.assertTrue(any("--n-cpu-moe" in c for c in e["conseils"]), e)


class Prudent(unittest.TestCase):
    def test_machine_modeste(self):
        r = memory_estimate.mode_prudent(Profil(budget=4, ram=8, gpu=False))
        self.assertTrue(r["actif"])
        self.assertEqual(r["reglages"]["num_ctx"], memory_estimate.CTX_PRUDENT)

    def test_grosse_machine(self):
        self.assertFalse(memory_estimate.mode_prudent(Profil(budget=24, ram=64))["actif"])

    def test_inconnue(self):
        self.assertFalse(memory_estimate.mode_prudent(None)["actif"])


class Ecart(unittest.TestCase):
    def test_ecart_en_pourcentage_de_la_mesure(self):
        self.assertEqual(memory_estimate.ecart(11.0, 10.0), 10.0)
        self.assertEqual(memory_estimate.ecart(9.0, 10.0), -10.0)
        self.assertIsNone(memory_estimate.ecart(None, 10.0))
        self.assertIsNone(memory_estimate.ecart(10.0, 0))


class AvecLeBanc(unittest.TestCase):
    def test_l_estimation_est_comparee_a_la_mesure(self):
        import os
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp(prefix="lutin-est-"))
        for cle, valeur in {"LUTIN_RACINE": str(tmp / "p"), "LUTIN_DONNEES": str(tmp / "d"), "LUTIN_MEMOIRE": str(tmp / "m"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
            os.environ.setdefault(cle, valeur)
        (tmp / "p").mkdir(exist_ok=True)
        from lutin import core as _m  # noqa: F401
        from lutin import engine_bench as bm

        class Flux:
            def __enter__(self):
                return iter([{"message": {"content": "bonjour"}, "done": True, "eval_count": 100, "eval_duration": 2_000_000_000}])

            def __exit__(self, *a):
                return False

        class Moteur:
            id, nom = "ollama", "Ollama"

            def statut(self):
                return {"version": "1"}

            def chat_flux(self, corps, delai=60):
                return Flux()
        r = bm.mesurer(Moteur(), "m", "rapide", 4096, memoire=lambda: {"ram": 2 * 1024 ** 3, "vram": 4 * 1024 ** 3}, estime_go=6.6)
        self.assertEqual(r["estimation"]["mesure_go"], 6.0)
        self.assertEqual(r["estimation"]["ecart_pct"], 10.0)


class Avertissement(unittest.TestCase):
    def test_trop_gros_est_dit_avant_le_chargement_une_fois(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        tmp = Path(tempfile.mkdtemp(prefix="lutin-est2-"))
        for cle, valeur in {"LUTIN_RACINE": str(tmp / "p"), "LUTIN_DONNEES": str(tmp / "d"), "LUTIN_MEMOIRE": str(tmp / "m"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
            os.environ.setdefault(cle, valeur)
        (tmp / "p").mkdir(exist_ok=True)
        from lutin import core as _m
        from lutin import model_fit, agent
        gros = dict(EXPERTS, id="gros:1b", go=90.0, capacites=["outils"], notes={})
        faux_moteur = mock.Mock(en_memoire=lambda m: None)
        evenements = []
        with mock.patch.object(_m, "_CATALOGUE", {"modeles": [gros]}), mock.patch.object(model_fit, "profil_pret", lambda: Profil(budget=6, ram=16, ram_libre=8)),                 mock.patch.object(agent, "moteur_actuel", lambda *a, **k: faux_moteur):
            agent.AVERTIS_CARTE.clear()
            r = {"modele": "gros:1b", "num_ctx": 8192}
            agent._estimer_avant_charge(r, evenements.append)
            agent._estimer_avant_charge(r, evenements.append)
        self.assertEqual(len(evenements), 1, "dit une fois, pas à chaque message")
        self.assertIn("Ne tient pas", evenements[0]["texte"])


if __name__ == "__main__":
    unittest.main()
