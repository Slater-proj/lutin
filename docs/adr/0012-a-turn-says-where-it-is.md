# ADR 0012 — A turn says where it is; the loop is made of parts; an engine says what the loop may ask of it

Status: accepted, implemented (plan step 5, items 2 and 7). Code: `src/lutin/turn_state.py`, `src/lutin/engine_capabilities.py`, `src/lutin/agent.py`;
tests: `tests/test_turn_state.py`, `tests/test_engine_capabilities.py`, `tests/test_moteur.py`.

## Context

One idea organises step 5: one runtime owns a turn, and the web server, the scheduler, the missions and the add-ons are frontends that call it. Three things stood in the way.

- **The state of a turn was implicit and spread.** A conversation was « active » when its stop event was in `core.TOURS_ACTIFS`, a dictionary filled by whoever
  launched the turn (five places); it was « waiting » when an approval card or a memory question carried its id; nothing told a turn that loads a model from one
  that is frozen. A page that had not started a turn (a reload, another device) showed « an answer is still being written » for a turn that was waiting for an
  approval that page would never receive.
- **The loop was one function of 380 lines** (`agent.boucle_agent`): context, request, model call with retries, tools, decision. No part could be called by a test
  without the others.
- **The loop asked « is it Ollama? »** to decide whether it may start the engine and what a video-memory error means.

## Decision

1. **`turn_state` keeps one record per running turn, written by the turn itself** (`agent.tour` records it and removes it, whoever launched it).
   States: `running`, `waiting_approval` (an approval card, or the memory question), `stalled` (running, but nothing has come out for 90 seconds: a model that
   loads, a long command, or something frozen), `cancelled` (Stop was asked, the turn is winding down). A running turn also says which part of the loop it is in
   (`context`, `model`, `tool`), the step, and what it runs or waits for. `stalled` is computed when the state is read: no timer, no thread.
   The wait is recorded before the card is sent, so a client that reads the state on receiving the card finds the turn already waiting.
   Every function is keyed by the conversation and does nothing when no turn is recorded: the parts of a turn can be called alone.
2. **`GET /api/v1/status` gives the records as `turns`**, next to `active_turns`. The Chat uses them to say what a turn started elsewhere is doing.
3. **The loop is made of parts**, in the order a step runs them: `_preparer_boucle` (the context of the turn, read once), `_messages_de_l_etape`,
   `_preparer_requete`, `_appeler_modele` (the three attempts, the stream, the classification of engine errors), `_executer_appels` (tools, loop guard,
   persistence). `boucle_agent` keeps the decision: go on, ask again, conclude, keep the answer. The lines were moved, not rewritten: no behaviour changes.
4. **An engine declares what the loop must know** (`Moteur.aptitudes()` returns an `EngineCapabilities`): how tool calls reach the model, grammar, slots, prompt
   cache, embeddings, token counts, whether the loop may start it (`starts_on_demand`), whether a model too big for the video memory still loads
   (`spills_to_cpu`). An engine that declares nothing gets the cautious answers. The loop reads `starts_on_demand` and `spills_to_cpu` where it compared the
   engine's id, and asks the engine to start itself (`demarrer_sur_demande`). `tools` and `embeddings` must agree with the grid shown on the page, which the
   conformance suite checks against a fake server. This record is not the grid: the grid says what a person can do with an engine.

## Consequences

- The interface, the scheduler and the add-ons can show the state of a turn without guessing it. `core.TOURS_ACTIFS` stays what stops a turn and what forbids two
  turns in one conversation; it is still filled by each launcher.
- A part of the loop can be tested alone: `tests/test_engine_capabilities.py` calls `_appeler_modele` with an engine that does not answer.
- `grammar`, `slots` and `prompt_cache` are declared from the documentation of the engines, not measured: nothing reads them yet (plan step 6, items 2 and 5).

## Not done yet

- A single entry `run_turn` that registers the stop event, enforces one turn per conversation and the limit of simultaneous turns: each launcher still does it.
  Done since by [ADR 0015](0015-one-entry-runs-a-turn.md).
- Showing an approval card on a page that did not start the turn: the page says the turn waits, it cannot answer for it.
- The messages of the loop about a silent engine still name Ollama; only Ollama declares `starts_on_demand` today.
- The context manager (item 6) and the route table with the application context (item 1).
