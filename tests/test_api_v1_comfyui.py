"""`/api/v1/addons/comfyui/panel`: the ComfyUI panel in English names and its five actions, on the real server of tests/test_api_v1.py. ComfyUI itself is not probed (its own logic
is tested in test_comfyui.py): the state it would give and the action it would take are replaced, so the translation and the guards are what is checked."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import addons_comfyui, api_v1  # noqa: E402

PANEL = "/api/v1/addons/comfyui/panel"
RAW = {"tourne": True, "erreur": "", "version": "0.3.1", "gpu": "RTX", "dossier": "C:/ComfyUI", "dossier_regle": "C:/ComfyUI", "valide": True, "raison": "", "lancement": True,
       "modeles": {"source": "api", "modeles": {"checkpoints": ["sd15.safetensors"], "diffusion_models": ["flux1-dev.safetensors", "mystery.safetensors"]}},
       "familles": {"flux1-dev.safetensors": "flux"}, "libelles_familles": {"flux": "Flux"}, "workflows": ["flux", "video_x"],
       "moteurs": {"image": ["Checkpoint", "Flux"], "video": ["video_x"], "son": []}, "inutilisables": ["mystery.safetensors"],
       "telechargement": {"etat": "en cours", "nom": "big.safetensors", "fait": 5, "total": 10, "erreur": ""}, "genres": ["checkpoints", "loras"]}


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


class Panel(unittest.TestCase):
    def setUp(self):
        self.taken = []
        for patch in (mock.patch.object(addons_comfyui, "etat", side_effect=lambda: dict(RAW)),
                      mock.patch.object(addons_comfyui, "action", side_effect=lambda name, data: self.taken.append((name, data)) or {})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_panel_is_given_in_english_names(self):
        status, answer = call("GET", PANEL)
        self.assertEqual(status, 200)
        panel = answer["panel"]
        self.assertEqual(sorted(panel), ["can_launch", "download", "download_kinds", "engines", "error", "families", "family_labels", "folder", "folder_problem", "folder_set", "folder_valid",
                                         "gpu", "models", "running", "unusable_models", "version", "workflows"])
        self.assertEqual((panel["running"], panel["folder"], panel["folder_valid"], panel["models"]["source"]), (True, "C:/ComfyUI", True, "api"))
        self.assertEqual(panel["models"]["by_kind"]["checkpoints"], ["sd15.safetensors"])
        self.assertEqual(panel["engines"], {"image": ["Checkpoint", "Flux"], "video": ["video_x"], "sound": []})
        self.assertEqual(panel["download"], {"state": "running", "name": "big.safetensors", "done_bytes": 5, "total_bytes": 10, "error": ""})
        self.assertEqual(panel["unusable_models"], ["mystery.safetensors"])

    def test_an_idle_download_and_a_failed_one_have_their_own_state_and_the_models_may_come_from_the_folder(self):
        for stored, expected in (("", "idle"), ("fini", "done"), ("erreur", "failed")):
            raw = dict(RAW, telechargement={"etat": stored, "nom": "", "fait": 0, "total": 0, "erreur": ""}, modeles={"source": "dossier", "modeles": {}})
            with mock.patch.object(addons_comfyui, "etat", return_value=raw):
                panel = call("GET", PANEL)[1]["panel"]
            self.assertEqual((panel["download"]["state"], panel["models"]["source"]), (expected, "folder"))

    def test_the_simple_actions_reach_the_add_on_with_its_own_names(self):
        for english, french, body, data in (("detect", "detecter", {}, {}), ("refresh_models", "modeles", {}, {}), ("use_folder", "utiliser_dossier", {"folder": "C:/X"}, {"dossier": "C:/X"}),
                                            ("cancel_download", "annuler_telechargement", {}, {})):
            status, answer = call("POST", PANEL + "/" + english, body)
            self.assertEqual(status, 200, english)
            self.assertIn("running", answer["panel"])
            self.assertEqual(self.taken[-1], (french, data), english)

    def test_a_download_needs_the_confirmation_and_the_network_and_only_known_fields(self):
        body = {"url": "https://huggingface.co/a/b/resolve/main/m.safetensors", "kind": "loras"}
        with mock.patch.object(api_v1._offline, "is_active", return_value=False):
            for refused in (dict(body), dict(body, confirm=False)):
                status, answer = call("POST", PANEL + "/download", refused)
                self.assertEqual((status, answer["error"]["code"]), (400, "confirmation_required"), refused)
            for refused in (dict(body, confirm="yes"), dict(body, confirm=True, extra=1)):
                self.assertEqual(call("POST", PANEL + "/download", refused)[1]["error"]["code"], "invalid_request", refused)
            self.assertEqual(self.taken, [], "nothing was started")
            status, answer = call("POST", PANEL + "/download", dict(body, confirm=True))
            self.assertEqual(status, 200, answer)
            self.assertEqual(self.taken, [("telecharger", {"url": body["url"], "genre": "loras"})], "`confirm` is not passed on to the add-on")
        with mock.patch.object(api_v1._offline, "is_active", return_value=True):
            self.assertEqual(call("POST", PANEL + "/download", dict(body, confirm=True))[1]["error"]["code"], "offline")
            self.assertEqual(call("POST", PANEL + "/download", body)[1]["error"]["code"], "confirmation_required", "the confirmation comes first")
            self.assertEqual(call("POST", PANEL + "/detect", {})[0], 200, "looking for ComfyUI on this machine needs no network")
        self.assertEqual(len(self.taken), 2)

    def test_the_other_actions_refuse_unknown_fields_and_a_paired_device_is_refused(self):
        self.assertEqual(call("POST", PANEL + "/use_folder", {"folder": "x", "confirm": True})[1]["error"]["code"], "invalid_request", "only a download takes `confirm`")
        self.assertEqual(call("POST", PANEL + "/explode", {})[0], 404)
        for method, path in (("GET", PANEL), ("POST", PANEL + "/detect"), ("POST", PANEL + "/download")):
            self.assertEqual(call(method, path, {} if method == "POST" else None, who=V.DEVICE)[1]["error"]["code"], "configurator", path)


if __name__ == "__main__":
    unittest.main()
