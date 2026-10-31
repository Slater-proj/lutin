import tempfile
import time
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import infos_modele as im


def show_dense():
    return {"capabilities": ["completion", "tools"], "model_info": {
        "general.architecture": "llama", "general.parameter_count": 3212749888, "llama.context_length": 131072, "llama.block_count": 28,
        "llama.attention.head_count": 24, "llama.attention.head_count_kv": 8, "llama.embedding_length": 3072}}


def show_experts():
    return {"capabilities": ["completion", "tools", "thinking"], "model_info": {
        "general.architecture": "qwen3moe", "general.parameter_count": 30532122624, "qwen3moe.context_length": 40960, "qwen3moe.block_count": 48,
        "qwen3moe.attention.head_count": 32, "qwen3moe.attention.head_count_kv": 4, "qwen3moe.attention.key_length": 128, "qwen3moe.embedding_length": 2048,
        "qwen3moe.expert_count": 128, "qwen3moe.expert_used_count": 8}}


def show_hybride():
    return {"capabilities": ["completion", "tools"], "model_info": {
        "general.architecture": "granitehybrid", "general.parameter_count": 6940000000, "granitehybrid.context_length": 1048576, "granitehybrid.block_count": 40,
        "granitehybrid.attention.head_count": 12, "granitehybrid.attention.head_count_kv": [0] * 36 + [4] * 4, "granitehybrid.embedding_length": 1536,
        "granitehybrid.expert_count": 64, "granitehybrid.expert_used_count": 6}}


class Extraction(unittest.TestCase):
    def test_modele_dense(self):
        i = im.extraire(show_dense())
        self.assertEqual((i["params_b"], i["actifs_b"], i["ctx_max"]), (3.21, 3.21, 131072))
        self.assertEqual(i["kv_mo_1k"], 115, "28 couches × 8 têtes × 128 × 2 (clés, valeurs) × 2 octets pour 1000 jetons")
        self.assertEqual(i["capacites"], ["outils"])

    def test_modele_a_experts_la_part_qui_travaille(self):
        i = im.extraire(show_experts())
        self.assertAlmostEqual(i["actifs_b"], 3.05, delta=0.3, msg="Qwen 3 30B : environ 3 milliards travaillent")
        self.assertEqual(i["capacites"], ["outils", "reflexion"])

    def test_modele_hybride_seules_les_couches_d_attention_ont_un_cache(self):
        i = im.extraire(show_hybride())
        self.assertLess(i["kv_mo_1k"], 30, "4 couches sur 40 seulement")
        self.assertLess(i["actifs_b"], 1.2)

    def test_reponse_inutilisable_ne_donne_rien_d_invente(self):
        self.assertEqual(im.extraire(None), {})
        self.assertEqual(im.extraire({"model_info": "x"}), {})
        self.assertEqual(im.extraire({"model_info": {"general.parameter_count": True}}), {})
        self.assertEqual(im.extraire({"capabilities": ["completion"]}), {"capacites": []}, "sans outils : on le sait, on le dit")

    def test_phrase_honnete(self):
        p = im.phrase(im.extraire(show_experts()))
        self.assertIn("30.53 milliards", p)
        self.assertIn("travaillent à chaque mot", p)
        self.assertIn("outils", p)
        self.assertIn("n'appelle pas les outils", im.phrase(im.extraire({"model_info": {"general.architecture": "x", "general.parameter_count": 1e9}, "capabilities": ["completion"]})))
        self.assertEqual(im.phrase({}), "")


class Lecture(unittest.TestCase):
    def test_lecture_en_arriere_plan_gardee_sur_disque_une_seule_fois(self):
        appels = []

        def show(m):
            appels.append(m)
            return show_dense()
        with tempfile.TemporaryDirectory() as d:
            donnees = Path(d)
            im._memoire.clear()
            self.assertIsNone(im.deja_connu("nouveau:3b", donnees))
            im.demander(["nouveau:3b"], donnees, show)
            for _ in range(100):
                if im.deja_connu("nouveau:3b", donnees) is not None:
                    break
                time.sleep(0.05)
            self.assertEqual(im.deja_connu("nouveau:3b", donnees)["params_b"], 3.21)
            im._memoire.clear()                                                     # nouvelle session : relu sur le disque, Ollama n'est pas redemandé
            im.demander(["nouveau:3b"], donnees, show)
            self.assertEqual(im.deja_connu("nouveau:3b", donnees)["params_b"], 3.21)
            time.sleep(0.2)
            self.assertEqual(appels, ["nouveau:3b"])

    def test_ollama_muet_on_reessaiera(self):
        def show(m):
            raise OSError("pas de réponse")
        with tempfile.TemporaryDirectory() as d:
            donnees = Path(d)
            im._memoire.clear()
            im.demander(["x:1b"], donnees, show)
            time.sleep(0.3)
            self.assertIsNone(im.deja_connu("x:1b", donnees), "rien n'est gardé d'une panne")
            self.assertNotIn("x:1b", im._en_cours)


if __name__ == "__main__":
    unittest.main()
