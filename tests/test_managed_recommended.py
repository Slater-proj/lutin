"""« Recommended for this machine » (managed_models.recommended): the models that run well here, each with the quantisation to take. Hermetic: the catalogue, the quantisations, the disk
and the judgement of the machine are replaced; nothing is read from Hugging Face."""
import unittest
from unittest import mock

import context  # noqa: F401
from lutin import core as _m  # noqa: E402,F401  (before the others: circular import otherwise)
from lutin import managed_models as MM  # noqa: E402


def judge(gb):
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
                   mock.patch.object(MM, "_judge", return_value=judge))
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
        with mock.patch.object(MM, "_judge", return_value=lambda gb: {"niveau": "trop_gros", "texte": "x"}):
            self.assertEqual(MM.recommended("exllamav3"), [])

    def test_a_machine_that_is_not_detected_recommends_nothing_rather_than_guess(self):
        with mock.patch.object(MM, "_judge", return_value=lambda gb: None):
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


if __name__ == "__main__":
    unittest.main()
