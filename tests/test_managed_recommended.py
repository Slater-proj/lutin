"""« Recommended for this machine » (managed_models.recommended): the models that run well here, each with the quantisation to take. Hermetic: the catalogue, the quantisations, the disk
and the judgement of the machine are replaced; nothing is read from Hugging Face."""
import unittest
from unittest import mock

import context  # noqa: F401
from lutin import core as _m  # noqa: E402,F401  (before the others: circular import otherwise)
from lutin import managed_models as MM  # noqa: E402


def judge(gb, kv=None):
    """A card of 24 GB: up to 8 GB ideal, up to 18 good, up to 22 borderline, above too big."""
    level = "ideal" if gb <= 8 else "bien" if gb <= 18 else "limite" if gb <= 22 else "trop_gros"
    return {"niveau": level, "texte": "x"}


REPOS = {
    "o/Small-8B-exl3": 5.2, "o/Mid-27B-exl3": 16.0, "o/Big-70B-exl3": 40.0, "o/Edge-32B-exl3": 19.0, "o/Broken-14B-exl3": 9.0,
}
QUANTS = {
    "o/Small-8B-exl3": [{"revision": "4.0bpw", "go": 5.2}, {"revision": "6.0bpw", "go": 7.4}, {"revision": "8.0bpw", "go": 9.5}],
    "o/Mid-27B-exl3": [{"revision": "3.0bpw", "go": 11.9}, {"revision": "4.0bpw", "go": 14.7}, {"revision": "5.0bpw", "go": 17.9}, {"revision": "6.0bpw", "go": 21.0}],
    "o/Big-70B-exl3": [{"revision": "2.0bpw", "go": 19.5}, {"revision": "3.0bpw", "go": 28.0}],
    "o/Edge-32B-exl3": [{"revision": "4.0bpw", "go": 19.0}],
}


def search(words, order, community, page):
    return {"modeles": [{"id": repo, "nom": repo.split("/")[1], "estimation_go": go} for repo, go in REPOS.items()], "suite": False}


def quants(repo):
    if repo == "o/Broken-14B-exl3":
        raise ValueError("Hugging Face does not answer")
    return [dict(q) for q in QUANTS[repo]]


class Recommended(unittest.TestCase):
    def setUp(self):
        self.disk = []
        patches = (mock.patch.object(MM, "_require", return_value=mock.Mock()),
                   mock.patch.object(MM, "_on_disk", side_effect=lambda kind, mo: (self.disk, True, "/models", search, quants)),
                   mock.patch.object(MM, "_judge", return_value=judge),
                   mock.patch.object(MM, "_kv_of_repo", return_value=None))          # the config.json of each repository is not read either
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_largest_quantisation_that_runs_well_is_taken_and_the_largest_model_comes_first(self):
        got = MM.recommended("exllamav3")
        self.assertEqual([(x["id"], x["revision"], x["go"]) for x in got], [("o/Mid-27B-exl3", "5.0bpw", 17.9), ("o/Small-8B-exl3", "8.0bpw", 9.5)],
                         "27B at 5 bits (17.9 GB, good) before the 8B at 8 bits; 6 bits of the 27B is borderline: not recommended")
        self.assertEqual([x["adequation"]["niveau"] for x in got], ["bien", "bien"])

    def test_a_model_too_big_or_only_borderline_is_not_recommended_and_an_unreadable_repository_does_not_stop_the_others(self):
        ids = [x["id"] for x in MM.recommended("exllamav3")]
        self.assertNotIn("o/Big-70B-exl3", ids, "too big: its estimate already says so")
        self.assertNotIn("o/Edge-32B-exl3", ids, "its only quantisation is borderline")
        self.assertNotIn("o/Broken-14B-exl3", ids, "its sizes cannot be read")

    def test_what_is_already_on_disk_is_marked(self):
        self.disk.append({"nom": "Mid-27B-exl3", "depot": "o/Mid-27B-exl3", "revision": "5.0bpw"})
        got = {x["id"]: x["installe"] for x in MM.recommended("exllamav3")}
        self.assertEqual(got, {"o/Mid-27B-exl3": True, "o/Small-8B-exl3": False})

    def test_nothing_fits_is_an_empty_list(self):
        with mock.patch.object(MM, "_judge", return_value=lambda gb, kv=None: {"niveau": "trop_gros", "texte": "x"}):
            self.assertEqual(MM.recommended("exllamav3"), [])

    def test_a_machine_that_is_not_detected_recommends_nothing_rather_than_guess(self):
        with mock.patch.object(MM, "_judge", return_value=lambda gb, kv=None: None):
            self.assertEqual(MM.recommended("exllamav3"), [])

    def test_at_most_five_models(self):
        many = {"o/M%d-8B-exl3" % i: 5.0 + i / 10 for i in range(9)}
        with mock.patch.dict(REPOS, many, clear=True), mock.patch.dict(QUANTS, {repo: [{"revision": "4.0bpw", "go": go}] for repo, go in many.items()}, clear=True):
            got = MM.recommended("exllamav3")
        self.assertEqual(len(got), MM.RECOMMENDED)
        self.assertEqual([x["go"] for x in got], sorted((x["go"] for x in got), reverse=True))

    def test_colibri_judges_for_itself(self):
        entries = [{"id": "big", "nom": "big", "estimation_go": 30, "adequation": {"niveau": "bien", "texte": "x"}, "installes": []},
                   {"id": "small", "nom": "small", "estimation_go": 8, "adequation": {"niveau": "bien", "texte": "x"}, "installes": []},
                   {"id": "nope", "nom": "nope", "estimation_go": 90, "adequation": {"niveau": "trop_gros", "texte": "x"}, "installes": []},
                   {"id": "have", "nom": "have", "estimation_go": 12, "adequation": {"niveau": "bien", "texte": "x"}, "installes": ["prêt"]}]
        with mock.patch.object(MM, "_on_disk", side_effect=lambda kind, mo: ([], True, "/m", None, None)), mock.patch.object(MM, "colibri_catalog", return_value={"modeles": entries}):
            self.assertEqual([x["id"] for x in MM.recommended("colibri")], ["big", "small"], "what Colibri says fits, not already prepared, the largest first")




class CarteSeule(unittest.TestCase):
    """ExLlamaV3 never spills into the computer's memory and reserves the cache of the conversation window at once (maintainer, 2026-11-21, RTX 4090 24 GB:
    a 40B at 22,8 GB judged « Juste » failed with « Insufficient VRAM in split for model and cache »)."""

    def profile(self, vram=24.0):
        from lutin import hardware
        return mock.Mock(gpu_principal=lambda: hardware.Gpu(nom="RTX 4090", fabricant="nvidia", vram_go=vram), sans_gpu=lambda: False, budget_go=lambda: round(vram * 0.85, 1), gpus=[])

    def test_a_model_that_fits_only_by_spilling_is_too_big_for_exllamav3(self):
        from lutin import model_fit
        verdict = model_fit.evaluer_carte_seule(22.8, self.profile(), 32768)
        self.assertEqual(verdict["niveau"], "trop_gros")
        self.assertIn("32768", verdict["texte"])
        self.assertIn(model_fit.evaluer_carte_seule(15.7, self.profile(), 32768)["niveau"], ("bien", "ideal"))
        self.assertEqual(model_fit.evaluer_carte_seule(22.8, self.profile(48.0), 32768)["niveau"], "ideal", "a larger card takes it")

    def test_the_models_of_exllamav3_are_judged_on_the_card_alone(self):
        from lutin import managed_models, model_fit
        with mock.patch.object(model_fit, "profil_pret", lambda *a: self.profile()), mock.patch.object(managed_models, "_context_size", lambda: 32768):
            self.assertEqual(managed_models._judge("exllamav3")(22.8)["niveau"], "trop_gros")
            self.assertNotEqual(managed_models._judge("lmstudio")(22.8)["niveau"], "trop_gros", "LM Studio (llama.cpp) can put part of a model in memory")

    def test_the_cache_of_the_model_itself_is_counted_when_its_config_says_it(self):
        """Maintainer (2026-11-21): « Juste » was too kind to a 27-32B on ExLlamaV3. Every model was counted 120 MB per 1,000 tokens; a 32B with 64 layers,
        8 KV heads of 128 asks 262 (lutin.kv_cache): with 36,864 tokens of window, 4.7 GB of cache instead of 2.2."""
        from lutin import model_fit
        guessed = model_fit.evaluer_carte_seule(17.0, self.profile(), 36864)
        exact = model_fit.evaluer_carte_seule(17.0, self.profile(), 36864, 262)
        self.assertIn(guessed["niveau"], ("bien", "ideal"))
        self.assertEqual(exact["niveau"], "limite", exact["texte"])
        self.assertEqual(model_fit.evaluer_carte_seule(17.0, self.profile(), 36864, 64)["niveau"], guessed["niveau"], "a small cache keeps the verdict")

    def test_the_quantisations_of_a_repository_are_judged_with_its_cache(self):
        from lutin import managed_models, model_fit
        asked = []
        with mock.patch.object(model_fit, "profil_pret", lambda *a: self.profile()), mock.patch.object(managed_models, "_context_size", lambda: 36864), \
                mock.patch.object(managed_models, "_require", return_value=mock.Mock()), \
                mock.patch.object(managed_models, "_on_disk", side_effect=lambda kind, mo: ([], True, "/m", None, lambda repo: [{"revision": "4.0bpw", "go": 17.0}])), \
                mock.patch.object(managed_models._exl_cat, "kv_of", lambda depot, revision="main": asked.append((depot, revision)) or 262):
            got = managed_models.quantizations("exllamav3", "o/Big-32B-exl3")
        self.assertEqual(asked, [("o/Big-32B-exl3", "4.0bpw")], "the config.json of a quantisation's own branch")
        self.assertEqual(got[0]["adequation"]["niveau"], "limite")


if __name__ == "__main__":
    unittest.main()
