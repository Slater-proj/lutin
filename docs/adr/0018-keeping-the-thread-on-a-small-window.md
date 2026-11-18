# ADR 0018 — Keeping the thread of a long conversation on a small window

Status: accepted on 2026-11-18, decisions 1 to 8 implemented (6 to 8 the same day, second part). The maintainer asked whether the two memories of a long conversation (summary, progress
sheet) are still useful now that the conversations are in a database (ADR 0017), whether they work, and how to stop conversations from going round in
circles on small machines: the history is dropped fast, the model asks again for what it was told, and a long project loses its thread.

## Context

Read on `2d60093` (`agent.py`, `progress_sheet.py`, `recall.py`, `prompt_layout.py`):

- **The database does not reach the model by itself.** It keeps every message, but the model only sees what fits in its window. The full-text index of
  ADR 0017 serves the search of the page; recall uses its own index. Summary and sheet are therefore still needed: they decide what stays in front of
  the model once the start of the conversation no longer fits.
- **Fixed costs eat a small window.** Every request carries the tool schemas (about 4,000 tokens by Lutin's estimate) and the notes (CONTEXTE.md,
  MEMOIRE.md); the history gets `0.68 × num_ctx` minus the tools. With 8,192 tokens about 1,500 are left for the history, and old turns are dropped on
  nearly every request.
- **What was dropped, and when:**
  1. The trimming of each request removed whole old turns oldest first, **the first request included** (only a message pinned by hand was safe).
  2. The **recall of the thread** (passages of this conversation put back before the question) ran only once a summary existed or in sheet mode. Until
     the summary or the question « summary or sheet? » came (at 60 % of the window, counting the messages only), the oldest messages disappeared with
     no way back.
  3. The **summary** is a summary of the previous summary, capped at 6,000 characters whatever the window (half of a 4,096-token window), and the first
     request is diluted a little more at each pass.
  4. The **sheet** evicted its oldest decisions past 25 (the documentation said a decision is never removed), and when it was too long for its share
     its plan was never shortened: a long plan pushed the current step and the open questions past the final cut.

## Decision

1. **Both memories stay, for different uses.** The sheet keeps the structure of a project (objective, decisions, current step, open questions) and
   costs no model call to prune; it suits work that lasts. The summary costs a call and loses details but needs nothing to manage; it suits a
   conversation. The database keeps everything in both cases, and recall brings back what the question needs.
2. **The first request is never dropped.** The trimming keeps the first message of the person still in the history, as if it were pinned; too long, it
   is cut to a sixth of the budget. The summary keeps it word for word (`depart`, at most 800 characters) and sends it with the summary.
3. **The recall of the thread starts as soon as the history no longer fits** (`deborde`), not only after a summary or in sheet mode.
4. **A summary takes 15 % of the window**, between 1,500 and 6,000 characters (`taille_resume`).
5. **The sheet puts first what must survive and keeps its foundations.** It is given to the model in the order objective, current step, open
   questions, decisions, plan, done, files, requests; when too long, the oldest requests and files go first, then the end of the plan, then the middle
   decisions (the first one and the latest stay), then what is done, and the open questions last. Past 25 decisions, the first five stay with the most
   recent ones.

6. **The thresholds count what the request really carries** (`place_de_l_historique`): the history gets `0.68 × num_ctx` minus the tool schemas
   really sent (`outils_du_mode`, not the whole list) and the system message, never less than a quarter of the window. The summary starts at 60 % of
   the window or 90 % of that room, whichever comes first; the pruning of the sheet at 45 % of the window or once the messages no longer fit the
   room the sheet leaves (its real size is deducted), whichever comes first; it stops waiting for the scribe at 60 % of the window or a tenth of the
   window past that room. A margin below the room was tried and dropped: it pruned conversations that still fitted, and every prune changes the start
   of the request. Before, on
   8,192 tokens, the messages could reach 60 % of the window while the request was trimmed at every answer, and the start of the request changed each
   time (no cache). The estimated gauge counts the tools really sent too.
7. **The recall knows what the model sees** (`ce_que_voit_le_modele`): the request of the next step is rebuilt (system, summary, sheet, room for the
   extracts) and trimmed as it will be; a passage it still contains is not put back, and the passages of messages the trimming drops come before
   those of the archived start. Before, the recall assumed the last six messages were seen and the others were not: on a large window it repeated
   what the model already had, on a small one it ignored that far more than the start was gone.
8. **Fewer tools on a small window.** At 8,192 tokens or below, the tools another one covers (`tool_table.SPARE_ON_SMALL_WINDOW`: `lire_plusieurs`,
   `modifier_plusieurs`, `symboles`, `apercu_page`) are not sent. Measured on the default mode: 3,429 → 2,782 tokens of schemas, and the room left
   to the history on 8,192 tokens goes from about 1,770 to 2,414 tokens.

## Not done yet

- **A 4,096-token window still has no room.** The 14 schemas left take about 2,780 tokens, 68 % of the window: the history gets the floor (a
  quarter of the window) and the request is trimmed at every answer. Shorter descriptions on a very small window, or a smaller set of tools, are a
  design choice to make with the maintainer (the descriptions are what keeps a small model from misusing the tools).
- **Measure on a real small model.** No test runs a whole turn with a 4,096 or 8,192 window and a real model; the evaluation suite (plan step 6) should
  hold one such scenario (a project of twenty exchanges, then « where are we? »).

## Consequences

- A long conversation keeps its objective in front of the model whatever the window, and passages of its start come back once the history overflows.
- The sheet no longer loses its first decisions nor its current step on a small window; `docs/FEATURES.md` says what is really kept.
- `tests/test_moteur.py` (first request kept, summary size, recall when the history overflows, the summary keeps the first request) and
  `tests/test_suivi.py` (a long plan does not push the step out, the first decisions stay). The test of pinned messages now pins a message that is not
  the first request: the first request is kept without a pin.
- Decisions 6 to 8: `tests/test_moteur.py` (the thresholds count the tools sent, the scribe is waited for only below the room, fewer tools on a small
  window, the estimated gauge), `tests/test_suivi.py` (the recall skips what the request sends and looks first at what the trimming dropped),
  `tests/test_tool_table.py` (each spare tool has its cover).
