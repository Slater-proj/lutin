"""The state of a running turn (plan step 5, item 2): running, waiting for a person, without a sign of life, being stopped; and which part of the loop it is in."""
import threading
import unittest

import context  # noqa: F401

from lutin import turn_state


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class States(unittest.TestCase):
    def setUp(self):
        self.clock, self.stop = Clock(), threading.Event()
        self.turn = turn_state.begin("c1", self.stop, self.clock)
        self.addCleanup(turn_state.end, self.turn)

    def state(self):
        return turn_state.of("c1")["state"]

    def test_a_turn_runs_from_its_beginning_and_is_gone_at_its_end(self):
        self.assertEqual(turn_state.of("c1"), {"conversation": "c1", "state": "running", "phase": "context", "step": 0, "detail": "", "elapsed_s": 0.0, "idle_s": 0.0})
        self.assertEqual([turn["conversation"] for turn in turn_state.snapshot()], ["c1"])
        turn_state.end(self.turn)
        self.assertIsNone(turn_state.of("c1"))
        self.assertEqual(turn_state.snapshot(), [])

    def test_the_phases_follow_the_parts_of_the_loop(self):
        turn_state.phase("c1", turn_state.MODEL, "qwen", step=1)
        self.assertEqual([turn_state.of("c1")[key] for key in ("state", "phase", "step", "detail")], ["running", "model", 1, "qwen"])
        turn_state.phase("c1", turn_state.TOOL, "lire")
        self.assertEqual([turn_state.of("c1")[key] for key in ("phase", "step", "detail")], ["tool", 1, "lire"], "the step stays until the next model call")
        with self.assertRaises(ValueError):
            turn_state.phase("c1", "thinking hard")
        self.assertEqual(len(turn_state.of("c1")["detail"]), 4)
        turn_state.phase("c1", turn_state.TOOL, "x" * 500)
        self.assertEqual(len(turn_state.of("c1")["detail"]), 120, "a detail is a label, not a text")

    def test_a_turn_without_a_sign_of_life_is_stalled_and_a_sign_of_life_wakes_it(self):
        self.clock.now += turn_state.STALL_AFTER_S - 1
        self.assertEqual(self.state(), "running")
        self.clock.now += 1
        self.assertEqual((self.state(), turn_state.of("c1")["idle_s"]), ("stalled", float(turn_state.STALL_AFTER_S)))
        turn_state.touch("c1")
        self.assertEqual((self.state(), turn_state.of("c1")["idle_s"], turn_state.of("c1")["elapsed_s"]), ("running", 0.0, float(turn_state.STALL_AFTER_S)))

    def test_waiting_for_a_person_is_not_being_stalled(self):
        turn_state.phase("c1", turn_state.TOOL, "ecrire")
        with turn_state.waiting("c1", "Write notes.txt"):
            self.clock.now += 10 * turn_state.STALL_AFTER_S
            self.assertEqual((self.state(), turn_state.of("c1")["detail"], turn_state.of("c1")["phase"]), ("waiting_approval", "Write notes.txt", "tool"))
        self.assertEqual((self.state(), turn_state.of("c1")["detail"]), ("running", "ecrire"), "the answer of the person is a sign of life, and the turn is back in its tool")

    def test_the_wait_ends_even_when_the_block_fails(self):
        with self.assertRaises(RuntimeError):
            with turn_state.waiting("c1", "card"):
                raise RuntimeError("stopped")
        self.assertEqual(self.state(), "running")

    def test_stop_wins_over_everything(self):
        with turn_state.waiting("c1", "card"):
            self.stop.set()
            self.assertEqual(self.state(), "cancelled")
        self.clock.now += 10 * turn_state.STALL_AFTER_S
        self.assertEqual(self.state(), "cancelled")

    def test_an_abandoned_turn_that_ends_late_does_not_erase_its_successor(self):
        newer = turn_state.begin("c1", threading.Event(), self.clock)
        self.addCleanup(turn_state.end, newer)
        turn_state.phase("c1", turn_state.MODEL, "newer")
        turn_state.end(self.turn)
        self.assertEqual(turn_state.of("c1")["detail"], "newer")
        turn_state.end(newer)
        self.assertIsNone(turn_state.of("c1"))

    def test_the_parts_of_a_turn_can_be_called_without_a_turn(self):
        turn_state.touch("nobody")
        turn_state.phase("nobody", turn_state.MODEL)
        with turn_state.waiting("nobody", "card"):
            pass
        self.assertIsNone(turn_state.of("nobody"))

    def test_turns_are_listed_oldest_first(self):
        self.clock.now += 5
        other = turn_state.begin("c0", None, self.clock)
        self.addCleanup(turn_state.end, other)
        self.assertEqual([turn["conversation"] for turn in turn_state.snapshot()], ["c1", "c0"])
        self.assertEqual(turn_state.of("c0")["state"], "running", "a turn without a stop event cannot be cancelled, and says so by running")


if __name__ == "__main__":
    unittest.main()
