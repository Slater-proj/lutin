# ADR 0019 — One memory for long conversations: the progress sheet, kept out of the way

Status: accepted on 2026-11-19. The maintainer asked, after the study of other projects (`docs/modernization/CONTEXT_RESEARCH.md`), to choose
what works best, improve on it, and decide whether to keep both memories of a long conversation (summary, progress sheet). Stages 1 to 6 below
are done one at a time, each measured on `tests/test_evaluation.py`.

## Context

ADR 0018 kept both memories « for different uses ». Measured since on the evaluation suite (a project of twenty exchanges, then « where are
we? », on 4,096 and 8,192 tokens, after ADR 0018 decision 10):

| | Summary | Progress sheet |
|---|---|---|
| Model calls in 22 turns | 9 summaries (half the conversation each) | 7 passes of the scribe (the latest exchanges each) |
| Removals of the start (each changes the prefix: the engine reads everything again) | 9 | 9 |
| Decisions kept with a model that does what it is asked | 5 of 5 | 5 of 5 |
| Decisions kept with a weak model | 0 to 1 of 5 | 1 to 3 of 5 |

Elsewhere: a context rewritten as a whole collapses (ACE, arXiv 2510.04618); the systems that hold apply changes merged by code (ACE, Factory's
anchored summaries, mem0); Cline does not trust models other than the latest ones with an automatic summary; masking old tool results matches an
LLM summary at half the cost (arXiv 2508.21433). The summary of Lutin is a summary of the previous summary, in prose; its sheet is changes merged
by code. Two more defects of today's flow: the scribe runs after the answer but before the turn ends, so the person waits for it (minutes on a
processor); and after a removal the history comes back to its threshold within one or two exchanges.

## Decision

1. **The progress sheet is the memory of every long conversation.** The summary mode and the question « sheet or summary? » are retired. A
   conversation that already has a summary keeps it at the head of the request (`bloc_du_debut`, with the first request), and continues with the
   sheet: nothing is lost, no data is migrated. The settings and routes that choose the mode keep accepting the old values for a while and act
   as the sheet.
2. **The start leaves without the model, far enough.** When the history passes its threshold, the start leaves in one block (archived, found
   again by `rappeler` and the recall of the thread) down to a target well below the threshold, so that several exchanges fit before the next
   removal: each removal changes the start of the request once, and the engine's cache serves in between.
3. **The scribe works out of the way.** It runs once the answer is given, without holding the turn; a new request of the person cancels it, and
   what it has not read yet is read at its next pass. A message it has not read is never removed, unless the window is full (as today).
4. **The scribe answers in a fixed shape.** Its JSON is asked with a schema where the engine supports it (Ollama `format`, llama.cpp
   `json_schema`); an empty or invalid answer changes nothing (as today).
5. **Tool results are bounded by the window.** A result gets a share of the window, cut in the middle with a header saying how to get the rest;
   once the turn is over, old results are replaced in one batch by one line.
6. **The recall answers the question asked.** A question about the state of the work is answered from the sheet; otherwise the query adds the
   previous request of the person, and a passage comes back only above a score threshold.

## Stages

1. Removal with a target (decision 2). 2. The sheet only (decision 1; the tests of the summary mode are rewritten for the sheet or retired with
the feature). 3. The scribe out of the way (decision 3). 4. Tool results (decision 5). 5. The recall (decision 6). 6. The schema (decision 4).
Each stage: before and after on the evaluation suite (model calls, removals, what the request keeps), the full suite green, one commit.

## Progress

Measured on `tests/test_evaluation.py` (fake engine, 22 turns; no real model).

- **Stage 1** (removal with a target, `PART_APRES_RETRAIT` = 40 % of the threshold): 9 → 6 removals in 22 turns, the same decisions kept.
- **Stage 2** (the sheet only): `memoire_longue` is always the sheet; the summary (`compacter`), the question (`demander_memoire`, the
  `choix_memoire` event) and the first fill of the sheet by the model (`amorcer_fiche`) are gone. Old values (`resume`, `demander`) of the setting,
  of a conversation and of the routes are accepted and act as the sheet; `/compact` removes the start in one block after the scribe's pass.
  Two choices made while doing it:
  - *The sheet starts when the conversation is halfway to its removal threshold* (`fiche_active`, `PART_DEBUT_FICHE` = 0.5), or at once for a
    mission, a sheet already filled, or a start already removed or summarised. Turned on from the first message, it made every short
    conversation pay a scribe call every three exchanges and carry its latest requests twice (once in the history, once in the sheet); six
    tests on short conversations caught it. Halfway leaves the scribe the time to read the start before a removal needs it.
  - *On 4,096 tokens, the `suivi` tool is not offered while the scribe keeps the sheet* (ADR 0018, decision 9: a core only): the tool weighs
    240 tokens, 6 % of the window.
  - Scheduled tasks and automatic replies (`lecture_seule`) remove their start and run the scribe too: they used the summary, and without
    either their conversation would grow until every request is trimmed.

  Before → after, 4,096 tokens: request at « where are we? » 3,392 → 3,151 tokens (the tool of the sheet), decisions kept 5/5 (faithful model),
  1/5 (weak), 7 scribe passes, 6 removals; 8,192 tokens: unchanged (6,192 tokens, 5/5 and 3/5, 7 passes, 6 removals). The summary mode it
  replaces asked the model for 9 summaries in the same 22 turns.
- **Stage 3** (the scribe out of the way): the turn writes the conversation, starts the scribe in its own thread (`lancer_scribe`) and ends;
  « fin » no longer waits for the scribe's model call (a test holds that call: before, « fin » came only once it returned). A new request
  (and `/compact`, and the deletion of the conversation) cancels it with a flag (`annuler_scribe`) and does not wait for it: each batch it
  read is kept only under a lock, if it was not cancelled and if the stored conversation still has the messages it read (`_garder_lot`), and
  its rank is written into the stored conversation, nothing else; what it did not keep is read at its next pass. A mission keeps the
  scribe in the turn: its turns follow each other at once and a scribe in the background would be cancelled every time. Not done: the
  cancelled call is not cut at the engine (a flag only, as decided); an engine that answers one request at a time finishes it before the new
  answer starts. Closing its connection would stop it (`chat_flux`) and is left for a measure on a real engine.
- **Stage 4** (tool results bounded by the window): a result enters the conversation at most at `prompt_layout.result_budget` characters, a
  tenth of the window counted as the estimate counts it (JSON form), never more than the old limit (`LECTURE_MAX` + 2,000, so nothing changes
  above about 30,000 tokens) nor less than 600. A longer result is cut in the middle (`cut_middle`: its start and its end, where an output
  usually says what it is and how it ended) under a header that says how much was cut and how to get the rest: `lire` with `debut`/`fin` for
  a file, otherwise « rappeler » with ici=true, which finds the full text kept in the archive (`archive.add_result`, its own role in the same
  file; `recall.result_passages` searches the results of the conversation by words only, in turn with the passages of the thread). `lire`
  (and the shortcut of `executer` for `type`) receives the limit and stops before it, saying where to resume; `executer` no longer cuts its own
  output at `SORTIE_MAX` during a turn (its middle was lost before it could be kept), only beyond 200,000 characters. Choices made while doing
  it, for the maintainer to confirm:
  - *Old results are replaced in the request only, and only in a long conversation* (`fiche_active`, the switch of the sheet): at the start of
    a request, every result of a finished request becomes one line (tool, main argument, size, how to find it again), in one batch
    (`mask_old_results`). The stored conversation keeps them in full (the page shows them; the thresholds of removal still count them, so
    removals come no later than before). In a short conversation nothing is replaced: the model would have to read again what it just read.
  - *A file read twice still appears twice* (the latest read is not singled out): not done.
  Found on the way: a line longer than the limit (a minified file) gave an empty read that sent back to `debut` on that same line, so the
  model could read it again without end; it now gives the start of the line and the next `debut`. Before → after, 4,096 tokens: an output of
  30,000 characters entered the conversation at 2,457 tokens (60 % of the window), now at most 409; 8,192 tokens: at most 819. The
  evaluation suite is unchanged (its scenario calls no tool: a scenario rich in tools is still to write, `CONTEXT_RESEARCH.md` proposal 9).
- **Stage 5** (the recall answers the question asked): a short question about the state of the work (`progress_sheet.is_state_question`:
  « où en est-on ? », « fais le point », « qu'est-ce qui reste ? », « where are we? », 14 words at most) is left to the sheet when the sheet has
  something: neither the thread nor the documents are searched. Otherwise the query of the thread adds the previous request of the person
  (a follow-up such as « comment s'appelle-t-il déjà ? » keeps its subject), and a passage found by words comes back only from a BM25 score
  of 2.5 (`recall.THREAD_MIN_SCORE`, measured on the corpus of `tools/mesurer_rappel.py`: wrong passages reach 2.32, right ones go from 2.12
  to 10.4; a passage found by meaning has passed the threshold of the embeddings), three at most as before. The threshold is absolute, so
  it depends on the size of the index: on a conversation of three chunks a right passage can stay below it; the thread recall only runs
  once the history overflows, when the index has eight chunks or more on 4,096 tokens. Before → after: request at « where are we? »
  3,151 → 2,658 tokens on 4,096 (5/5 and 1/5 decisions kept, unchanged), 6,192 → 6,094 on 8,192, faithful model 5/5 unchanged, **weak
  model 3/5 → 1/5**: two decisions the weak scribe had not written came back through the recall of the thread, which the question no
  longer runs (measured by turning the rule off: 3/5 again; the threshold and the previous request alone change nothing). To be decided by
  the maintainer: keep the rule as decided, or keep the recall for a question of state when the sheet holds few decisions.
- **Stage 6** (the scribe answers in a fixed shape): `agent.SCHEMA_SCRIBE` (each key a list of sentences, every key required, no more items
  than `_scribe_appliquer` keeps) is sent as `format` to the engines that declare they constrain their output (`grammar` = yes: Ollama,
  llama.cpp); the OpenAI form (`response_format` of type `json_schema`) is what llama-server receives. An engine that refuses the schema
  (HTTP error: an old Ollama, a compatible server) gets free JSON at a second try; an engine that declares nothing gets free JSON at once.
  Not measured on a real engine (no real model in the tests).

## Consequences

- One memory to explain, to test and to tune; no question to answer in the middle of a conversation.
- No model call to make room: on a processor, the minutes of the summary disappear from the turn; the scribe's calls leave it too (stage 3).
- The sheet depends on the scribe for its decisions; a scribe that keeps nothing still leaves the latest requests, the first request, the archive
  and the recall. A weak model loses less than with the summary (measured above).
