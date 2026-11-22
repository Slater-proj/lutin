"""One entry takes a seat for a turn, runs it and frees it, whoever launched it (ADR 0015).

The first classes go through the real launchers (scheduled tasks, missions, Telegram, automatic replies) with the turn replaced by a fake: each test is a
gap that ADR 0015 found by reading the code, and failed before the launcher used `turn_runner`. The last class tests the seat itself."""
import itertools
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-turn-runner-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "data"), "LUTIN_MEMOIRE": str(_TEMP / "memory"),
                   "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(key, value)
(_TEMP / "project").mkdir(exist_ok=True)
(_TEMP / "work").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402
from lutin import addons_telegram, auto_reply, mission, notifications, turn_runner  # noqa: E402
from lutin import scheduled_tasks as tasks  # noqa: E402


def answering(text="Done."):
    """A fake turn that answers and writes its conversation, as the real one does."""
    def fake(conv, request, emit, r=None, stop=None, replace=None, **k):
        conv["messages"] += [{"role": "user", "content": request}, {"role": "assistant", "content": text}]
        _m.conv_write(conv)
    return fake


_IDS = itertools.count(1)


def refusing(*a, **k):
    raise AssertionError("no turn may start here")


class Clean(unittest.TestCase):
    def setUp(self):
        _m.TOURS_ACTIFS.clear()
        _m.RACINE_TOURS.clear()
        _m.LOCAL_TOUR.stop = None
        self.addCleanup(_m.TOURS_ACTIFS.clear)
        self.addCleanup(_m.RACINE_TOURS.clear)

    def person_writes_in(self, ident, root=None):
        """A person's turn running in the conversation `ident` (its seat taken the way the page takes it), in the work folder `root`."""
        stop = threading.Event()
        with _m.VERROU_TOURS:
            _m.TOURS_ACTIFS[ident] = stop
            _m.RACINE_TOURS[ident] = str(root or _m.RACINE)
        return stop


class ScheduledTasks(Clean):
    def setUp(self):
        super().setUp()
        tasks._write([])
        tasks.RUNNING.clear()
        for patch in (mock.patch.object(notifications, "find", lambda ident: None), mock.patch.object(notifications, "send", lambda *a: None)):
            patch.start()
            self.addCleanup(patch.stop)
        self.task = tasks.add(nom="Summary", prompt="Summarise the repository.", heure="08:00", jours=[0, 1, 2, 3, 4], travail="", notifier="")
        with mock.patch.object(_m, "tour", answering("First summary.")):
            self.conversation = tasks.execute(self.task["id"])          # the task's own conversation, the same at every run

    def test_run_now_while_a_person_writes_in_its_conversation_is_refused(self):
        person = self.person_writes_in(self.conversation)
        with mock.patch.object(_m, "tour", refusing), self.assertRaises(ValueError):
            tasks.execute(self.task["id"])
        self.assertIs(_m.TOURS_ACTIFS.get(self.conversation), person, "the person's Stop button still stops the person's turn")
        self.assertEqual(tasks.RUNNING, {}, "the task is not left « at work »")

    def test_an_abandoned_turn_writes_nothing_and_keeps_the_newer_seat(self):
        newer = threading.Event()

        def abandoned(conv, request, emit, r=None, stop=None, *a, **k):
            with _m.VERROU_TOURS:                                         # what core._rendre_la_main does 20 s after « Stop », then a person writes again
                stop.set()
                stop.abandonne = True
                _m.TOURS_ACTIFS.pop(conv["id"], None)
                _m.TOURS_ACTIFS[conv["id"]] = newer
            conv["messages"] += [{"role": "assistant", "content": "late answer"}]
            _m.conv_write(conv)                                          # the frozen turn finally ends
        with mock.patch.object(_m, "tour", abandoned):
            tasks.execute(self.task["id"])
        self.assertNotIn("late answer", [m.get("content") for m in _m.conv_read(self.conversation)["messages"]])
        self.assertIs(_m.TOURS_ACTIFS.get(self.conversation), newer, "the newer turn keeps its seat")


class Missions(Clean):
    def setUp(self):
        super().setUp()
        config = mock.patch.object(_m, "config_lue", lambda: {"emplacements": {"travail": str(_TEMP / "work")}})
        config.start()
        self.addCleanup(config.stop)
        for m in mission.read():
            mission.action("supprimer", {"id": m["id"]})

    def test_a_mission_waits_while_a_person_writes_in_its_conversation(self):
        conv = _m.conv_new()
        m = mission.create("Game", "Make a small game.", "principal", 8, True, conv_id=conv["id"])
        person = self.person_writes_in(conv["id"], (_TEMP / "work").resolve())          # the same folder: only the conversation is busy
        with mock.patch.object(_m, "tour", refusing):
            self.assertFalse(mission._turn(mission.find(m["id"])), "no turn: the mission tries again at its next round")
        self.assertIs(_m.TOURS_ACTIFS.get(conv["id"]), person)
        self.assertNotIn(m["id"], mission.ALIVE["arrets"])


class AddOns(Clean):
    """Telegram and the automatic replies (mail, X) answer a third person in a conversation of their own."""

    def under_lock(self):
        seen = []
        patch = mock.patch.object(_m, "activate_work", lambda conv, work: seen.append(_m.VERROU_TOURS.locked()))
        patch.start()
        self.addCleanup(patch.stop)
        return seen

    def test_telegram_chooses_the_work_folder_with_the_lock_held(self):
        seen = self.under_lock()
        with mock.patch.object(_m, "tour", answering("Hello.")):
            self.assertEqual(addons_telegram.reply_model("chat-1", "Alice", "Hello", True), "Hello.")
        self.assertEqual(seen, [True])

    def test_an_automatic_reply_chooses_the_work_folder_with_the_lock_held(self):
        seen = self.under_lock()
        with mock.patch.object(_m, "tour", answering("Hi Bob.")):
            self.assertEqual(auto_reply.reply("mail", "Courriel", "bob@example.org", "Bob", "Hi", pause=0.05), "Hi Bob.")
        self.assertEqual(seen, [True])

    def test_telegram_waits_while_a_turn_runs_in_its_conversation(self):
        self.under_lock()
        with mock.patch.object(_m, "tour", answering("First.")):
            addons_telegram.reply_model("chat-2", "Alice", "Hello", True)
        ident = addons_telegram.read()["convs"]["chat-2"]
        person = self.person_writes_in(ident)
        started, result = threading.Event(), []

        def fake(conv, request, emit, r=None, stop=None, *a, **k):
            started.set()
            answering("Second.")(conv, request, emit)
        with mock.patch.object(_m, "tour", fake):
            worker = threading.Thread(target=lambda: result.append(addons_telegram.reply_model("chat-2", "Alice", "Again", True)))
            worker.start()
            self.assertFalse(started.wait(0.5), "no second turn while the first one runs")
            self.assertIs(_m.TOURS_ACTIFS.get(ident), person)
            with _m.VERROU_TOURS:
                _m.TOURS_ACTIFS.pop(ident, None)
                _m.RACINE_TOURS.pop(ident, None)
            worker.join(10)
        self.assertEqual(result, ["Second."], "the waiting message is answered once the conversation is free")


class Seats(Clean):
    def conv(self):
        """A conversation of its own. Not from a clock: on Windows with Python 3.12 `monotonic_ns` moves every 15.6 ms, and two calls gave one id."""
        return {"id": "c-%d" % next(_IDS), "messages": []}

    def test_one_turn_per_conversation_and_a_limit(self):
        a, b, c = self.conv(), self.conv(), self.conv()
        with mock.patch.object(_m, "TOURS_SIMULTANES", 2):
            first = turn_runner.reserve(a)
            with self.assertRaises(turn_runner.TurnRefused) as refused:
                turn_runner.reserve(a)
            self.assertEqual(refused.exception.code, turn_runner.TURN_RUNNING)
            turn_runner.reserve(b)
            self.assertTrue(turn_runner.full())
            with self.assertRaises(turn_runner.TurnRefused) as refused:
                turn_runner.reserve(c)
            self.assertEqual(refused.exception.code, turn_runner.TOO_MANY_TURNS)
            first.release()
            self.assertFalse(turn_runner.full())
            self.assertEqual(set(turn_runner.active()), {b["id"]})

    def test_a_work_folder_that_cannot_be_used_takes_no_seat(self):
        a = self.conv()
        with mock.patch.object(_m, "activate_work", mock.Mock(side_effect=ValueError("busy folder"))), self.assertRaises(turn_runner.TurnRefused) as refused:
            turn_runner.reserve(a, work="elsewhere")
        self.assertEqual((refused.exception.code, refused.exception.message), (turn_runner.WORKSPACE_CONFLICT, "busy folder"))
        self.assertEqual((_m.TOURS_ACTIFS, _m.RACINE_TOURS), ({}, {}))

    def test_a_launcher_registry_that_refuses_gives_the_seat_back(self):
        def also(stop):
            raise ValueError("already at work")
        with self.assertRaises(ValueError):
            turn_runner.reserve(self.conv(), also=also)
        self.assertEqual(_m.TOURS_ACTIFS, {})

    def test_waiting_for_a_seat_then_giving_up(self):
        a, b = self.conv(), self.conv()
        with mock.patch.object(_m, "TOURS_SIMULTANES", 1):
            held = turn_runner.reserve(a)
            threading.Timer(0.2, held.release).start()
            turn_runner.reserve(b, wait_s=5, poll_s=0.05).release()       # the seat came free while it waited
            held = turn_runner.reserve(a)
            begin = time.monotonic()
            with self.assertRaises(turn_runner.TurnRefused):
                turn_runner.reserve(b, wait_s=0.3, poll_s=0.05)
            self.assertGreaterEqual(time.monotonic() - begin, 0.3)
            give_up = threading.Event()
            give_up.set()
            begin = time.monotonic()
            with self.assertRaises(turn_runner.TurnRefused):
                turn_runner.reserve(b, wait_s=30, poll_s=0.05, give_up=give_up)
            self.assertLess(time.monotonic() - begin, 5, "a launcher that is stopping does not wait")
            held.release()

    def test_a_seat_is_freed_only_by_its_own_turn(self):
        a = self.conv()
        seat = turn_runner.reserve(a)
        newer = threading.Event()
        with _m.VERROU_TOURS:
            _m.TOURS_ACTIFS[a["id"]] = newer
        seat.release()
        self.assertIs(_m.TOURS_ACTIFS.get(a["id"]), newer)

    def test_the_thread_is_marked_only_while_the_turn_runs(self):
        a = _m.conv_new()
        marks = []

        def fake(conv, request, emit, r=None, stop=None, *x, **k):
            marks.append(getattr(_m.LOCAL_TOUR, "stop", None) is stop)
            stop.abandonne = True
            conv["messages"].append({"role": "assistant", "content": "late"})
            _m.conv_write(conv)                                      # abandoned: not written
        with mock.patch.object(_m, "tour", fake):
            seat = turn_runner.run_turn(a, "question", lambda e: None)
        self.assertEqual(marks, [True])
        self.assertTrue(seat.abandoned)
        self.assertEqual(_m.conv_read(a["id"])["messages"], [])
        self.assertIsNone(getattr(_m.LOCAL_TOUR, "stop", None), "the thread can write the next conversation it handles")
        self.assertEqual(_m.TOURS_ACTIFS, {})


if __name__ == "__main__":
    unittest.main()
