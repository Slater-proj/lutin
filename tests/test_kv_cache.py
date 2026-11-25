"""The conversation cache of a model, read from its config.json (lutin.kv_cache). Hermetic: the files are written here."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import kv_cache  # noqa: E402

DENSE_32B = {"num_hidden_layers": 64, "num_attention_heads": 64, "num_key_value_heads": 8, "head_dim": 128, "hidden_size": 5120}


class FromConfig(unittest.TestCase):
    def test_a_dense_model(self):
        self.assertEqual(kv_cache.mb_per_1k(DENSE_32B), 262, "2 (keys, values) x 64 layers x 8 heads x 128 x 2 bytes x 1,000 tokens")

    def test_the_head_dimension_is_found_from_the_width_when_not_written(self):
        self.assertEqual(kv_cache.mb_per_1k({"num_hidden_layers": 32, "num_attention_heads": 32, "num_key_value_heads": 8, "hidden_size": 4096}), 131)

    def test_without_key_value_heads_every_head_keeps_a_cache(self):
        self.assertEqual(kv_cache.mb_per_1k({"num_hidden_layers": 32, "num_attention_heads": 32, "hidden_size": 4096}), 524)

    def test_a_vision_model_counts_its_language_model(self):
        self.assertEqual(kv_cache.mb_per_1k({"vision_config": {"num_hidden_layers": 27}, "text_config": DENSE_32B}), 262)

    def test_a_hybrid_model_counts_only_its_attention_layers(self):
        kinds = ["linear_attention", "linear_attention", "linear_attention", "full_attention"] * 12
        self.assertEqual(kv_cache.mb_per_1k(dict(DENSE_32B, num_hidden_layers=48, layer_types=kinds)), 49, "12 layers of 48 keep a cache that grows")
        self.assertEqual(kv_cache.mb_per_1k(dict(DENSE_32B, num_hidden_layers=48, full_attention_interval=4)), 49)
        sliding = ["sliding_attention"] * 5 + ["full_attention"]
        self.assertEqual(kv_cache.mb_per_1k(dict(DENSE_32B, num_hidden_layers=6, layer_types=sliding)), 25, "sliding layers are counted whole: cautious")

    def test_a_file_that_does_not_say_gives_nothing_rather_than_a_guess(self):
        for config in ({}, {"num_hidden_layers": 64}, None, [], {"num_hidden_layers": True, "num_attention_heads": 8, "head_dim": 128}, {"num_hidden_layers": "64", "num_attention_heads": 8, "head_dim": 128}):
            self.assertIsNone(kv_cache.mb_per_1k(config), repr(config))


class FromRepository(unittest.TestCase):
    def test_the_config_of_a_branch_is_asked_once_and_a_failure_is_not_kept(self):
        from lutin import core as _m  # noqa: F401  (before the catalogue: circular import otherwise)
        from lutin import exllamav3_catalog as C
        C.KV.clear()
        C.CACHE.clear()
        asked = []

        def hf(url, headers=None):
            asked.append(url)
            return (200, {}, json.dumps(DENSE_32B).encode()) if "ok/" in url else (404, {}, b"")
        self.assertEqual(C.kv_of("ok/Big-32B-exl3", "4.0bpw", hf), 262)
        self.assertEqual(C.kv_of("ok/Big-32B-exl3", "4.0bpw", hf), 262)
        self.assertEqual(asked, ["https://huggingface.co/ok/Big-32B-exl3/resolve/4.0bpw/config.json"])
        self.assertIsNone(C.kv_of("no/Gated-exl3", "main", hf))
        self.assertIsNone(C.kv_of("no/Gated-exl3", "main", hf))
        self.assertEqual(len(asked), 3, "a repository that did not answer is asked again later")
        self.assertIsNone(C.kv_of("../etc", "main", hf), "a name that is not a repository is not asked")
        self.assertEqual(len(asked), 3)


class FromFolder(unittest.TestCase):
    def test_a_model_on_disk_is_read_again_only_when_its_file_changes(self):
        folder = Path(tempfile.mkdtemp(prefix="lutin-kv-"))
        self.assertIsNone(kv_cache.of_folder(folder), "no config.json")
        (folder / "config.json").write_text(json.dumps(DENSE_32B), encoding="utf-8")
        self.assertEqual(kv_cache.of_folder(folder), 262)
        (folder / "config.json").write_text("{broken", encoding="utf-8")
        os.utime(folder / "config.json", (1, 1))
        self.assertIsNone(kv_cache.of_folder(folder))


class TheGuardCountsIt(unittest.TestCase):
    def test_exllamav3_reserves_the_cache_of_its_window_before_the_model_loads(self):
        """TabbyAPI reserves the whole cache at load, on the card alone: the guard let a 27B of 16.5 GB load into 18 GB free, and TabbyAPI failed."""
        from unittest import mock
        from lutin import core as _m, engines, exllamav3, health
        models = Path(tempfile.mkdtemp(prefix="lutin-kv-exl-"))
        (models / "Big-32B").mkdir()
        (models / "Big-32B" / "config.json").write_text(json.dumps(DENSE_32B), encoding="utf-8")
        exl = engines.ENGINES["exllamav3"]
        with mock.patch.object(exllamav3, "folder_models", lambda dossiers=None: models):
            self.assertEqual(round(exl.cache_reserve("Big-32B", 36864) / 1024 ** 3, 1), 4.7, "262 MB per 1,000 tokens at 16 bits, in Q8, for 36,864 tokens")
            self.assertEqual(round(exl.cache_reserve("Other", 36864) / 1024 ** 3, 1), 2.2, "no config.json: the cautious estimate")
            self.assertEqual(exl.cache_reserve("../Big-32B", 36864), 0, "a name outside the models' folder is not read")
            self.assertEqual(engines.ENGINES["llamacpp"].cache_reserve("Big-32B", 36864), 0, "llama.cpp spills to the processor instead of failing")
            r = dict(_m.settings(), moteur="exllamav3", modele="Big-32B", num_ctx=36864)
            self.assertGreater(health._cache_reserve(r, None), 4 * 1024 ** 3)
            self.assertEqual(health._cache_reserve(r, {"taille": 0, "vram": 0}), 0, "once loaded, nothing more is reserved")


if __name__ == "__main__":
    unittest.main()
