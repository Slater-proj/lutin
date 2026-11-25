"""ADR 0020, stage 2: `/api/v1/engines/{id}/models*`, the models of any engine in the same way, on the real server of tests/test_api_v1.py.

Nothing is installed, downloaded or searched on the network: what an engine knows (its installed models, its library, its catalogue of Hugging Face) is replaced
by data, and the engine in use is chosen by the test."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import agent, api_v1, engines, managed_models, model_compat, model_discovery, model_fit, model_sources, model_variants  # noqa: E402

A = V.A
ENTRY_KEYS = ["approximate", "download", "fit", "has_variants", "id", "in_use", "incomplete", "installed", "name", "removable", "revision", "size_gb", "strengths", "summary"]
TOO_BIG = {"niveau": "trop_gros", "texte": "Too big for this machine."}
GOOD = {"niveau": "bien", "texte": "Fits."}


def setUpModule():
    V.setUpModule()


def get(path, who=None):
    return V.call("GET", "/api/v1" + path, V.OWNER if who is None else who)


class InUse(unittest.TestCase):
    """The engine in use is chosen here; the machine is not measured unless a test gives it; the network is on."""

    def use(self, identifier):
        for patch in (mock.patch.object(agent, "local_engine", lambda r=None: engines.ENGINES[identifier]), mock.patch.object(model_fit, "ready_profile", lambda *a: None),
                      mock.patch.object(model_sources._offline, "is_active", lambda *a, **k: False), mock.patch.dict(engines.CONTEXT, hors_ligne=lambda: False)):
            patch.start()
            self.addCleanup(patch.stop)


class Entries(unittest.TestCase):
    def test_a_model_is_downloaded_unless_something_says_why_not(self):
        with mock.patch.object(model_sources._offline, "is_active", lambda *a, **k: False), mock.patch.dict(engines.CONTEXT, hors_ligne=lambda: False):
            self.assertEqual(model_sources.download_state(GOOD), {"possible": True, "reason": ""})
            self.assertEqual(model_sources.download_state(TOO_BIG), {"possible": False, "reason": "Too big for this machine."})
            self.assertEqual(model_sources.download_state(GOOD, {"possible": False, "raison": "A format this engine cannot read."}), {"possible": False, "reason": "A format this engine cannot read."})
            self.assertFalse(model_sources.download_state(GOOD, installed=True)["possible"])
        with mock.patch.dict(engines.CONTEXT, hors_ligne=lambda: True):
            self.assertIn("hors ligne", model_sources.download_state(GOOD)["reason"].lower())

    def test_an_entry_has_the_same_fields_whatever_the_source(self):
        made = model_sources.entry("owner/model", fit=GOOD, size_gb=5.0, revision="4.0bpw")
        self.assertEqual(sorted(made), ENTRY_KEYS)
        self.assertEqual((made["name"], made["revision"], made["fit"]), ("model", "4.0bpw", {"level": "good", "text": "Fits."}))
        self.assertEqual(sorted(model_sources.entry("qwen3:8b")), ENTRY_KEYS)


class Strengths(unittest.TestCase):
    def test_a_model_of_the_catalogue_says_what_it_is_good_at_the_best_first(self):
        """The catalogue tab of Ollama said a model's strengths; since the Models screen is the same for every engine (2026-11-22), the common entry carries them."""
        self.assertEqual(model_sources.strengths_of({"notes": {"polyvalent": 7, "code": 9, "vision": 2, "rapide": 6}}), ["code", "general"])
        self.assertEqual(model_sources.strengths_of({}), [])
        self.assertEqual(model_sources.entry("m")["strengths"], [], "a source that does not rate its models says nothing")


class Ollama(InUse):
    def setUp(self):
        self.use("ollama")
        installed = {"actif": True, "installes": ["qwen3:8b"], "tailles": {"qwen3:8b": 5_200_000_000}}
        patch = mock.patch.object(engines.ENGINES["ollama"], "modeles", lambda: installed)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_installed_models_with_their_size(self):
        status, answer = get("/engines/ollama/models")
        self.assertEqual((status, answer["engine"]), (200, "ollama"))
        self.assertEqual([(m["id"], m["installed"], m["size_gb"]) for m in answer["models"]], [("qwen3:8b", True, 5.2)])
        self.assertEqual(sorted(answer["models"][0]), ENTRY_KEYS)

    def test_the_search_gives_the_catalogue_then_the_library_of_ollama_com_one_entry_per_size(self):
        library = {"modeles": [{"nom": "gemma3", "description": "Google's.", "tailles": ["4b", "12b"], "capacites": [], "maj": "", "telechargements": 9}], "suite": True}
        with mock.patch.object(model_discovery, "search", lambda *a, **k: library), mock.patch.object(model_discovery, "evaluate_sizes", lambda models, judge: [dict(m, evaluations={"4b": {"go": 3.3, "niveau": "bien", "texte": "Fits."}}) for m in models]):
            status, answer = get("/engines/ollama/models/search?q=gemma")
        self.assertEqual(status, 200, answer)
        names = [m["id"] for m in answer["models"]]
        self.assertIn("gemma3:4b", names)
        self.assertIn("gemma3:12b", names, "a size whose weight is unknown is still offered")
        self.assertTrue(answer["more"])
        for model in answer["models"]:
            self.assertEqual(sorted(model), ENTRY_KEYS)
            self.assertEqual(sorted(model["download"]), ["possible", "reason"])

    def test_the_search_keeps_the_order_and_the_capability_and_gives_a_model_once(self):
        asked = []
        library = {"modeles": [{"nom": "gemma3", "description": "Google's.", "tailles": ["4b"], "capacites": ["vision"], "maj": "", "telechargements": 9}], "suite": False}
        catalogue = {"modeles": [{"id": "gemma3:4b", "nom": "Gemma 3", "phrase": "Sees images.", "go": 3.3, "capacites": ["vision"]},
                                 {"id": "qwen3:8b", "nom": "Qwen 3", "phrase": "Writes.", "go": 5.2, "capacites": ["outils"]}]}
        with (mock.patch.object(model_discovery, "search", lambda *a, **k: asked.append((a, k)) or library), mock.patch.dict(A._CATALOGUE, catalogue),
              mock.patch.object(model_compat, "evaluate", lambda *a: {"compatible": True, "raisons": []}),
              mock.patch.object(model_discovery, "evaluate_sizes", lambda models, judge: [dict(m, evaluations={}) for m in models])):
            status, answer = get("/engines/ollama/models/search?order=popular&capability=vision")
            self.assertEqual(status, 200, answer)
            self.assertEqual([m["id"] for m in answer["models"]], ["gemma3:4b"], "the catalogue filtered by the capability, and ollama.com's gemma3:4b not twice")
            self.assertEqual(asked, [(("", "popular", 1), {"categorie": "vision"})])
            self.assertEqual(get("/engines/ollama/models/search?capability=flying")[1]["error"]["code"], "invalid_request")

    def test_the_precisions_of_a_model(self):
        found = {"defaut": None, "variantes": [{"id": "qwen3:8b-q4_K_M", "precision": "q4_K_M", "go": 5.0, "defaut": True}, {"id": "qwen3:8b-q8_0", "precision": "q8_0", "go": 8.7}]}
        with mock.patch.object(model_variants, "list_variants", lambda ref: found):
            status, answer = get("/engines/ollama/models/variants?ref=qwen3:8b")
        self.assertEqual(status, 200, answer)
        self.assertEqual([(v["id"], v["revision"], v["size_gb"], v["default"]) for v in answer["variants"]], [("qwen3:8b-q4_K_M", "q4_K_M", 5.0, True), ("qwen3:8b-q8_0", "q8_0", 8.7, False)])
        self.assertEqual(get("/engines/ollama/models/variants")[0], 400)

    def test_a_download_waits_for_its_confirmation_and_starts_as_a_task_of_the_engine_in_use(self):
        started = []
        with mock.patch.object(agent, "install_model", lambda ref: started.append(ref) or {"statut": "en cours"}):
            self.assertEqual(V.call("POST", "/api/v1/engines/ollama/models/downloads", V.OWNER, {"ref": "qwen3:14b"})[1]["error"]["code"], "confirmation_required")
            self.assertEqual(V.call("POST", "/api/v1/engines/ollama/models/downloads", V.DEVICE, {"ref": "qwen3:14b", "confirm": True})[0], 403, "a paired phone may not download")
            self.assertEqual(started, [])
            status, answer = V.call("POST", "/api/v1/engines/ollama/models/downloads", V.OWNER, {"ref": "qwen3:14b", "confirm": True})
        self.assertEqual((status, answer), (202, {"started": True, "engine": "ollama"}))
        self.assertEqual(started, ["qwen3:14b"])

    def test_a_removal_goes_through_the_engine_in_use(self):
        removed = []
        with mock.patch.object(agent, "delete_model", lambda name: removed.append(name)):
            self.assertEqual(V.call("DELETE", "/api/v1/engines/ollama/models/qwen3%3A8b", V.DEVICE)[0], 403)
            status, answer = V.call("DELETE", "/api/v1/engines/ollama/models/qwen3%3A8b", V.OWNER)
        self.assertEqual((status, answer["deleted"], removed), (200, True, ["qwen3:8b"]))

    def test_the_recommended_models_are_the_ones_this_machine_runs_well_the_largest_first(self):
        small = {"id": "qwen3:4b", "nom": "Qwen3 4B", "go": 2.6, "phrase": "Small."}
        large = {"id": "qwen3:14b", "nom": "Qwen3 14B", "go": 9.3, "phrase": "Large."}
        roles = {"rapide": mock.Mock(id="qwen3:4b", modele=small), "polyvalent": mock.Mock(id="qwen3:14b", modele=large)}
        with mock.patch.object(model_fit, "ready_profile", lambda *a: mock.Mock()), mock.patch.object(model_fit, "judge", lambda *a, **k: GOOD), mock.patch.object(model_compat, "roles_for", lambda *a: roles):
            status, answer = get("/engines/ollama/models/recommended")
        self.assertEqual([m["id"] for m in answer["models"]], ["qwen3:14b", "qwen3:4b"])
        self.assertEqual(answer["models"][0]["fit"], {"level": "good", "text": "Fits."})


class LlamaCpp(InUse):
    def setUp(self):
        self.use("llamacpp")
        engine = engines.ENGINES["llamacpp"]
        for name, value in (("modeles", lambda: {"actif": True, "installes": ["m.gguf"], "tailles": {}}), ("telechargeable", lambda: {"possible": True, "raison": "", "genre": "huggingface"}),
                            ("chercher_modeles", lambda words: [{"id": "owner/Model-GGUF", "telechargements": 12, "likes": 1}]),
                            ("fichiers_du_depot", lambda repo: [{"fichier": "Model-Q4_K_M.gguf", "taille": 4_900_000_000}, {"fichier": "Model-Q8_0.gguf", "taille": 8_500_000_000}])):
            patch = mock.patch.object(engine, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_hugging_face_is_searched_for_words_and_each_repository_has_its_files(self):
        status, answer = get("/engines/llamacpp/models/search?q=model")
        self.assertEqual(status, 200, answer)
        self.assertIn("owner/Model-GGUF", [m["id"] for m in answer["models"]])
        found = next(m for m in answer["models"] if m["id"] == "owner/Model-GGUF")
        self.assertEqual((sorted(found), found["has_variants"]), (ENTRY_KEYS, True))
        status, answer = get("/engines/llamacpp/models/variants?ref=owner/Model-GGUF")
        self.assertEqual([(v["revision"], v["size_gb"]) for v in answer["variants"]], [("Model-Q4_K_M.gguf", 4.9), ("Model-Q8_0.gguf", 8.5)])

    def test_a_file_of_a_repository_is_downloaded_as_a_task_and_a_repository_alone_is_refused(self):
        tasks = []
        with mock.patch.object(engines, "launch_task", lambda engine, action, run=None: tasks.append((engine.id, action)) or {}):
            status, answer = V.call("POST", "/api/v1/engines/llamacpp/models/downloads", V.OWNER, {"ref": "owner/Model-GGUF", "revision": "Model-Q4_K_M.gguf", "confirm": True})
            self.assertEqual((status, tasks), (202, [("llamacpp", "telecharger")]))
            status, answer = V.call("POST", "/api/v1/engines/llamacpp/models/downloads", V.OWNER, {"ref": "owner/Model-GGUF", "confirm": True})
        self.assertEqual((status, answer["error"]["code"]), (400, "action_impossible"), "a file must be chosen first")

    def test_the_machine_not_yet_detected_gives_no_verdict_but_still_lists_the_files(self):
        """Kept from the old /engines/{id}/library/files (ADR 0020, stage 4): the profile is not measured here (InUse)."""
        status, answer = get("/engines/llamacpp/models/variants?ref=owner/Model-GGUF")
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer["variants"] and all(v["fit"] is None for v in answer["variants"]), answer)

    def test_strict_offline_mode_searches_the_catalogue_only_and_refuses_the_files_and_the_download(self):
        """Kept from the old /engines/{id}/library (ADR 0020, stage 4), which refused all three offline. The new search still gives the catalogue of Lutin, which is local;
        Hugging Face is not asked (before this, it was: the new family had lost the check)."""
        asked = []
        with mock.patch.object(engines.ENGINES["llamacpp"], "chercher_modeles", lambda words: asked.append(words) or []),                 mock.patch.object(model_sources._offline, "is_active", lambda *a, **k: True), mock.patch.dict(engines.CONTEXT, hors_ligne=lambda: True),                 mock.patch.object(api_v1._offline, "is_active", return_value=True):
            status, answer = get("/engines/llamacpp/models/search?q=model")
            self.assertEqual((status, asked), (200, []), answer)
            self.assertTrue(all(not m["download"]["possible"] for m in answer["models"]), "nothing can be downloaded offline")
            for method, path, body in (("GET", "/api/v1/engines/llamacpp/models/variants?ref=owner/Model-GGUF", None),
                                       ("POST", "/api/v1/engines/llamacpp/models/downloads", {"ref": "owner/Model-GGUF", "revision": "Model-Q4_K_M.gguf", "confirm": True})):
                status, answer = V.call(method, path, V.OWNER, body)
                self.assertEqual((status, answer.get("error", {}).get("code")), (409, "offline"), path)

    def test_hugging_face_is_not_reached_in_strict_offline_mode(self):
        """The request itself is refused before any connection (`llamacpp_engine._http_json` calls `offline.guard`)."""
        from lutin import llamacpp_engine, offline
        with mock.patch.object(offline, "is_active", lambda *a, **k: True), mock.patch.object(llamacpp_engine.urllib.request, "urlopen", side_effect=AssertionError("no connection")):
            with self.assertRaises(offline.OfflineError):
                llamacpp_engine._http_json("https://huggingface.co/api/models?search=x")


class Managed(InUse):
    def setUp(self):
        self.use("exllamav3")
        for name, value in (("chosen", lambda kind: kind == "exllamav3"),
                            ("models", lambda kind, current: {"modeles": [{"nom": "Qwen3-8B-exl3_4.0bpw", "depot": "turboderp/Qwen3-8B-exl3", "revision": "4.0bpw", "taille_go": 5.5, "adequation": GOOD, "utilise": True}],
                                                              "installe": True, "actif": True, "nom": "ExLlamaV3", "statut": "", "dossier": "C:/m", "maj": True}),
                            ("recommended", lambda kind: [{"id": "turboderp/Qwen3-27B-exl3", "nom": "Qwen3-27B-exl3", "revision": "4.0bpw", "go": 15.7, "adequation": GOOD, "installe": False}]),
                            ("catalog", lambda *a: {"suite": False, "modeles": [{"id": "turboderp/Gemma-exl3", "nom": "Gemma-exl3", "estimation_go": 9.0, "adequation": TOO_BIG, "installes": [], "direct": False}]}),
                            ("quantizations", lambda kind, repo: [{"revision": "3.0bpw", "go": 6.0, "adequation": GOOD, "installe": False}])):
            patch = mock.patch.object(managed_models, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_same_shape_as_every_other_engine(self):
        for path in ("/engines/exllamav3/models", "/engines/exllamav3/models/recommended", "/engines/exllamav3/models/search", "/engines/exllamav3/models/variants?ref=turboderp/Gemma-exl3"):
            status, answer = get(path)
            self.assertEqual(status, 200, (path, answer))
            for model in answer.get("models") or answer["variants"]:
                self.assertEqual(sorted(model), ENTRY_KEYS, path)
        installed = get("/engines/exllamav3/models")[1]["models"][0]
        self.assertEqual((installed["id"], installed["revision"], installed["in_use"], installed["installed"]), ("turboderp/Qwen3-8B-exl3", "4.0bpw", True, True))

    def test_a_model_too_big_for_the_card_says_why_it_cannot_be_downloaded(self):
        found = get("/engines/exllamav3/models/search?q=gemma")[1]["models"][0]
        self.assertEqual((found["fit"]["level"], found["download"]["possible"]), ("too_big", False))
        self.assertEqual(found["download"]["reason"], "Too big for this machine.")

    def test_a_download_goes_to_the_server_after_its_confirmation(self):
        started = []
        with mock.patch.object(managed_models, "download", lambda *args: started.append(args)):
            status, answer = V.call("POST", "/api/v1/engines/exllamav3/models/downloads", V.OWNER, {"ref": "turboderp/Qwen3-27B-exl3", "revision": "4.0bpw", "confirm": True})
        self.assertEqual((status, started), (202, [("exllamav3", "turboderp/Qwen3-27B-exl3", "4.0bpw")]))

    def test_an_engine_that_is_not_the_one_in_use_is_refused(self):
        with mock.patch.object(managed_models, "chosen", lambda kind: False):
            for method, path, body in (("GET", "/engines/exllamav3/models", None), ("GET", "/engines/exllamav3/models/recommended", None),
                                       ("POST", "/engines/exllamav3/models/downloads", {"ref": "a/b", "confirm": True})):
                status, answer = V.call(method, "/api/v1" + path, V.OWNER, body)
                self.assertEqual((status, answer["error"]["code"]), (409, "not_chosen"), path)
        self.use("ollama")          # llama.cpp asked while Ollama is in use
        self.assertEqual(V.call("POST", "/api/v1/engines/llamacpp/models/downloads", V.OWNER, {"ref": "a:b", "confirm": True})[1]["error"]["code"], "not_chosen")


    def test_an_incomplete_download_is_said_and_a_model_lutin_did_not_put_there_is_not_removed(self):
        seen = {"modeles": [{"nom": "half", "depot": "a/half", "taille_go": 1.0, "incomplet": True},
                            {"nom": "theirs", "chemin": "D:/theirs", "taille_go": 9.0, "supprimable": False}], "installe": True, "nom": "ExLlamaV3"}
        removed = []
        with mock.patch.object(managed_models, "models", lambda kind, current: seen), mock.patch.object(agent, "delete_model", removed.append):
            half, theirs = get("/engines/exllamav3/models")[1]["models"]
            self.assertEqual((half["incomplete"], half["removable"]), (True, True))
            self.assertEqual((theirs["incomplete"], theirs["removable"]), (False, False))
            status, answer = V.call("DELETE", "/api/v1/engines/exllamav3/models/theirs", V.OWNER)
            self.assertEqual((status, answer["error"]["code"], removed), (400, "invalid_request", []))
            self.assertEqual(V.call("DELETE", "/api/v1/engines/exllamav3/models/half", V.OWNER)[0], 200)
        self.assertEqual(removed, ["half"])

    def test_the_search_keeps_its_order_and_the_other_authors(self):
        asked = []
        with mock.patch.object(managed_models, "catalog", lambda *args: asked.append(args) or {"suite": True, "modeles": []}):
            status, answer = get("/engines/exllamav3/models/search?q=qwen&order=popular&community=1&page=2")
            self.assertEqual((status, answer.get("more")), (200, True), answer)
            self.assertEqual(get("/engines/exllamav3/models/search?order=sideways")[1]["error"]["code"], "invalid_request")
        self.assertEqual(asked, [("exllamav3", "qwen", "populaire", True, 2)])

    def test_a_catalogue_that_cannot_be_read_is_a_gateway_error_not_a_crash(self):
        def unreadable(*args):
            raise ValueError("Hugging Face does not answer.")
        for name, path in (("catalog", "/models/search"), ("recommended", "/models/recommended"), ("models", "/models")):
            with self.subTest(name), mock.patch.object(managed_models, name, unreadable):
                status, answer = get("/engines/exllamav3" + path)
                self.assertEqual((status, answer["error"]["code"], answer["error"]["message"]), (502, "unreachable", "Hugging Face does not answer."))

    def test_newer_versions_and_new_models_are_looked_for_on_demand(self):
        found = {"plus_recentes": [{"nom": "Qwen3-8B-exl3", "depot": "turboderp/Qwen3-8B-exl3", "revision": "4.0bpw"}], "erreurs": ["one repository did not answer"]}
        new = {"propositions": [{"id": "turboderp/Gemma-exl3", "nom": "Gemma-exl3", "estimation_go": 9.0, "adequation": GOOD, "installes": [], "direct": False}]}
        with mock.patch.object(managed_models, "check", lambda kind, scope: found if scope == "maj" else new):
            status, answer = V.call("POST", "/api/v1/engines/exllamav3/models/check", V.OWNER, {"scope": "updates"})
            self.assertEqual(status, 200, answer)
            self.assertEqual([(m["id"], m["revision"]) for m in answer["models"]], [("turboderp/Qwen3-8B-exl3", "4.0bpw")])
            self.assertEqual(answer["errors"], ["one repository did not answer"])
            status, answer = V.call("POST", "/api/v1/engines/exllamav3/models/check", V.OWNER, {"scope": "new"})
            self.assertEqual(([m["id"] for m in answer["models"]], answer["models"][0]["has_variants"], answer["errors"]), (["turboderp/Gemma-exl3"], True, []))
            for model in answer["models"]:
                self.assertEqual(sorted(model), ENTRY_KEYS)
            self.assertEqual(V.call("POST", "/api/v1/engines/exllamav3/models/check", V.OWNER, {"scope": "sideways"})[1]["error"]["code"], "invalid_request")
        with mock.patch.object(managed_models, "chosen", lambda kind: kind == "lmstudio"):
            self.use("lmstudio")
            status, answer = V.call("POST", "/api/v1/engines/lmstudio/models/check", V.OWNER, {"scope": "updates"})
            self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"), "only ExLlamaV3 knows the newer versions of what it downloaded")
        self.use("ollama")          # Ollama's models are kept current by the proposals (POST /models/check)
        status, answer = V.call("POST", "/api/v1/engines/ollama/models/check", V.OWNER, {"scope": "new"})
        self.assertEqual((status, answer["error"]["code"]), (400, "action_impossible"))


class Detecting(InUse):
    def test_recommendations_before_the_machine_is_measured_say_so_instead_of_an_empty_list(self):
        """Maintainer, 2026-11-22: « dans la page Modèles de ExLlamaV3, rien du tout proposé ». The first visit starts the measure of the machine; the list was
        empty and the page said « nothing fits » for good. Now `detecting` says it, and the page asks again."""
        self.use("ollama")
        status, answer = get("/engines/ollama/models/recommended")          # InUse: the profile is not known
        self.assertEqual((status, answer["models"], answer["detecting"]), (200, [], True), answer)


class Address(InUse):
    def test_a_server_reached_by_its_address_shows_its_models_and_downloads_nothing(self):
        self.use("openai")
        with mock.patch.object(engines.ENGINES["openai"], "modeles", lambda: {"actif": True, "installes": ["served-model"], "tailles": {}}):
            status, answer = get("/engines/openai/models")
            self.assertEqual([(m["id"], m["installed"]) for m in answer["models"]], [("served-model", True)])
            self.assertEqual(get("/engines/openai/models/search?q=x")[1]["models"], [])
            status, answer = V.call("POST", "/api/v1/engines/openai/models/downloads", V.OWNER, {"ref": "x", "confirm": True})
        self.assertEqual((status, answer["error"]["code"]), (400, "action_impossible"))
        self.assertEqual(get("/engines/inconnu/models")[0], 404)


if __name__ == "__main__":
    unittest.main()
