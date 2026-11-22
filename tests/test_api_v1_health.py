"""`/api/v1/health` (docs/modernization/PARITY.md, item 2) on the real server of tests/test_api_v1.py (level « network »).

What reads this computer (memory, graphics card, the list of programs, the self-test, unloading) is replaced by fixed answers in the stored French
shapes: what is fixed here is their English fields, the rights (reading and unloading for a session, clearing a log for whoever may configure)
and the refusals."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import loaded_resources, observatory, outbound  # noqa: E402

A = V.A
HEALTH = {"niveau": "attention", "items": [{"id": "ram", "nom": "Mémoire vive (RAM)", "niveau": "ok", "valeur": "5 Go libres", "conseil": ""},
                                          {"id": "vram", "nom": "Carte graphique", "niveau": "critique", "valeur": "plein", "conseil": "Décharge un modèle."}]}
RESOURCES = {"ram": {"total": 32, "libre": 5, "engagement_libre": 10}, "vram": {"nom": "Quadro", "total": 4, "utilise": 1, "libre": 3},
             "charges": [{"id": "ollama:qwen3:8b", "genre": "ollama", "moteur": "Ollama", "nom": "qwen3:8b", "vram": 1, "ram": None, "taille": 1, "detail": "", "dechargeable": True, "fermable": False}],
             "programmes": [{"nom": "Code", "libelle": "Code", "nombre": 3, "octets": 9, "ia": False}]}


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


def setUpModule():
    V.setUpModule()


class Health(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(A, "health_state", lambda: HEALTH), mock.patch.object(loaded_resources, "state", lambda: RESOURCES)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_state_of_the_machine_under_english_names(self):
        status, answer = call("GET", "/api/v1/health", who=V.DEVICE)
        self.assertEqual((status, sorted(answer), answer["level"]), (200, ["items", "level", "resources"], "warning"), "a paired phone reads it")
        self.assertEqual(answer["items"][1], {"id": "vram", "name": "Carte graphique", "level": "critical", "value": "plein", "advice": "Décharge un modèle."})
        resources = answer["resources"]
        self.assertEqual((resources["ram"], resources["vram"]), ({"total": 32, "free": 5, "commit_free": 10}, {"name": "Quadro", "total": 4, "used": 1, "free": 3}))
        self.assertEqual(sorted(resources["loaded"][0]), ["closable", "detail", "engine", "id", "kind", "name", "ram", "size", "unloadable", "vram"])
        self.assertEqual(resources["programs"], [{"name": "Code", "label": "Code", "count": 3, "bytes": 9, "ai": False}])

    def test_unloading_and_freeing_the_graphics_memory(self):
        unloaded = []
        with mock.patch.object(loaded_resources, "unload", lambda ident: unloaded.append(ident) or {"ok": True, "message": "déchargé"}), \
                mock.patch.object(A, "free_vram", lambda tout=False: unloaded.append(("tout", tout)) or {"ok": True, "message": "libre"}):
            for body in ({}, {"id": ""}, {"id": 1}, {"id": "x", "all": True}):
                self.assertEqual(call("POST", "/api/v1/health/unload", body)[1]["error"]["code"], "invalid_request", body)
            status, answer = call("POST", "/api/v1/health/unload", {"id": "ollama:qwen3:8b"})
            self.assertEqual((status, answer["message"], sorted(answer)), (200, "déchargé", ["message", "resources"]))
            self.assertEqual(call("POST", "/api/v1/health/free-graphics-memory")[1]["message"], "libre")
        self.assertEqual(unloaded, ["ollama:qwen3:8b", ("tout", True)], "nothing is unloaded by a refused request")

    def test_the_self_test_says_each_check(self):
        result = {"ok": False, "profond": False, "resultats": [{"nom": "Moteur", "ok": False, "important": True, "detail": "arrêté", "duree": 0.1}]}
        with mock.patch.object(A, "run_selftest", lambda profond=False: dict(result, profond=profond)):
            status, answer = call("POST", "/api/v1/health/self-test", {"deep": True})
            self.assertEqual((status, answer), (200, {"ok": False, "deep": True, "checks": [{"name": "Moteur", "ok": False, "important": True, "detail": "arrêté", "seconds": 0.1}]}))
            self.assertEqual(call("POST", "/api/v1/health/self-test", {"deep": "yes"})[1]["error"]["code"], "invalid_request")

    def test_activity_and_outbound_logs_are_read_by_a_session_and_cleared_by_a_configurator(self):
        status, activity = call("GET", "/api/v1/health/activity", who=V.DEVICE)
        self.assertEqual((status, sorted(activity)), (200, ["models", "retries", "routed", "tools"]))
        status, sent = call("GET", "/api/v1/health/outbound", who=V.DEVICE)
        self.assertEqual((status, sorted(sent)), (200, ["entries"]))
        cleared = []
        with mock.patch.object(observatory, "clear", lambda: cleared.append("activity")), mock.patch.object(outbound, "clear", lambda: cleared.append("outbound")):
            for path in ("/api/v1/health/activity", "/api/v1/health/outbound"):
                self.assertEqual(call("DELETE", path, who=V.DEVICE)[1]["error"]["code"], "configurator", path)
                self.assertEqual(call("DELETE", path), (200, {"cleared": True}))
        self.assertEqual(cleared, ["activity", "outbound"])


if __name__ == "__main__":
    unittest.main()
