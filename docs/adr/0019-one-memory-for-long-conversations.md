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

## Consequences

- One memory to explain, to test and to tune; no question to answer in the middle of a conversation.
- No model call to make room: on a processor, the minutes of the summary disappear from the turn; the scribe's calls leave it too (stage 3).
- The sheet depends on the scribe for its decisions; a scribe that keeps nothing still leaves the latest requests, the first request, the archive
  and the recall. A weak model loses less than with the summary (measured above).
