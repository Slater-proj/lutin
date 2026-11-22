"""Engine capabilities (plan step 5, item 7): each engine declares what the agent loop must know to drive it, in agreement with the grid shown on the page,
and the loop reads that record instead of asking « is it Ollama? »."""
import os
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-engine-capabilities-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir()

from lutin import core as _core  # noqa: E402  (core first: agent is one of its parts)
from lutin import agent, engine_capabilities, engines  # noqa: E402
from lutin.engine_capabilities import EngineCapabilities  # noqa: E402

GRID_TO_TOOLS = {"natif": engine_capabilities.NATIVE, "adapte": engine_capabilities.TEMPLATE, "non": engine_capabilities.NO, "non_teste": engine_capabilities.UNKNOWN}
GRID_TO_YES_NO = {"natif": engine_capabilities.YES, "adapte": engine_capabilities.YES, "non": engine_capabilities.NO, "non_teste": engine_capabilities.UNKNOWN}


class Record(unittest.TestCase):
    def test_an_engine_of_which_nothing_is_known_gets_the_cautious_answers(self):
        self.assertEqual(engine_capabilities.CAUTIOUS.as_dict(), {"tools": "unknown", "grammar": "unknown", "slots": "unknown", "prompt_cache": "unknown", "embeddings": "unknown",
                                                                  "token_counts": "unknown", "starts_on_demand": False, "spills_to_cpu": False,
                                                                  "experts_in_ram": False})
        self.assertIs(engine_capabilities.of(object()), engine_capabilities.CAUTIOUS)
        self.assertIs(engine_capabilities.of(engines.Engine()), engine_capabilities.CAUTIOUS)

        class Wrong:
            def aptitudes(self):
                return {"starts_on_demand": True}
        self.assertIs(engine_capabilities.of(Wrong()), engine_capabilities.CAUTIOUS, "a declaration that is not a record is not believed")

    def test_a_record_only_takes_the_words_it_knows(self):
        for wrong in ({"tools": "yes"}, {"grammar": "native"}, {"prompt_cache": "yes"}, {"slots": True}, {"starts_on_demand": "yes"}, {"spills_to_cpu": 1}):
            with self.assertRaises(ValueError, msg=wrong):
                EngineCapabilities(**wrong)
        with self.assertRaises(AttributeError):
            engine_capabilities.CAUTIOUS.tools = "native"          # a record is a fact, not a setting


class Engines(unittest.TestCase):
    def test_every_engine_declares_a_record_that_agrees_with_its_grid(self):
        self.assertGreaterEqual(set(engines.ENGINES), {engines.OLLAMA, engines.LLAMACPP, engines.OPENAI})
        for identifier, engine in engines.ENGINES.items():
            record, grid = engine.aptitudes(), engine.grille()
            self.assertIsInstance(record, EngineCapabilities, identifier)
            self.assertEqual(record.tools, GRID_TO_TOOLS[grid["outils"][0]], identifier + ": tools")
            self.assertEqual(record.embeddings, GRID_TO_YES_NO[grid["embeddings"][0]], identifier + ": embeddings")

    def test_what_each_engine_says(self):
        ollama, llamacpp, other = (engines.ENGINES[identifier].aptitudes() for identifier in (engines.OLLAMA, engines.LLAMACPP, engines.OPENAI))
        self.assertEqual((ollama.tools, ollama.prompt_cache, ollama.slots, ollama.starts_on_demand, ollama.spills_to_cpu), ("native", "automatic", "no", True, True))
        self.assertEqual((llamacpp.tools, llamacpp.grammar, llamacpp.slots, llamacpp.prompt_cache, llamacpp.starts_on_demand, llamacpp.spills_to_cpu), ("template", "yes", "yes", "on_request", False, False))
        self.assertEqual(other, engine_capabilities.CAUTIOUS, "a server Lutin only connects to: nothing is assumed")

    def test_the_experts_of_a_big_model_wait_in_memory_only_on_an_engine_that_can(self):
        """A mixture-of-experts model larger than the card is offered only where its experts can wait in memory (docs/modernization/LARGE_MODELS.md)."""
        from lutin import llamacpp_engine
        self.assertTrue(engines.ENGINES[engines.OLLAMA].aptitudes().experts_in_ram)
        self.assertFalse(engines.ENGINES[engines.OPENAI].aptitudes().experts_in_ram, "a server Lutin only connects to: nothing is assumed")
        llamacpp = engines.ENGINES[engines.LLAMACPP]
        with mock.patch.object(llamacpp, "serveur_pret", lambda: None):
            self.assertTrue(llamacpp.aptitudes().experts_in_ram, "not installed yet: Lutin installs a recent version")
        for help_text, expected in (("--fit [on|off]", True), ("-ncmoe, --n-cpu-moe n", True), ("--threads n -ngl n", False)):
            with mock.patch.object(llamacpp, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(llamacpp_engine, "aide_serveur", lambda exe, h=help_text: h):
                self.assertIs(llamacpp.aptitudes().experts_in_ram, expected, help_text)

    def test_the_only_engine_the_loop_may_start_knows_how(self):
        for identifier, engine in engines.ENGINES.items():
            if not engine.aptitudes().starts_on_demand:
                with self.assertRaises(ValueError, msg=identifier):
                    engine.demarrer_sur_demande()
        with mock.patch.object(_core, "demarrer_ollama", return_value="started") as start:
            self.assertEqual(engines.ENGINES[engines.OLLAMA].demarrer_sur_demande(), "started")
        start.assert_called_once_with()


class Down(engines.Engine):
    """An engine that fails the way the test says. It calls itself Ollama on purpose: the loop must read its record, not its name."""
    id, nom = engines.OLLAMA, "Fake"

    def __init__(self, record, failure):
        self.record, self.failure, self.started, self.asked = record, failure, 0, 0

    def aptitudes(self):
        return self.record

    def chat_flux(self, corps, delai=900):
        self.asked += 1
        raise self.failure

    def demarrer_sur_demande(self):
        self.started += 1


class Loop(unittest.TestCase):
    """The model call alone (agent._appeler_modele), with an engine that does not answer."""

    def call(self, engine):
        events = []
        r = {"modele": "small", "num_ctx": 4096, "temperature": 0.2}
        body = {"model": "small", "messages": [{"role": "user", "content": "Hello"}], "stream": True, "options": {}, "think": False}
        with mock.patch.object(agent, "moteur_actuel", lambda r=None: engine), mock.patch.object(_core, "AUTO_DEMARRAGE", True):
            done, fallback, text, thought, calls = agent._appeler_modele({"id": "c-loop", "messages": []}, r, events.append, {}, threading.Event(), body, body["messages"], [], None, False)
        self.assertEqual((done, fallback, text, calls), (False, False, "", []), "an engine that never answers gives no answer")
        return [event["texte"] for event in events]

    def test_an_engine_that_starts_on_demand_is_started_once_then_asked_again(self):
        engine = Down(EngineCapabilities(starts_on_demand=True), urllib.error.URLError("connection refused"))
        said = self.call(engine)
        self.assertEqual((engine.started, engine.asked), (1, 2), "started once for this request, and asked again")
        self.assertIn("Ollama ne répond pas : je le démarre (quelques secondes)...", said)

    def test_an_engine_that_does_not_is_never_started_whatever_its_name(self):
        engine = Down(engine_capabilities.CAUTIOUS, urllib.error.URLError("connection refused"))
        said = self.call(engine)
        self.assertEqual((engine.started, engine.asked), (0, 1))
        self.assertFalse([line for line in said if "je le démarre" in line])

    def test_an_engine_that_cannot_spill_to_the_processor_says_the_model_does_not_fit(self):
        engine = Down(engine_capabilities.CAUTIOUS, RuntimeError("failed to load model: insufficient VRAM"))
        said = self.call(engine)
        self.assertEqual(engine.asked, 1, "asking again would fail the same way")
        self.assertTrue([line for line in said if "la mémoire de la carte graphique ne suffit pas" in line], said)

    def test_an_engine_that_spills_is_not_told_so(self):
        engine = Down(EngineCapabilities(spills_to_cpu=True), RuntimeError("failed to load model: insufficient VRAM"))
        said = self.call(engine)
        self.assertFalse([line for line in said if "la mémoire de la carte graphique ne suffit pas" in line], said)


if __name__ == "__main__":
    unittest.main()
