# ADR 0018 — Keeping the thread of a long conversation on a small window

Status: accepted on 2026-11-18, first part implemented. The maintainer asked whether the two memories of a long conversation (summary, progress
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

## Not done yet (in this order)

- **Count the tools in the thresholds.** The summary and the pruning of the sheet trigger on the messages alone (60 % and 45 % of the window); with the
  tool schemas the request is trimmed long before. Triggering on what the request really leaves to the history would summarise or prune earlier and
  keep the start of the request stable for the engine's cache.
- **Recall that knows what the model sees.** It skips passages found in the last six messages, assuming they are in the window; it should skip what the
  trimmed request really contains, and look at what was dropped first.
- **Fewer tools on a small window.** The 21 tool schemas take about half of an 8,192-token window; the modes already narrow them, a small window could
  narrow them more.
- **Measure on a real small model.** No test runs a whole turn with a 4,096 or 8,192 window and a real model; the evaluation suite (plan step 6) should
  hold one such scenario (a project of twenty exchanges, then « where are we? »).

## Consequences

- A long conversation keeps its objective in front of the model whatever the window, and passages of its start come back once the history overflows.
- The sheet no longer loses its first decisions nor its current step on a small window; `docs/FEATURES.md` says what is really kept.
- `tests/test_moteur.py` (first request kept, summary size, recall when the history overflows, the summary keeps the first request) and
  `tests/test_suivi.py` (a long plan does not push the step out, the first decisions stay). The test of pinned messages now pins a message that is not
  the first request: the first request is kept without a pin.
