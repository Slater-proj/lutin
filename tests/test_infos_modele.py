import tempfile
import time
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import model_info as im


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
        i = im.extract(show_dense())
        self.assertEqual((i["params_b"], i["actifs_b"], i["ctx_max"]), (3.21, 3.21, 131072))
        self.assertEqual(i["kv_mo_1k"], 115, "28 couches × 8 têtes × 128 × 2 (clés, valeurs) × 2 octets pour 1000 jetons")
        self.assertEqual(i["capacites"], ["outils"])

    def test_modele_a_experts_la_part_qui_travaille(self):
        i = im.extract(show_experts())
        self.assertAlmostEqual(i["actifs_b"], 3.05, delta=0.3, msg="Qwen 3 30B : environ 3 milliards travaillent")
        self.assertEqual(i["capacites"], ["outils", "reflexion"])

    def test_modele_hybride_seules_les_couches_d_attention_ont_un_cache(self):
        i = im.extract(show_hybride())
        self.assertLess(i["kv_mo_1k"], 30, "4 couches sur 40 seulement")
        self.assertLess(i["actifs_b"], 1.2)

    def test_reponse_inutilisable_ne_donne_rien_d_invente(self):
        self.assertEqual(im.extract(None), {})
        self.assertEqual(im.extract({"model_info": "x"}), {})
        self.assertEqual(im.extract({"model_info": {"general.parameter_count": True}}), {})
        self.assertEqual(im.extract({"capabilities": ["completion"]}), {"capacites": []}, "sans outils : on le sait, on le dit")

    def test_un_modele_de_recherche_n_est_pas_presente_comme_un_modele_qui_n_appelle_pas_les_outils(self):
        i = im.extract({"capabilities": ["embedding"], "model_info": {"general.architecture": "bert", "general.parameter_count": 137000000}})
        self.assertTrue(i["embedding"])
        self.assertIn("recherche par le sens", im.sentence(i))
        self.assertNotIn("outils", im.sentence(i))

    def test_la_precision_installee_est_lue_et_les_anciennes_lectures_refaites(self):
        i = im.extract(dict(show_dense(), details={"quantization_level": "Q8_0", "parameter_size": "3.2B"}))
        self.assertEqual(i["quantification"], "Q8_0")
        self.assertNotIn("quantification", im.extract(show_dense()), "pas de précision annoncée : rien d'inventé")
        import json as _json
        import tempfile as _tf
        from pathlib import Path as _P
        with _tf.TemporaryDirectory() as d:
            donnees = _P(d)
            (donnees / "infos-modeles.json").write_text(_json.dumps({"ancien:3b": {"params_b": 3.2}, "recent:3b": {"params_b": 3.2, "v": im.VERSION}}), encoding="utf-8")
            im._memory.clear()
            self.assertIsNone(im.already_known("ancien:3b", donnees), "lecture d'avant la précision installée : à refaire")
            self.assertEqual(im.already_known("recent:3b", donnees)["params_b"], 3.2)

    def test_phrase_honnete(self):
        p = im.sentence(im.extract(show_experts()))
        self.assertIn("30.53 milliards", p)
        self.assertIn("travaillent à chaque mot", p)
        self.assertIn("outils", p)
        self.assertIn("n'appelle pas les outils", im.sentence(im.extract({"model_info": {"general.architecture": "x", "general.parameter_count": 1e9}, "capabilities": ["completion"]})))
        self.assertEqual(im.sentence({}), "")


class Lecture(unittest.TestCase):
    def test_lecture_en_arriere_plan_gardee_sur_disque_une_seule_fois(self):
        appels = []

        def show(m):
            appels.append(m)
            return show_dense()
        with tempfile.TemporaryDirectory() as d:
            donnees = Path(d)
            im._memory.clear()
            self.assertIsNone(im.already_known("nouveau:3b", donnees))
            im.ask(["nouveau:3b"], donnees, show)
            for _ in range(100):
                if im.already_known("nouveau:3b", donnees) is not None:
                    break
                time.sleep(0.05)
            self.assertEqual(im.already_known("nouveau:3b", donnees)["params_b"], 3.21)
            im._memory.clear()                                                     # nouvelle session : relu sur le disque, Ollama n'est pas redemandé
            im.ask(["nouveau:3b"], donnees, show)
            self.assertEqual(im.already_known("nouveau:3b", donnees)["params_b"], 3.21)
            time.sleep(0.2)
            self.assertEqual(appels, ["nouveau:3b"])

    def test_ollama_muet_on_reessaiera(self):
        def show(m):
            raise OSError("pas de réponse")
        with tempfile.TemporaryDirectory() as d:
            donnees = Path(d)
            im._memory.clear()
            im.ask(["x:1b"], donnees, show)
            time.sleep(0.3)
            self.assertIsNone(im.already_known("x:1b", donnees), "rien n'est gardé d'une panne")
            self.assertNotIn("x:1b", im._in_progress)


if __name__ == "__main__":
    unittest.main()
