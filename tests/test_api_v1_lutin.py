"""`/api/v1/lutin/…` and the fields `new_version` and `restart` of `/status` (docs/modernization/PARITY.md, item 6): Lutin's own version, on the
real server of tests/test_api_v1.py (level « network »).

Hermetic: the version cache is a temporary file, GitHub is `updates.derniere_release_detail` replaced, the update is `cli.mise_a_jour_detaillee`
replaced, and the restart is a `threading.Timer` that is never started. Nothing reaches the network and Lutin never stops."""
import json
import time
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import access, cli, updates

A = V.A


def setUpModule():
    V.setUpModule()


class LutinVersion(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp(prefix="lutin-version-")) / "lutin-version.json"
        for patch in (mock.patch.dict(os.environ, {"LUTIN_VERSION_CACHE": str(self.cache)}),
                      mock.patch.object(access, "saved_security", lambda: A.SECURITY),          # the level saved is the one running: no restart waits
                      mock.patch.dict(access.RESTAURE, {"fait": False}),
                      mock.patch.dict(access.UPDATE, {"etat": "", "lignes": [], "avant": "", "apres": ""})):
            patch.start()
            self.addCleanup(patch.stop)

    def announce(self, version, **more):
        self.cache.write_text(json.dumps(dict({"date": 1, "version": version, "depot": "example/lutin"}, **more)), encoding="utf-8")

    def status(self):
        status, answer = V.call("GET", "/api/v1/status", V.OWNER)
        self.assertEqual(status, 200, answer)
        return answer

    def test_the_status_announces_a_newer_version_from_the_cache_only(self):
        self.assertIsNone(self.status()["new_version"], "no check made yet")
        self.announce(A.VERSION)
        self.assertIsNone(self.status()["new_version"], "the version running is not announced")
        self.announce("999.0.0")
        self.assertEqual(self.status()["new_version"], {"version": "999.0.0", "page": "https://github.com/example/lutin/releases/tag/v999.0.0",
                                                         "command": updates.update_command()})
        self.announce("999.0.0", ignoree="999.0.0")
        self.assertIsNone(self.status()["new_version"], "an ignored version is not announced again")

    def test_checking_now_asks_github_once(self):
        asked = []

        def github(*args, **kwargs):
            asked.append(args)
            return "999.0.0", "https://example.invalid/lutin.whl", ""
        with mock.patch.object(updates, "latest_release_detail", github):
            status, answer = V.call("POST", "/api/v1/lutin/check", V.OWNER, {})
        self.assertEqual(status, 200, answer)
        self.assertEqual(len(asked), 1)
        self.assertEqual((answer["current"], answer["latest"], answer["new_version"]["version"]), (A.VERSION, "999.0.0", "999.0.0"))
        self.assertEqual(self.status()["new_version"]["version"], "999.0.0", "kept in the cache for the banner")

    def test_checking_says_when_github_cannot_be_reached(self):
        with mock.patch.object(updates, "latest_release_detail", lambda *args, **kwargs: (None, None, "no route to host")):
            status, answer = V.call("POST", "/api/v1/lutin/check", V.OWNER, {})
        self.assertEqual((status, answer["error"]["code"]), (503, "unreachable"))
        self.assertIn("no route to host", answer["error"]["message"])

    def test_checking_needs_a_version_cache(self):
        with mock.patch.dict(os.environ):
            del os.environ["LUTIN_VERSION_CACHE"]
            status, answer = V.call("POST", "/api/v1/lutin/check", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "not_available"))
            self.assertFalse(V.call("GET", "/api/v1/lutin/update", V.OWNER)[1]["can_check"])

    def test_a_version_is_ignored(self):
        self.announce("999.0.0")
        status, answer = V.call("POST", "/api/v1/lutin/ignored-version", V.OWNER, {"version": "999.0.0"})
        self.assertEqual((status, answer), (200, {"new_version": None}))
        self.assertIsNone(self.status()["new_version"])
        self.announce("1000.0.0", ignoree="999.0.0")
        self.assertEqual(self.status()["new_version"]["version"], "1000.0.0", "the next one is announced")
        status, answer = V.call("POST", "/api/v1/lutin/ignored-version", V.OWNER, {"version": " "})
        self.assertEqual((status, answer["error"]["code"]), (400, "invalid_request"))

    def test_the_state_of_an_update_before_any(self):
        status, answer = V.call("GET", "/api/v1/lutin/update", V.DEVICE)
        self.assertEqual(status, 200, answer)
        self.assertEqual(sorted(answer), ["after", "before", "can_check", "can_restart", "can_update", "command", "lines", "state"])
        self.assertEqual((answer["state"], answer["lines"], answer["can_check"]), ("idle", [], True))

    def test_updating_needs_the_right_to_configure_and_the_network(self):
        started = []
        with mock.patch.object(cli, "detailed_update", lambda *args, **kwargs: started.append(1) or (0, "1.0", None)):
            self.assertEqual(V.call("POST", "/api/v1/lutin/update", V.DEVICE, {})[0], 403, "a paired phone does not update Lutin")
            status, answer = V.call("POST", "/api/v1/lutin/update", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "offline"), "the test server is in strict offline mode")
            with mock.patch.object(access, "in_docker", lambda: True):
                status, answer = V.call("POST", "/api/v1/lutin/update", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "in_docker"))
        self.assertEqual(started, [], "nothing was started")

    def run_update(self, outcome, can_restart=False):
        """Runs an update whose steps are replaced by `outcome` (code, before, after) and returns its last state."""
        def steps(say, error, capturer=False, revenir_a=None):
            say("Sauvegarde faite.")
            return outcome
        timers = []
        with mock.patch.object(cli, "detailed_update", steps), mock.patch.object(V.api_v1._offline, "is_active", lambda: False), \
                mock.patch.object(access, "can_restart", lambda: can_restart), mock.patch.object(access.threading, "Timer", lambda *args: timers.append(args) or mock.Mock()):
            status, answer = V.call("POST", "/api/v1/lutin/update", V.OWNER, {})
            self.assertEqual(status, 200, answer)          # « running », or already over: the replaced steps take no time
            for _ in range(200):
                answer = V.call("GET", "/api/v1/lutin/update", V.OWNER)[1]
                if answer["state"] not in ("idle", "running"):
                    break
                time.sleep(0.02)
        return answer, timers

    def test_an_update_installed_without_a_supervisor_asks_for_a_restart(self):
        answer, timers = self.run_update((0, "1.0", "1.1"))
        self.assertEqual((answer["state"], answer["before"], answer["after"]), ("installed", "1.0", "1.1"))
        self.assertIn("Sauvegarde faite.", answer["lines"])
        self.assertEqual(timers, [], "nothing restarts Lutin: the person does")
        self.assertEqual(self.status()["restart"], {"needed": True, "possible": False})

    def test_an_update_under_a_supervisor_restarts_lutin(self):
        answer, timers = self.run_update((0, "1.0", "1.1"), can_restart=True)
        self.assertEqual(answer["state"], "restarting")
        self.assertEqual(len(timers), 1, "the restart is planned, after the page has read the state")

    def test_an_update_that_finds_nothing_or_fails(self):
        self.assertEqual(self.run_update((0, "1.0", None))[0]["state"], "up_to_date")
        self.assertEqual(self.run_update((1, "1.0", None))[0]["state"], "failed")
        self.assertFalse(self.status()["restart"]["needed"])

    def test_an_update_while_another_runs_or_during_an_answer(self):
        with mock.patch.object(V.api_v1._offline, "is_active", lambda: False):
            with mock.patch.dict(A.ACTIVE_TURNS, {"conversation": object()}):
                status, answer = V.call("POST", "/api/v1/lutin/update", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))
            with mock.patch.dict(access.UPDATE, {"etat": "en cours"}):
                status, answer = V.call("POST", "/api/v1/lutin/update", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "update_running"))

    def test_restarting(self):
        self.assertEqual(V.call("POST", "/api/v1/lutin/restart", V.DEVICE, {})[0], 403)
        status, answer = V.call("POST", "/api/v1/lutin/restart", V.OWNER, {})
        self.assertEqual((status, answer["error"]["code"]), (409, "cannot_restart"), "nothing would start Lutin again")
        timers = []
        with mock.patch.object(access, "can_restart", lambda: True), mock.patch.object(access.threading, "Timer", lambda *args: timers.append(args) or mock.Mock()):
            with mock.patch.dict(A.ACTIVE_TURNS, {"conversation": object()}):
                status, answer = V.call("POST", "/api/v1/lutin/restart", V.OWNER, {})
            self.assertEqual((status, answer["error"]["code"]), (409, "turn_running"))
            self.assertEqual(timers, [])
            status, answer = V.call("POST", "/api/v1/lutin/restart", V.OWNER, {})
        self.assertEqual((status, answer), (200, {"restarting": True}))
        self.assertEqual(timers, [(0.8, os._exit, [access.RESTART_CODE])], "Lutin stops after answering, with the code « start me again »")

    def test_what_asks_for_a_restart(self):
        self.assertEqual(self.status()["restart"], {"needed": False, "possible": False})
        with mock.patch.object(access, "can_restart", lambda: True):
            self.assertTrue(self.status()["restart"]["possible"])
        access.RESTAURE["fait"] = True
        self.assertTrue(self.status()["restart"]["needed"], "a backup put back")
        access.RESTAURE["fait"] = False
        with mock.patch.object(access, "saved_security", lambda: type(A.SECURITY)(niveau=V.S.LOCAL)):
            self.assertTrue(self.status()["restart"]["needed"], "another access level saved for the next start")



class LutinStartup(unittest.TestCase):
    """`/lutin/startup` (maintainer's request, 2026-11-19): in Settings › General, « check for new versions when Lutin starts » and « start Lutin
    with the machine ». The autostart is replaced: nothing reaches the session of this machine."""

    def setUp(self):
        from lutin import power
        self.asked = []
        for patch in (mock.patch.object(power, "install_startup", lambda: self.asked.append("install")), mock.patch.object(power, "remove_startup", lambda: self.asked.append("remove")),
                      mock.patch.object(power, "startup_state", lambda: {"installe": bool(self.asked) and self.asked[-1] == "install", "possible": True, "limites": ""}),
                      mock.patch.dict(power.STARTUP_MEMO, {"t": 0.0, "v": None})):
            patch.start()
            self.addCleanup(patch.stop)
        config = Path(os.environ["LUTIN_CONFIG"])
        before = config.read_text(encoding="utf-8") if config.is_file() else None
        self.addCleanup(lambda: config.write_text(before, encoding="utf-8") if before is not None else config.unlink(missing_ok=True))

    def test_both_are_read_and_changed_from_this_machine(self):
        status, answer = V.call("GET", "/api/v1/lutin/startup", V.DEVICE)
        self.assertEqual((status, answer["check_updates"], answer["autostart"]["installed"]), (200, True, False), "read by any session, on by default")
        status, answer = V.call("PATCH", "/api/v1/lutin/startup", V.OWNER, {"check_updates": False, "autostart": True})
        self.assertEqual((status, answer["check_updates"], answer["autostart"]["installed"]), (200, False, True))
        self.assertFalse(json.loads(Path(os.environ["LUTIN_CONFIG"]).read_text(encoding="utf-8"))["verifier_maj"], "kept in config.json, read at launch")
        self.assertFalse(A.read_config()["verifier_maj"], "and by the engines' check")
        self.assertEqual(V.call("PATCH", "/api/v1/lutin/startup", V.OWNER, {"autostart": False})[1]["autostart"]["installed"], False)
        self.assertEqual(self.asked, ["install", "remove"])

    def test_refusals_write_nothing(self):
        self.assertEqual(V.call("PATCH", "/api/v1/lutin/startup", V.DEVICE, {"autostart": True})[0], 403, "another device never touches this machine's session")
        for body in ({}, {"autostart": "yes"}, {"check_updates": 1}, {"check_updates": False, "autostart": None}):
            self.assertEqual(V.call("PATCH", "/api/v1/lutin/startup", V.OWNER, body)[0], 400, body)
        self.assertEqual(self.asked, [])
        self.assertTrue(A.read_config().get("verifier_maj", True))


if __name__ == "__main__":
    unittest.main()
