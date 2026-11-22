"""The layout of a request (plan step 5, item 6, ADR 0013): a prefix that stays, what follows the request just before the last question, what changes
inside a turn at the very end, and one budget shared by the recalled passages. The whole turn on a fake engine is in `tests/test_moteur.py`."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-prompt-layout-"))
for key, value in {"LUTIN_RACINE": str(_TEMP / "project"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ[key] = value
for folder in ("project", "donnees", "memoire"):
    (_TEMP / folder).mkdir()

from lutin import core as _core  # noqa: E402, F401  (core first: agent is one of its parts)
from lutin import agent, prompt_layout  # noqa: E402

TASKS = "\n\n[Tâches en cours : …]\n[>] Corriger"


class Budget(unittest.TestCase):
    def test_recalls_share_a_tenth_of_the_window(self):
        self.assertEqual(prompt_layout.recall_budget(4096), 1228)
        self.assertEqual(prompt_layout.recall_budget(24576), 7372)

    def test_a_usual_window_keeps_the_two_ceilings(self):
        for num_ctx in (16384, 24576, 131072):
            self.assertEqual(prompt_layout.thread_budget(num_ctx), 1800)
            self.assertEqual(prompt_layout.documents_budget(num_ctx, "x" * 1800), 2200, "nothing changes when the window has the room")

    def test_a_small_window_serves_the_thread_first_and_the_documents_with_what_is_left(self):
        self.assertEqual(prompt_layout.thread_budget(4096), 1228)
        self.assertEqual(prompt_layout.documents_budget(4096), 1228, "no extract of the thread: the documents take the share")
        self.assertEqual(prompt_layout.documents_budget(4096, "x" * 700), 528)
        self.assertEqual(prompt_layout.documents_budget(4096, "x" * 1000), 0, "228 characters left say nothing: no recall at all")
        self.assertEqual(prompt_layout.documents_budget(4096, "x" * 5000), 0)


class Block(unittest.TestCase):
    def test_nothing_to_say_is_no_message(self):
        self.assertEqual(prompt_layout.turn_block(), [])
        self.assertEqual(prompt_layout.turn_block("", "  ", "\n\n"), [])

    def test_one_pair_of_messages_so_that_roles_alternate(self):
        block = prompt_layout.turn_block("[Fiche de suivi] A", "[Extraits de la conversation] B", "\n\n# RAPPELS C\n")
        self.assertEqual([m["role"] for m in block], ["user", "assistant"])
        self.assertEqual(block[0]["content"], "[Fiche de suivi] A\n\n[Extraits de la conversation] B\n\n# RAPPELS C", "the sheet first, then the thread, then the documents")
        self.assertEqual(block[1]["content"], "Compris, je m'appuie sur cette fiche.")
        self.assertEqual(prompt_layout.turn_block("", "", "# RAPPELS C")[1]["content"], "Compris, je m'appuie sur ces extraits.")

    def test_the_block_goes_just_before_the_last_question(self):
        history = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "1"}, {"role": "user", "content": "two"}, {"role": "assistant", "content": "", "tool_calls": []}, {"role": "tool", "content": "r"}]
        block = prompt_layout.turn_block("", "", "# RAPPELS C")
        placed = prompt_layout.before_last_question(history, block)
        self.assertEqual(placed, history[:2] + block + history[2:])
        self.assertEqual(len(history), 5, "the history given is not changed")
        self.assertIs(prompt_layout.before_last_question(history, []), history)
        only_tools = [{"role": "assistant", "content": "a"}]
        self.assertIs(prompt_layout.before_last_question(only_tools, block), only_tools, "no question: nowhere to put it")


class Tail(unittest.TestCase):
    def test_the_tail_is_written_at_the_end_of_the_last_message_never_as_a_message_of_its_own(self):
        saved = [{"role": "user", "content": "question"}, {"role": "assistant", "content": "", "tool_calls": [{}]}, {"role": "tool", "content": "result"}]
        marked = prompt_layout.attach_tail(saved, TASKS)
        self.assertEqual(len(marked), 3)
        self.assertEqual(saved[2], {"role": "tool", "content": "result"}, "the conversation is never changed: the message is copied")
        self.assertEqual(marked[2]["content"], "result", "not written yet: the request must first be fitted to the window")
        sent = agent.adjust_context(marked, 24576, 1.0, [])
        self.assertEqual(sent[2], {"role": "tool", "content": "result" + TASKS})
        self.assertEqual(sent[:2], [{"role": "user", "content": "question"}, {"role": "assistant", "content": "", "tool_calls": [{}]}])

    def test_no_tail_is_no_change(self):
        saved = [{"role": "user", "content": "question"}]
        self.assertIs(prompt_layout.attach_tail(saved, ""), saved)

    def test_a_request_that_ends_with_the_model_s_own_words_takes_the_tail_on_the_last_message_of_the_user(self):
        marked = prompt_layout.attach_tail([{"role": "user", "content": "question"}, {"role": "assistant", "content": "half an answer"}], TASKS)
        self.assertEqual(agent.adjust_context(marked, 24576, 1.0, []), [{"role": "user", "content": "question" + TASKS}, {"role": "assistant", "content": "half an answer"}])
        self.assertEqual(prompt_layout.attach_tail([{"role": "system", "content": "s"}], TASKS), [{"role": "system", "content": "s"}], "never on the system message: it is the prefix")

    def test_a_long_result_cut_to_fit_the_window_keeps_the_tail(self):
        long = "ligne\n" * 8000
        marked = prompt_layout.attach_tail([{"role": "system", "content": "s"}, {"role": "user", "content": "question"}, {"role": "assistant", "content": "", "tool_calls": [{}]}, {"role": "tool", "content": long}], TASKS)
        report = {}
        sent = agent.adjust_context(marked, 4096, 1.0, [], report)
        self.assertEqual(report["tronques"], 1, "the result was cut")
        self.assertTrue(sent[-1]["content"].endswith("[... tronqué]" + TASKS), "and the list is still there, after the cut")
        self.assertLess(len(sent[-1]["content"]), 2000)

    def test_the_private_keys_never_reach_the_engine(self):
        marked = prompt_layout.attach_tail([{"role": "system", "content": "s"}] + prompt_layout.turn_block("", "", "# RAPPELS C") + [{"role": "user", "content": "question"}], TASKS)
        for message in agent.adjust_context(marked, 24576, 1.0, []):
            self.assertEqual(set(message), {"role", "content"})

    def test_the_block_of_the_turn_is_not_removed_to_make_room(self):
        old = [m for i in range(40) for m in ({"role": "user", "content": "question %d " % i + "mot " * 300}, {"role": "assistant", "content": "réponse %d " % i + "mot " * 300})]
        block = prompt_layout.turn_block("", "", "# RAPPELS C")
        sent = agent.adjust_context([{"role": "system", "content": "s"}] + old + block + [{"role": "user", "content": "la question"}], 4096, 1.0, [], report := {})
        self.assertGreater(report["tours"], 0, "old exchanges were removed")
        self.assertEqual([m["content"] for m in sent[-3:]], ["# RAPPELS C", "Compris, je m'appuie sur ces extraits.", "la question"])


if __name__ == "__main__":
    unittest.main()
