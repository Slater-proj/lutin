"""This machine as a node in `/api/v1` (ADR 0016, stage 3), on the real server of tests/test_api_v1.py (level « network »).

What is fixed here: the English fields of `GET /node`, the right of each route as the old Machines tab had it (lending, the pairing code and
revoking for whoever may configure; what this machine grants, the answer to a rights request and cancelling a shutdown from this machine only), a
distinct status for each refusal, and that a refusal comes before any effect. Nothing reaches the computer: autostart and the shutdown are replaced."""
import unittest
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import machines, power  # noqa: E402
from lutin import security as S  # noqa: E402
import quiet_node  # noqa: E402  (what a node reads of this computer, replaced)

A = V.A
NODE_FIELDS = ["allow", "authorized", "id", "lending", "pending_shutdown", "requests", "shares", "startup"]
STARTUP = {"installe": False, "possible": True, "limites": "Lutin starts when the session opens."}


def setUpModule():
    V.setUpModule()


def call(method, path, body=None, who=None):
    return V.call(method, path, V.OWNER if who is None else who, body)


def node():
    status, answer = call("GET", "/api/v1/node")
    assert status == 200, answer
    return answer


class Node(unittest.TestCase):
    def setUp(self):
        quiet_node.quiet(self)
        for patch in (mock.patch.object(power, "startup_state_memo", lambda: dict(STARTUP)),          # the real one reads the registry of this computer
                      mock.patch.object(power, "install_startup", self.fail_on_call("install_startup")),
                      mock.patch.object(power, "remove_startup", self.fail_on_call("remove_startup"))):
            patch.start()
            self.addCleanup(patch.stop)
        machines.CODES.clear()

        def restore():
            for allow in (machines.noeud_autoriser_extinction, machines.noeud_autoriser_maj, machines.noeud_autoriser_piloter):
                allow(False)
            for share in machines.DROITS:
                machines.noeud_droit(share, False)
            for waiting in machines.noeud_vue()["demandes"]:
                machines.noeud_repondre_demande(waiting["machine"], waiting["droit"], False)
            for allowed in machines.noeud_vue()["autorisees"]:
                machines.noeud_revoquer(allowed["nom"])
            machines.noeud_activer(False)
            machines.CODES.clear()
        self.addCleanup(restore)

    def fail_on_call(self, name):
        def called(*args, **kwargs):
            raise AssertionError("{} reached the computer".format(name))
        return called

    def authorize(self, name):
        """What `POST /machines` does on the other machine: it trades the code shown here for a token."""
        status, answer = call("POST", "/api/v1/node/pairing-code")
        self.assertEqual(status, 201, answer)
        return machines.noeud_echanger(answer["code"], name)["jeton"]

    def test_the_node_under_its_english_names(self):
        answer = node()
        self.assertEqual(sorted(answer), NODE_FIELDS)
        self.assertEqual((answer["lending"], answer["id"]), (False, machines.noeud()["id"]))
        self.assertEqual(answer["shares"], {"skills": False, "memory": False})
        self.assertEqual(answer["allow"], {"lead": False, "update": False, "shutdown": False}, "nothing is granted by default")
        self.assertEqual((answer["pending_shutdown"], answer["requests"], answer["authorized"]), (None, [], []))
        self.assertEqual(answer["startup"], {"installed": False, "possible": True, "limits": STARTUP["limites"]})
        self.assertEqual(call("GET", "/api/v1/node", who=V.DEVICE)[0], 200, "a paired phone reads it, as the old Machines tab")
        self.assertNotIn("jeton", repr(answer))

    def test_lending_is_turned_on_and_off(self):
        self.assertEqual(call("PATCH", "/api/v1/node", {"lending": True}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        for body in ({}, {"lending": 1}, {"lending": "yes"}, {"lending": True, "id": "x"}):
            self.assertEqual(call("PATCH", "/api/v1/node", body)[1]["error"]["code"], "invalid_request", body)
        self.assertFalse(machines.noeud_actif(), "a refused value changes nothing")
        status, answer = call("PATCH", "/api/v1/node", {"lending": True})
        self.assertEqual((status, sorted(answer), answer["lending"]), (200, NODE_FIELDS, True))
        self.assertTrue(machines.noeud_actif())
        self.assertEqual(call("PATCH", "/api/v1/node", {"lending": False})[1]["lending"], False)

    def test_at_the_level_local_lending_is_refused(self):
        with mock.patch.object(A, "SECURITY", S.Security(niveau=S.LOCAL)):
            status, answer = call("PATCH", "/api/v1/node", {"lending": True})
            self.assertEqual((status, answer["error"]["code"]), (409, "local_only"))
            self.assertIn("réseau", answer["error"]["message"])
            self.assertFalse(machines.noeud_actif())
            self.assertEqual(call("PATCH", "/api/v1/node", {"lending": False})[0], 200, "turning it off is always possible")
            status, answer = V.call("POST", "/api/machines-noeud-activer", V.OWNER, {"actif": True})
            self.assertEqual(status, 400, "the old route answers as before")

    def test_the_pairing_code_needs_lending(self):
        status, answer = call("POST", "/api/v1/node/pairing-code")
        self.assertEqual((status, answer["error"]["code"], machines.CODES), (409, "not_lending", {}), "no code that could not be used")
        machines.noeud_activer(True)
        self.assertEqual(call("POST", "/api/v1/node/pairing-code", {"name": "x"})[1]["error"]["code"], "invalid_request")
        self.assertEqual(call("POST", "/api/v1/node/pairing-code", who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(machines.CODES, {})
        status, answer = call("POST", "/api/v1/node/pairing-code")
        self.assertEqual((status, sorted(answer), answer["valid_seconds"]), (201, ["code", "valid_seconds"], machines.DUREE_CODE_S))
        self.assertRegex(answer["code"], r"^\d{4}-\d{4}$")
        machines.noeud_echanger(answer["code"], "Bureau")
        self.assertEqual([allowed["name"] for allowed in node()["authorized"]], ["Bureau"])

    def test_revoking_an_authorized_machine(self):
        machines.noeud_activer(True)
        token = self.authorize("Poste du salon")
        self.assertEqual(machines.noeud_jeton_valide(token), "Poste du salon")
        self.assertEqual(call("DELETE", "/api/v1/node/authorized/Poste%20du%20salon", who=V.DEVICE)[1]["error"]["code"], "configurator")
        self.assertEqual(call("DELETE", "/api/v1/node/authorized/Inconnu")[1]["error"]["code"], "not_found")
        self.assertEqual(machines.noeud_jeton_valide(token), "Poste du salon", "refusals revoke nothing")
        status, answer = call("DELETE", "/api/v1/node/authorized/Poste%20du%20salon")
        self.assertEqual((status, answer["authorized"]), (200, []))
        self.assertIsNone(machines.noeud_jeton_valide(token), "the token stops working at once")

    def test_an_authorized_machine_is_renamed_to_say_who_it_is(self):
        """Seen by the maintainer: a paired machine is listed under the name its computer sent (« DESKTOP-K2J8S9 »): it can be given a clear one."""
        machines.noeud_activer(True)
        token = self.authorize("DESKTOP-K2J8S9")
        machines.noeud_demander("DESKTOP-K2J8S9", "maj")
        self.authorize("Salon")
        path = "/api/v1/node/authorized/DESKTOP-K2J8S9"
        self.assertEqual(call("PATCH", path, {"name": "PC du bureau"}, who=V.DEVICE)[1]["error"]["code"], "configurator")
        for body in ({}, {"name": ""}, {"name": "  "}, {"name": 1}, {"name": "x", "date": "y"}):
            self.assertEqual(call("PATCH", path, body)[1]["error"]["code"], "invalid_request", body)
        self.assertEqual(call("PATCH", path, {"name": "Salon"})[1]["error"]["code"], "conflict", "two machines never share a name")
        self.assertEqual(call("PATCH", "/api/v1/node/authorized/Inconnu", {"name": "X"})[1]["error"]["code"], "not_found")
        status, answer = call("PATCH", path, {"name": "PC du bureau <b>"})
        self.assertEqual(status, 200, answer)
        self.assertEqual(sorted(allowed["name"] for allowed in answer["authorized"]), ["PC du bureau b", "Salon"], "cleaned as at pairing")
        self.assertEqual(machines.noeud_jeton_valide(token), "PC du bureau b", "its token still opens, under the new name")
        self.assertEqual([request["machine"] for request in answer["requests"]], ["PC du bureau b"], "its waiting request follows it")

    def test_permissions_are_granted_from_this_machine_only(self):
        status, answer = call("PATCH", "/api/v1/node/permissions", {"shares": {"skills": True}, "allow": {"lead": True}})
        self.assertEqual((status, answer["shares"], answer["allow"]), (200, {"skills": True, "memory": False}, {"lead": True, "update": False, "shutdown": False}))
        self.assertTrue(machines.noeud_vue()["piloter"])
        self.assertTrue(machines.noeud_droits()["skills"])
        refused = ({}, {"shares": {}}, {"shares": {"conversations": True}}, {"shares": ["skills"]}, {"allow": {"lead": 1}}, {"autostart": "yes"},
                   {"autostart": None}, {"lending": True}, {"shares": {"memory": True}, "allow": {"admin": True}},
                   {"allow": {"update": True}, "autostart": 1})
        for body in refused:
            self.assertEqual(call("PATCH", "/api/v1/node/permissions", body)[1]["error"]["code"], "invalid_request", body)
        after = node()
        self.assertEqual((after["shares"]["memory"], after["allow"]["update"]), (False, False), "everything is checked before anything is written")

    def test_autostart_comes_first_and_a_refusal_writes_nothing(self):
        asked = []
        with mock.patch.object(power, "install_startup", lambda: asked.append("install")), mock.patch.object(power, "remove_startup", lambda: asked.append("remove")):
            self.assertEqual(call("PATCH", "/api/v1/node/permissions", {"autostart": True})[0], 200)
            self.assertEqual(call("PATCH", "/api/v1/node/permissions", {"autostart": False})[0], 200)
        self.assertEqual(asked, ["install", "remove"])

        def refuse():
            raise ValueError("Windows refused")
        with mock.patch.object(power, "install_startup", refuse):
            status, answer = call("PATCH", "/api/v1/node/permissions", {"autostart": True, "allow": {"shutdown": True}, "shares": {"memory": True}})
        self.assertEqual((status, answer["error"]["code"], answer["error"]["message"]), (400, "invalid_request", "Windows refused"))
        self.assertFalse(machines.noeud_vue()["extinction"], "the system said no: nothing else is written")
        self.assertFalse(machines.noeud_droits()["memoire"])

    def test_a_remote_administrator_configures_but_does_not_grant(self):
        """The level `local` is stricter than `configurator`: an administrator on another device lends and revokes, but what this machine grants,
        the answer to a request and a shutdown stay with the person in front of it."""
        machines.noeud_demander("Bureau", "piloter")
        with mock.patch.object(A.Handler, "_admin_tous", staticmethod(lambda: True)):
            self.assertEqual(call("PATCH", "/api/v1/node", {"lending": True}, who=V.DEVICE)[0], 200)
            self.assertEqual(call("POST", "/api/v1/node/pairing-code", who=V.DEVICE)[0], 201)
            for method, path, body in (("PATCH", "/api/v1/node/permissions", {"allow": {"lead": True}}),
                                       ("POST", "/api/v1/node/requests/Bureau/lead", {"accept": True}),
                                       ("POST", "/api/v1/node/shutdown/cancel", None)):
                status, answer = call(method, path, body, who=V.DEVICE)
                self.assertEqual((status, answer["error"]["code"]), (403, "local_only"), path)
        self.assertFalse(machines.noeud_vue()["piloter"])
        self.assertEqual(len(machines.noeud_vue()["demandes"]), 1)

    def test_a_rights_request_is_answered_here(self):
        machines.noeud_demander("Bureau", "piloter")
        machines.noeud_demander("Bureau", "maj")
        waiting = node()["requests"]
        self.assertEqual(sorted((request["machine"], request["right"]) for request in waiting), [("Bureau", "lead"), ("Bureau", "update")])
        self.assertTrue(all(sorted(request) == ["date", "machine", "right"] for request in waiting))
        for path, body in (("Bureau/admin", {"accept": True}), ("Bureau/lead", {}), ("Bureau/lead", {"accept": "yes"}), ("Bureau/lead", {"accept": True, "x": 1})):
            self.assertEqual(call("POST", "/api/v1/node/requests/" + path, body)[1]["error"]["code"], "invalid_request", path)
        self.assertEqual(call("POST", "/api/v1/node/requests/Ailleurs/lead", {"accept": True})[1]["error"]["code"], "not_found")
        self.assertEqual(call("POST", "/api/v1/node/requests/Bureau/shutdown", {"accept": True})[1]["error"]["code"], "not_found", "no such request")
        self.assertEqual(len(machines.noeud_vue()["demandes"]), 2, "refusals answer nothing")
        status, answer = call("POST", "/api/v1/node/requests/Bureau/lead", {"accept": True})
        self.assertEqual((status, answer["allow"]["lead"], [request["right"] for request in answer["requests"]]), (200, True, ["update"]))
        answer = call("POST", "/api/v1/node/requests/Bureau/update", {"accept": False})[1]
        self.assertEqual((answer["allow"]["update"], answer["requests"]), (False, []), "refused: forgotten, not granted")
        self.assertEqual(call("POST", "/api/v1/node/requests/Bureau/lead", {"accept": True})[1]["error"]["code"], "not_found", "answered once")

    def test_a_shutdown_asked_by_another_machine(self):
        self.assertEqual(call("POST", "/api/v1/node/shutdown/cancel"), (200, {"cancelled": False}), "nothing pending")
        self.assertEqual(call("POST", "/api/v1/node/shutdown/cancel", {"now": True})[1]["error"]["code"], "invalid_request")
        cancelled = []
        with mock.patch.object(power, "pending_shutdown", lambda: {"dans_s": 20, "par": "Bureau"}), \
                mock.patch.object(power, "cancel_shutdown", lambda journaliser: cancelled.append(True) or True):
            self.assertEqual(node()["pending_shutdown"], {"in_s": 20, "by": "Bureau"})
            self.assertEqual(call("POST", "/api/v1/node/shutdown/cancel"), (200, {"cancelled": True}))
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
