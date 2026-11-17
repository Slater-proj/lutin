"""`/api/v1/machines` and the remote models (ADR 0016, stage 1), on a real server with the fake engine of tests/test_moteur.py.

The server pairs with itself (as tests/test_machines.py does): it is both this machine and the paired one. What is fixed here: the fields of a paired
machine under their English names, that the list never waits for the network, that a token never leaves, the remote models of `GET /models`, and the
`machine` field of a turn."""
import json
import time
import unittest

import test_api_v1_turns as U  # its callers and, through it, the fake engine of tests/test_moteur.py (imported as modules: their tests do not run here)

from lutin import machines  # noqa: E402

T, A, api = U.T, U.A, U.api
MACHINE_FIELDS = ["added", "address", "allowed", "detail", "id", "load", "mac", "mac_auto", "models", "name", "requested", "shares", "shutdown_in_s",
                  "state", "step", "update_available", "version", "wake_failed", "warnings"]


def until(check, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    return check()


class PairedMachines(unittest.TestCase):
    def setUp(self):
        machines.SONDES.clear()
        machines.DERNIER_ETAT.clear()
        machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
        machines.noeud_activer(True)
        self.paired = machines.ajouter(T.BASE, machines.noeud_nouveau_code()["code"], "Bureau")

        def restore():
            machines._ecrire_registre([])
            machines.noeud_activer(False)
            machines.SONDES.clear()
            machines.DERNIER_ETAT.clear()
            machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
        self.addCleanup(restore)

    def test_the_list_answers_at_once_then_with_the_probe(self):
        status, answer = api("GET", "/api/v1/machines")
        self.assertEqual((status, sorted(answer)), (200, ["answering", "enabled", "log", "machines"]))
        self.assertEqual((answer["enabled"], answer["answering"]), (True, ""), "a paired machine turns the multi-machine mode on")
        first = answer["machines"][0]
        self.assertEqual((sorted(first), first["id"], first["name"], first["address"]), (MACHINE_FIELDS, self.paired["id"], "Bureau", self.paired["adresse"]))
        self.assertIn(first["state"], ("unknown", "operational"), "never probed yet: the list did not wait for it")
        probed = until(lambda: next((m for m in api("GET", "/api/v1/machines")[1]["machines"] if m["state"] != "unknown"), None))
        self.assertEqual(probed["state"], "operational", probed["detail"])
        self.assertIsNone(probed["shutdown_in_s"], "a countdown only while the machine shuts down ({})".format(probed["step"]))
        self.assertEqual(sorted(probed["allowed"]), ["lead", "shutdown", "update"])
        self.assertEqual(sorted(probed["shares"]), ["memory", "skills"])
        self.assertIsInstance(probed["models"], list)

    def test_a_machine_that_does_not_answer_does_not_hold_the_list(self):
        stored = machines.lire()
        machines._ecrire_registre([dict(stored[0], adresse="http://10.255.255.1:9")])          # an address nothing answers: a probe would wait seconds
        begin = time.monotonic()
        status, answer = api("GET", "/api/v1/machines")
        self.assertLess(time.monotonic() - begin, 1.0, "the list does not wait for the network")
        self.assertEqual((status, answer["machines"][0]["state"]), (200, "unknown"))

    def test_no_token_ever_leaves(self):
        stored = json.dumps(machines.lire())
        token = machines.lire()[0].get("jeton", "")
        self.assertTrue(token and token in stored)
        until(lambda: api("GET", "/api/v1/machines")[1]["machines"][0]["state"] != "unknown")
        self.assertNotIn(token, json.dumps(api("GET", "/api/v1/machines")[1]))
        self.assertNotIn(token, json.dumps(api("GET", "/api/v1/models")[1]))

    def test_the_models_of_a_paired_machine_are_offered(self):
        remote = until(lambda: api("GET", "/api/v1/models")[1]["remote"])
        self.assertEqual(len(remote), 1, remote)
        self.assertEqual((sorted(remote[0]), remote[0]["machine"], remote[0]["machine_name"], remote[0]["state"]),
                         (["machine", "machine_name", "models", "state"], self.paired["id"], "Bureau", "operational"))

    def test_without_the_multi_machine_mode_no_remote_model(self):
        before = A.reglages().get("cluster")
        A.enregistrer_reglages({"cluster": False})
        self.addCleanup(lambda: A.enregistrer_reglages({"cluster": before}))
        self.assertEqual(api("GET", "/api/v1/models")[1]["remote"], [])
        self.assertFalse(api("GET", "/api/v1/machines")[1]["enabled"])

    def test_a_turn_accepts_a_machine_and_an_unknown_one_answers_here(self):
        conversation = U.new_conversation()
        status, _, events = U.turn(conversation, {"message": "Hello", "machine": "0" * 32}, [[{"content": "From here."}]])
        self.assertEqual(status, 200, events)
        self.assertEqual("".join(event["text"] for event in U.of_type(events, "text")), "From here.")


if __name__ == "__main__":
    unittest.main()
