# ADR 0013 — A request has a prefix that stays and a tail that changes

Status: accepted, implemented (plan step 5, item 6). Code: `src/lutin/prompt_layout.py`, `src/lutin/agent.py`, `src/lutin/recall.py`, `src/lutin/web.py`;
tests: `tests/test_prompt_layout.py`, `tests/test_moteur.py`.

## Context

An engine keeps what it has already read: a request that starts like the previous one only costs what follows the common start (the prompt cache of
llama.cpp and Ollama). The loop sends one request per step, and a working turn has many steps: what a request costs is what differs from the one before.

The system message, first in every request, held two things that change:

- **the task list** (`text_tasks`), rewritten each time the model calls `taches`, in the middle of a turn;
- **the recalls drawn from the documents** (`automatic_recalls`), which follow the last question, so they change at every request of the user.

Each change moved the first difference to message 0: the engine read the whole conversation again. The progress sheet and the extracts of the thread were
already placed just before the last question, for that very reason.

Measured on the fake engine of `tests/test_moteur.py` (characters of the serialized messages; Lutin counts three for a token), same replies before and after:

| Conversation | Sent | Read again, before | Read again, after |
|---|---|---|---|
| nine requests in two turns, the model writes its task list three times | 105 691 | 38 263 (36 %) | 14 748 (14 %) |
| five requests for three questions in scenario mode, recalls differ | 52 559 before, 52 971 after | 27 753 (53 %) | 20 631 (39 %) |
| the same work with no task list and no recall (reference) | 63 793 | 12 363 (19 %) | 12 363 (19 %) |

Before, a request that followed a change first differed from the previous one in the system message: three times in the first conversation (8 000 to 9 400
characters read again each time, the whole conversation), at each question in the second. After, a step that follows a change of the list reads 400 to 530
characters again, and the first difference is the end of a message already read. In the second conversation the third question reads 479 characters again
instead of 8 005; the second still reads 7 940, because the previous turn is read once more (see the consequences) and that turn is nearly all of this short
conversation. What is left in every row is the first reading of each new tool result. These conversations are short: before, the cost of a change grew with
the conversation, since it was all of it each time.

## Decision

1. **The prefix is the system message, and nothing in it follows the request.** It holds the instructions, the mode, the two memory files, the skills, the
   project map, the date and the folder of the conversation.
2. **What follows the request goes just before the last question**, in one pair of messages (a user message, a short acknowledgement, so that roles still
   alternate): the progress sheet, the extracts of the thread, and now the recalls drawn from the documents. It is read once for the turn and does not change
   between two steps. From one question to the next, everything before the previous question is kept by the engine.
3. **What changes inside a turn goes at the very end**: the task list is written at the end of the last message of the request (the question at the first step,
   the latest tool result afterwards), under a bracketed label, as the execution directive already is. It is never a message of its own (some chat templates
   refuse two user messages in a row, or a system message that is not first), and it is added after the request has been fitted to the window, so a long tool
   result cut to fit never takes the list with it. When the list changes, the request differs from the previous one only after a message the engine had read
   to its end. The conversation that is saved never contains it.
4. **Recalled passages share one budget**: a tenth of the window for the extracts of the thread and the recalls of the documents together, the thread first
   (it is this conversation's own lost detail), the documents with what is left, and none below 300 characters. Each keeps its own ceiling (1 800 and 2 200
   characters), so nothing changes from a window of about 13 400 tokens up; a 4 096-token window no longer gives half of its room to recalls.
   The progress sheet keeps its own budget, and the task list is bounded by its tool (twelve lines of 140 characters).
5. **The words the model reads do not change** (ADR 0007): the same titles and sentences, at another place. The label of the task list is new.

## Not chosen

- **The task list read once per turn, next to the progress sheet.** It would go stale as soon as the model updates it, and in a long turn the tool call that
  holds the newer list is among the first exchanges removed to fit the window.
- **A message of its own at the end** (user or system role): it breaks the alternation of roles on templates that require it, and after a tool result a
  small model answers it as a new request.
- **Keeping the recalls in the conversation**, so that nothing ever moves: the saved conversation would grow by two thousand characters per question.

## Consequences

- A task list costs its own length at each step instead of the conversation at each change; a list that does not change costs slightly more than before.
- A request that follows a question with a sheet, extracts or recalls reads the previous turn once more (the pair that preceded the previous question is no
  longer there). This was already so for the sheet and the extracts.
- The model reads its task list last, close to where it writes, instead of first.
- `tests/test_moteur.py` checks the same texts at their new place, and that a request starts like the previous one when only the task list changed.

## Not done yet

- The memory notes, the project map and the date stay in the prefix: a note written by `memoriser`, a map rebuilt in the background or midnight still change
  the start of the next request. Reading the system message once per turn is the next step; moving the map is a question of order for the review of step 7.
- Nothing is measured on a real engine: the prompt tokens actually read again on llama.cpp and Ollama belong to plan step 6, item 2.

## Way back

One commit; the saved conversations are not concerned (neither the list nor the recalls were ever stored in the messages).
