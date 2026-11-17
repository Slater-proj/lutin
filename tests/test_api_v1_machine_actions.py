"""The actions on a paired machine in `/api/v1` (ADR 0016, stage 2), on a real server with the fake engine of tests/test_moteur.py.

The server pairs with itself (as tests/test_machines.py does): it is both this machine and the paired one, so the other side of each action is the
real node code. What is fixed here: the English fields of each answer, a distinct status for each kind of refusal (404 unknown machine, 409 the other
machine said no, 503 it does not answer, 400 a wrong value), and that a refusal comes before any effect. Nothing reaches the computer: the Wake-on-LAN
packet, the shutdown and the update are replaced."""
import unittest
from unittest import mock

import test_api_v1_machines as M  # its callers, the fake engine of tests/test_moteur.py and the fields of a machine (imported as a module: its tests do not run here)

from lutin import access, machines, power  # noqa: E402

T, A, api = M.T, M.A, M.api
UNKNOWN = "0" * 32


class MachineActions(unittest.TestCase):
    def setUp(self):
        A.LIMITEUR_PIN.evenements.clear()          # every pairing counts against the limit of the node, which is this server
        machines.CODES.clear()
        machines.SONDES.clear()
        machines.DERNIER_ETAT.clear()
        machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
        machines.noeud_activer(True)
        self.answering = A.reglages().get("machine", "")

        def restore():
            machines._ecrire_registre([])
            for allow in (machines.noeud_autoriser_extinction, machines.noeud_autoriser_maj):
                allow(False)
            for share in machines.DROITS:
                machines.noeud_droit(share, False)
            for waiting in machines.noeud_vue()["demandes"]:
                machines.noeud_repondre_demande(waiting["machine"], waiting["droit"], False)
            machines.noeud_activer(False)
            for kept in (machines.CODES, machines.SONDES, machines.DERNIER_ETAT, machines.REVEIL, machines.ARRET, machines.MAJ_DISTANTE):
                kept.clear()
            machines._sauver_reveils()
            machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
            A.enregistrer_reglages({"machine": self.answering})
        self.addCleanup(restore)

    def pair(self, name="Bureau"):
        status, answer = api("POST", "/api/v1/machines", {"address": T.BASE, "code": machines.noeud_nouveau_code()["code"], "name": name})
        self.assertEqual(status, 201, answer)
        return answer

    def test_pairing_with_the_code_then_unpairing(self):
        paired = self.pair()
        self.assertEqual((sorted(paired), paired["name"], paired["address"]), (M.MACHINE_FIELDS, "Bureau", T.BASE))
        self.assertEqual([m["id"] for m in machines.lire()], [paired["id"]])
        A.enregistrer_reglages({"machine": paired["id"]})
        status, answer = api("DELETE", "/api/v1/machines/" + paired["id"])
        self.assertEqual((status, answer["machines"], answer["answering"]), (200, [], ""), "the machine that answered is gone: this one answers again")
        self.assertEqual(A.reglages().get("machine"), "")
        self.assertEqual(api("DELETE", "/api/v1/machines/" + paired["id"])[1]["error"]["code"], "not_found")

    def test_a_refused_pairing_adds_nothing_and_keeps_the_code(self):
        code = machines.noeud_nouveau_code()["code"]          # shown as « 1234-5678 »: the node keeps the digits
        digits = int("".join(c for c in code if c.isdigit()))
        wrong = "{:08d}".format((digits + 1) % 10 ** 8)
        refusals = [({"address": T.BASE}, 400, "invalid_request"), ({"address": T.BASE, "code": digits}, 400, "invalid_request"),
                    ({"address": T.BASE, "code": code, "token": "x"}, 400, "invalid_request"),
                    ({"address": "ftp://poste", "code": code}, 400, "invalid_request"),
                    ({"address": T.BASE, "code": code, "mac": "zz"}, 400, "invalid_request"),
                    ({"address": T.BASE, "code": wrong}, 409, "machine_refused"),
                    ({"address": "http://127.0.0.1:9", "code": code}, 503, "machine_unreachable")]
        for body, status, error in refusals:
            answer = api("POST", "/api/v1/machines", body)
            self.assertEqual((answer[0], answer[1]["error"]["code"]), (status, error), body)
            self.assertTrue(answer[1]["error"]["message"])
            self.assertEqual(machines.lire(), [], body)
        status, answer = api("POST", "/api/v1/machines", {"address": T.BASE, "code": code})
        self.assertEqual(status, 201, "the refusals came before the code was spent: {}".format(answer))

    def test_the_mac_address(self):
        paired = self.pair()
        status, answer = api("PATCH", "/api/v1/machines/" + paired["id"], {"mac": "00:1A:2B:3C:4D:5E"})
        self.assertEqual((status, answer["id"], answer["mac"], sorted(answer)), (200, paired["id"], "00:1A:2B:3C:4D:5E", M.MACHINE_FIELDS))
        for body in ({"mac": "zz"}, {"mac": 1}, {}, {"mac": "", "name": "x"}):
            self.assertEqual(api("PATCH", "/api/v1/machines/" + paired["id"], body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(machines.trouver(paired["id"])["mac"], "00:1A:2B:3C:4D:5E", "a refused value changes nothing")
        self.assertEqual(api("PATCH", "/api/v1/machines/" + UNKNOWN, {"mac": ""})[1]["error"]["code"], "not_found")

    def test_waking_sends_the_packet_and_needs_the_mac_address(self):
        paired = self.pair()
        sent = []
        with mock.patch.object(power, "send_wake", lambda mac, host: sent.append((mac, host)) or [(host, 9)]):
            api("PATCH", "/api/v1/machines/" + paired["id"], {"mac": ""})
            status, answer = api("POST", "/api/v1/machines/{}/actions/wake".format(paired["id"]))
            self.assertEqual((status, answer["error"]["code"], sent), (400, "invalid_request", []), "no MAC address: nothing is sent")
            self.assertIn("MAC", answer["error"]["message"])
            api("PATCH", "/api/v1/machines/" + paired["id"], {"mac": "00:1A:2B:3C:4D:5E"})
            status, answer = api("POST", "/api/v1/machines/{}/actions/wake".format(paired["id"]))
        self.assertEqual((status, sorted(answer), answer["mac"], answer["sent"]), (202, ["interfaces", "mac", "sent", "warnings"], "00:1A:2B:3C:4D:5E", 1))
        self.assertEqual(sent, [("00:1A:2B:3C:4D:5E", "127.0.0.1")])
        self.assertIsInstance(answer["interfaces"], list)
        self.assertIsInstance(answer["warnings"], list)

    def test_shutdown_needs_the_right_the_machine_grants(self):
        paired = self.pair()
        path = "/api/v1/machines/{}/actions/".format(paired["id"])
        asked = []
        with mock.patch.object(power, "schedule_shutdown", lambda *a, **k: asked.append("shutdown") or 30), \
                mock.patch.object(power, "cancel_shutdown", lambda *a, **k: asked.append("cancel") or True):
            status, answer = api("POST", path + "shutdown")
            self.assertEqual((status, answer["error"]["code"], asked), (409, "machine_refused", []), "not allowed by default")
            machines.noeud_autoriser_extinction(True)
            self.assertEqual(api("POST", path + "shutdown"), (202, {"shutdown_in_s": 30}))
            self.assertEqual(api("POST", path + "cancel-shutdown"), (200, {"cancelled": True}))
        self.assertEqual(asked, ["shutdown", "cancel"])

    def test_update_needs_the_right_the_machine_grants(self):
        paired = self.pair()
        asked = []
        with mock.patch.object(access, "update", lambda *a, **k: asked.append("update") or {"started": True}):
            status, answer = api("POST", "/api/v1/machines/{}/actions/update".format(paired["id"]))
            self.assertEqual((status, answer["error"]["code"], asked), (409, "machine_refused", []))
            machines.noeud_autoriser_maj(True)
            self.assertEqual(api("POST", "/api/v1/machines/{}/actions/update".format(paired["id"])), (202, {}))
        self.assertEqual(asked, ["update"])

    def test_an_action_is_checked_before_anything(self):
        paired = self.pair()
        self.assertEqual(api("POST", "/api/v1/machines/{}/actions/reboot".format(paired["id"]))[1]["error"]["code"], "invalid_request")
        self.assertEqual(api("POST", "/api/v1/machines/{}/actions/wake".format(paired["id"]), {"confirm": True})[1]["error"]["code"], "invalid_request")
        for action in ("wake", "shutdown", "cancel-shutdown", "update"):
            self.assertEqual(api("POST", "/api/v1/machines/{}/actions/{}".format(UNKNOWN, action))[0], 404, action)

    def test_a_machine_that_does_not_answer_says_so(self):
        paired = self.pair()
        machines._ecrire_registre([dict(machines.lire()[0], adresse="http://127.0.0.1:9")])
        for path, body in (("actions/shutdown", None), ("actions/update", None), ("rights-requests", {"right": "lead"}), ("imports/skills", None)):
            status, answer = api("POST", "/api/v1/machines/{}/{}".format(paired["id"], path), body)
            self.assertEqual((status, answer["error"]["code"]), (503, "machine_unreachable"), path)

    def test_a_right_is_asked_and_the_owner_answers_on_the_machine(self):
        paired = self.pair()
        path = "/api/v1/machines/{}/rights-requests".format(paired["id"])
        self.assertEqual(api("POST", path, {"right": "lead"}), (202, {"right": "lead"}))
        self.assertEqual([waiting["droit"] for waiting in machines.noeud_vue()["demandes"]], ["piloter"], "waiting on the node, nothing granted")
        self.assertFalse(machines.noeud_vue()["piloter"])
        for body in ({"right": "admin"}, {"right": ["lead"]}, {}, {"right": "lead", "why": "x"}):
            self.assertEqual(api("POST", path, body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(api("POST", "/api/v1/machines/{}/rights-requests".format(UNKNOWN), {"right": "lead"})[1]["error"]["code"], "not_found")

    def test_imports_need_the_share_then_give_the_counts(self):
        paired = self.pair()
        path = "/api/v1/machines/{}/imports/".format(paired["id"])
        for kind, share, fields in (("skills", "skills", ["added", "already_there", "updated"]),
                                    ("memory", "memoire", ["notes_added", "notes_skipped", "profile_copied", "profile_truncated"])):
            status, answer = api("POST", path + kind)
            self.assertEqual((status, answer["error"]["code"]), (409, "machine_refused"), kind)
            machines.noeud_droit(share, True)
            status, answer = api("POST", path + kind)
            self.assertEqual((status, sorted(answer)), (200, fields), answer)
        self.assertEqual(api("POST", path + "conversations")[1]["error"]["code"], "invalid_request")
        self.assertEqual(api("POST", path + "skills", {"all": True})[1]["error"]["code"], "invalid_request")
        self.assertEqual(api("POST", "/api/v1/machines/{}/imports/skills".format(UNKNOWN))[1]["error"]["code"], "not_found")

    def test_the_old_route_still_answers_400(self):
        paired = self.pair()
        status, answer = M.U.api("POST", "/api/machines-shutdown", {"id": paired["id"]})
        self.assertEqual(status, 400)
        self.assertIn("Autoriser les machines appairées", answer["erreur"])


if __name__ == "__main__":
    unittest.main()
