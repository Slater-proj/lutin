"""ADR 0020, stage 1: ExLlamaV3, LM Studio and Colibri are engines of their own, the old setting (`moteur: openai` + `serveur`) is read as the engine it names
without being rewritten, and `GET /api/v1/engines` gives one card per program, each with the same fields and whether it can run on this machine.

Nothing is installed or started: the engines' own questions (state, models, actions) are replaced where a real server could answer."""
import json
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import agent, engines, hardware, storage  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402

A = V.A
CARDS = ["ollama", "llamacpp", "exllamav3", "lmstudio", "colibri", "openai"]
STOPPED = {"installe": False, "actif": False, "version": "", "detail": ""}


def setUpModule():
    V.setUpModule()


class Profile:
    def __init__(self, *makers):
        self.gpus = [hardware.Gpu(nom="card", vram_go=24.0, fabricant=maker, source="test") for maker in makers]


def quiet(test, identifiers=CARDS):
    """The engines answer at once, as stopped: no probe reaches a real Ollama, TabbyAPI or LM Studio of this machine."""
    for identifier in identifiers:
        engine = engines.ENGINES[identifier]
        for name, value in (("statut", dict(STOPPED)), ("modeles", {"actif": False, "installes": [], "tailles": {}}), ("actif", False)):
            patch = mock.patch.object(engine, name, return_value=value)
            patch.start()
            test.addCleanup(patch.stop)


class Files(unittest.TestCase):
    """Writes the two settings files as an older Lutin left them, and puts back what was there."""

    def setUp(self):
        self.settings, self.engines = A.DONNEES / "reglages.json", A.DONNEES / "moteurs.json"
        kept = {f: (f.read_bytes() if f.is_file() else None) for f in (self.settings, self.engines)}
        self.addCleanup(lambda: [f.write_bytes(b) if b is not None else f.unlink(missing_ok=True) for f, b in kept.items()])
        quiet(self)

    def write(self, settings, servers):
        self.settings.write_text(json.dumps(settings), encoding="utf-8")
        self.engines.write_text(json.dumps(servers), encoding="utf-8")

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8")), json.loads(self.engines.read_text(encoding="utf-8"))


class OldSetting(Files):
    OLD = {"openai": {"serveur": "exllamav3", "port_exllamav3": 5123, "dossier_modeles": "", "url": "http://192.0.2.1:8080/v1"}}

    def setUp(self):
        super().setUp()
        self.write({"moteur": "openai", "modele": "qwen3-8b-exl3"}, self.OLD)

    def test_an_old_openai_and_server_setting_opens_on_that_engine(self):
        before = (self.settings.read_bytes(), self.engines.read_bytes())
        self.assertEqual(A.reglages()["moteur"], "exllamav3")
        self.assertEqual(agent.moteur_actuel().id, "exllamav3")
        self.assertEqual(engines.ENGINES["exllamav3"].adresse(), "http://127.0.0.1:5123/v1")          # its port, kept in the old section of « openai »
        self.assertEqual(V.call("GET", "/api/v1/engines", V.OWNER)[1]["current"], "exllamav3")
        self.assertEqual((self.settings.read_bytes(), self.engines.read_bytes()), before, "reading must not migrate anything")

    def test_saving_another_setting_keeps_the_old_engine_as_it_was_written(self):
        storage.enregistrer_reglages({"num_ctx": 8192})
        settings, servers = self.read()
        self.assertEqual((settings["moteur"], settings["num_ctx"]), ("openai", 8192))
        self.assertEqual(servers, self.OLD)
        self.assertEqual(A.reglages()["moteur"], "exllamav3")

    def test_choosing_the_address_engine_forgets_the_old_server_and_stops_it(self):
        with mock.patch.object(engines.ENGINES["exllamav3"], "arreter_gere", return_value=True) as stop:
            storage.enregistrer_reglages({"moteur": "openai"})
        stop.assert_called_once_with()          # one OpenAI-compatible server at a time, as the old select did
        settings, servers = self.read()
        self.assertEqual(settings["moteur"], "openai")
        self.assertNotIn("serveur", servers["openai"])
        self.assertEqual(servers["openai"]["url"], "http://192.0.2.1:8080/v1")
        self.assertEqual(A.reglages()["moteur"], "openai")

    def test_choosing_the_engine_by_its_new_name_writes_it(self):
        storage.enregistrer_reglages({"moteur": "lmstudio"})
        self.assertEqual(self.read()[0]["moteur"], "lmstudio")
        self.assertEqual(agent.moteur_actuel().id, "lmstudio")

    def test_a_managed_server_keeps_its_old_settings_when_one_of_them_changes(self):
        status, answer = V.call("PATCH", "/api/v1/engines/exllamav3/settings", V.OWNER, body={"exllamav3_port": 5200})
        self.assertEqual((status, answer["exllamav3"]["port"]), (200, 5200), answer)
        servers = self.read()[1]
        self.assertEqual(servers["exllamav3"], {"port_exllamav3": 5200, "dossier_modeles": ""})
        self.assertEqual(servers["openai"], self.OLD["openai"])          # the old section is not touched
        self.assertEqual(engines.ENGINES["exllamav3"].adresse(), "http://127.0.0.1:5200/v1")

    def test_the_address_engine_is_no_longer_a_managed_server(self):
        engine = engines.ENGINES["openai"]
        self.assertEqual(engine.adresse(), "http://192.0.2.1:8080/v1")
        self.assertFalse(any(action["possible"] for action in engine.actions().values()))
        self.assertFalse(engine.exllamav3_choisi())

    def test_a_managed_engine_has_no_server_to_choose(self):
        with self.assertRaises(ml.ErreurMoteur):
            ml.apply_settings(engines.ENGINES["colibri"], {"serveur": "lmstudio"})


class Cards(Files):
    def setUp(self):
        super().setUp()
        self.write({"moteur": "ollama", "modele": "m"}, {})

    def cards(self):
        status, answer = V.call("GET", "/api/v1/engines", V.OWNER)
        self.assertEqual(status, 200)
        return {card["id"]: card for card in answer["engines"]}

    def test_one_card_per_program_in_order(self):
        status, answer = V.call("GET", "/api/v1/engines", V.OWNER)
        self.assertEqual([card["id"] for card in answer["engines"]], CARDS)
        names = {card["id"]: card["name"] for card in answer["engines"]}
        self.assertEqual((names["exllamav3"], names["lmstudio"], names["colibri"]), ("ExLlamaV3", "LM Studio", "Colibri"))

    def test_every_card_has_the_same_fields_and_the_same_buttons(self):
        cards = self.cards()
        self.assertEqual({tuple(sorted(card)) for card in cards.values()}, {tuple(sorted(cards["ollama"]))})
        self.assertEqual({tuple(sorted(card["actions"])) for card in cards.values()}, {("install", "reinstall", "start", "stop", "uninstall", "update")})
        self.assertEqual({tuple(sorted(card["runs_here"])) for card in cards.values()}, {("possible", "reason")})
        for identifier in ("exllamav3", "lmstudio", "colibri"):
            self.assertTrue(cards[identifier]["actions"]["install"]["reason"], identifier)          # what Install does, or why it cannot

    def test_a_card_that_cannot_run_here_says_why(self):
        with mock.patch.dict(engines.CONTEXT, profil=lambda: Profile("amd")):
            cards = self.cards()
        self.assertFalse(cards["exllamav3"]["runs_here"]["possible"])
        self.assertIn("NVIDIA", cards["exllamav3"]["runs_here"]["reason"])
        for identifier in ("ollama", "llamacpp", "lmstudio", "openai"):
            self.assertEqual(cards[identifier]["runs_here"], {"possible": True, "reason": ""}, identifier)

    def test_a_machine_not_measured_yet_excludes_nothing_for_its_cards(self):
        with mock.patch.dict(engines.CONTEXT, profil=lambda: None):
            self.assertEqual(engines.ENGINES["exllamav3"].compatibilite()[0], True)
        with mock.patch.dict(engines.CONTEXT, profil=lambda: Profile("nvidia")):
            self.assertEqual(engines.ENGINES["exllamav3"].compatibilite()[0], True)

    def test_docker_says_why_a_server_cannot_run_there(self):
        with mock.patch.dict(engines.CONTEXT, profil=lambda: Profile("nvidia"), en_docker=lambda: True):
            possible, reason = engines.ENGINES["exllamav3"].compatibilite()
        self.assertFalse(possible)
        self.assertIn("Docker", reason)

    def test_each_managed_card_describes_its_own_program(self):
        cards = self.cards()
        for identifier, name in (("exllamav3", "ExLlamaV3"), ("lmstudio", "LM Studio"), ("colibri", "Colibri")):
            self.assertIn(name, cards[identifier]["description"], identifier)
        grid = dict((row["fonction"], row) for row in engines.ENGINES["lmstudio"].vue()["grille"])
        self.assertNotEqual(grid["installation"]["etat"], "non")          # Lutin installs LM Studio: its own card must not say otherwise


if __name__ == "__main__":
    unittest.main()
