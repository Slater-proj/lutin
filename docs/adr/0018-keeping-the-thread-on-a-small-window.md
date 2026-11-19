# ADR 0018 — Keeping the thread of a long conversation on a small window

Status: accepted on 2026-11-18, decisions 1 to 8 implemented (6 to 8 the same day, second part), decision 9 on 2026-11-19, decision 10 (defects found by the evaluation suite) the same day. The maintainer asked whether the two memories of a long conversation (summary, progress
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

9. **A core of tools on 4,096 tokens or below** (maintainer's decision, 2026-11-19: « fewer tools »). The fourteen schemas left by decision 8 took
   2,782 tokens, 68 % of the window: the history only had its floor (1,024 tokens) and the system message, the tools and that floor already went past
   the window. At `tool_table.TINY_WINDOW` (4,096) or below, `tool_table.spare_tools` also leaves out `lister`, `trouver`, `calculer`,
   `creer_document`, `taches`, `web_chercher` and `web_lire`; what is sent is `lire`, `ecrire`, `modifier`, `chercher`, `executer`, `rappeler` and
   `memoriser`. `executer` lists a folder or finds a file (`dir` or `ls`, run without approval) and computes (with approval); `ecrire` writes a
   Markdown, HTML or CSV document (no PDF nor Word on such a window); `lire` shows the source of a page instead of its picture. `memoriser` stays:
   nothing replaces the durable notes, and it weighs 96 tokens. The task list and the web have no cover and are lost on such a window
   (`tool_table.LOST_ON_TINY_WINDOW`); keeping the web would have kept the history on its floor. The plan of the project no longer tells the model
   to use `lister` when that tool is not sent. Measured on the default mode (`polyvalent`, Web ticked), 4,096 tokens: 14 tools and 2,782 tokens of
   schemas → 7 tools and 1,060 tokens. What the request leaves to the system message and the history (`ajuster_contexte`: 68 % of the window minus
   the tools) goes from 3 tokens to 1,725. With the `CONTEXTE.md` Lutin ships (763 tokens) the system message weighs about 1,130 tokens: before,
   it did not fit beside the tools and nothing of the history did; now about 595 tokens of history are sent. With empty notes (system message
   about 397 tokens) the room of `place_de_l_historique` goes from its floor (1,024) to 1,328 tokens; with the shipped `CONTEXTE.md` it stays on
   its floor, which now fits in the window. From 4,097 tokens on nothing changes. In the `technique` mode with the image tool connected,
   `etat_outil` and `installer_module` stay (tools of that extension, like those of the voice and ComfyUI modules).

   In the sheet mode, the tool of the sheet (`suivi`) comes with the core.

10. **What the evaluation suite found** (`tests/test_evaluation.py`, 2026-11-19): a project of twenty exchanges (an objective, five decisions, a
    current step, answers of about 190 words), then « Où en est-on ? », then a precise question; on 4,096 and 8,192 tokens, with the summary and
    with the sheet, and with a fake model that keeps what it is asked to keep or one that keeps nothing. Three defects, fixed:
    - **In the sheet mode, the first request was lost.** The removal of the start in one block took it with it and nothing kept it: decision 2
      held only for the summary. It is now kept (`depart`) by both, and sent at the head of the history (`bloc_du_debut`: the summary with the
      first request, or the first request alone), the same in the request and in what the recall believes is sent (`ce_que_voit_le_modele` left
      the first request out of the summary).
    - **After a summary, the trimming kept an old message instead of the latest exchange.** It protected the first message of the person still in
      the history as the first request, while the real one was in the summary: on 8,192 tokens, « Point 19 » stayed and turn 20 went. With a
      summary in the request, nothing more is protected.
    - **The history did not get its floor.** The thresholds count on a quarter of the window beyond the system message (decision 6), but
      `ajuster_contexte` kept to 68 % of the window minus the tools: on 8,192 tokens in the sheet mode (3,023 tokens of tools, 1,443 of system
      message with the shipped notes, 1,288 of sheet and extracts) not even the latest exchange was sent. The trimming now gives the history the
      same floor, never past 85 % of the window (`PART_MAX`): the answer keeps at least 15 %, and a retry after a context error lowers both. On
      8,192 tokens the request of the last turn goes from about 5,300 to 6,300 tokens (answer room about 1,900 instead of 2,900).
    Measured after the fixes (fake models, so what the request carries, not what a real model makes of it): with a faithful model, the objective,
    the five decisions and the current step are in front of the model in all four cases; on 8,192 tokens the latest exchange is sent as it is,
    on 4,096 tokens it comes back through the recall (the floor holds the summary and the extracts, not an answer of 190 words besides). With a
    model that keeps nothing, the summary loses the five decisions (the sheet keeps one to three through its « latest requests »), and a precise
    question brings the decision back through the recall. Both windows summarise often: 9 summaries in 22 turns (7 passes of the scribe in the
    sheet mode), each a call to the model.

## Not done yet

- **A summary every two or three answers on 4,096 and 8,192 tokens** (measured above): each is a model call, minutes on a processor. Not changed:
  the threshold follows the room the request leaves, which is small; the sheet costs no call to prune.
- **`CONTEXTE.md` is now the largest fixed cost on 4,096 tokens**: 763 tokens as shipped (19 % of the window), read up to `LIMITE_CONTEXTE`
  characters whatever the window, and it names `web_chercher` and `web_lire`, which such a window does not send. Bounding it by the window is a
  choice to make with the maintainer (it is the person's own description of the project).
- **Measure on a real small model.** The evaluation suite (decision 10) runs the scenario on fake models: it says what the request carries, not
  whether a small model finds its way with it, nor how a real tokenizer counts (Lutin estimates three characters a token). Running it on a real
  model needs Ollama and a small model on the machine, outside the hermetic tests.
- **A task list started on a larger window** is still shown to the model on a 4,096-token one, with the advice to update it with `taches`, which is
  not sent there; a call gets the error that lists the tools available, and the list is closed after a few answers without update.

## Consequences

- A long conversation keeps its objective in front of the model whatever the window, and passages of its start come back once the history overflows.
- The sheet no longer loses its first decisions nor its current step on a small window; `docs/FEATURES.md` says what is really kept.
- `tests/test_moteur.py` (first request kept, summary size, recall when the history overflows, the summary keeps the first request) and
  `tests/test_suivi.py` (a long plan does not push the step out, the first decisions stay). The test of pinned messages now pins a message that is not
  the first request: the first request is kept without a pin.
- Decisions 6 to 8: `tests/test_moteur.py` (the thresholds count the tools sent, the scribe is waited for only below the room, fewer tools on a small
  window, the estimated gauge), `tests/test_suivi.py` (the recall skips what the request sends and looks first at what the trimming dropped),
  `tests/test_tool_table.py` (each spare tool has its cover).
- Decision 9: `tests/test_moteur.py` (the core on 4,096 tokens in two modes, the full tools back on 8,192, the history above its floor, the plan of
  the project without `lister`), `tests/test_tool_table.py` (each tool left out on a tiny window has a cover still sent or is a known loss; the
  window size picks the set).
- Decision 10: `tests/test_evaluation.py` (the scenario, 8 cases; it prints what each case keeps, `LUTIN_EVAL_REPORT=<file>` keeps the report) and
  `tests/test_moteur.py` (the first request at the head after the removal in sheet mode, the latest exchange before an old message after a
  summary, the floor of the history and the room of the answer).
