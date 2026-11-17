# ADR 0015 — One entry runs a turn, whoever asks for it

Status: **proposed**, to be validated by the maintainer before any code (plan step 5, the idea that organises it: « one runtime owns a turn »;
ADR 0012, « Not done yet »).

## Context

A turn is run by `agent.tour`. Before calling it, whoever launches it must take a seat: refuse a second turn in the same conversation, respect the
limit of simultaneous turns (`core.TOURS_SIMULTANES`, two: one graphics card), choose the work folder (`activate_work`, to be called with
`VERROU_TOURS` held), record the stop event in `core.TOURS_ACTIFS` and the folder in `RACINE_TOURS`; after it, free the seat. Five launchers do this
each in their own way (read on `cf30e93`):

| Launcher | Refuses a second turn in the same conversation | Limit | Work folder under the lock | Frees only its own seat | Abandoned turn writes nothing |
|---|---|---|---|---|---|
| the page (`server.Gestionnaire._chat`: `/api/chat`, and `/api/v1/conversations/{id}/turns` of the new Chat) | yes (409) | refuses (429) | yes | yes (`is stop`) | yes (`LOCAL_TOUR.stop`) |
| missions (`mission._tour`) | no | returns « no seat » | yes | no | no |
| scheduled tasks (`scheduled_tasks.executer`) | no | refuses with a reason | yes, new conversation only | no | no |
| Telegram (`addons_telegram`) | no | waits up to 180 s | **no**, after the lock | no | no |
| automatic replies (`auto_reply`) | no | waits up to `MAX_WAIT` | **no**, after the lock | no | no |

What follows from it, **read in the code, not reproduced** (each one gets a failing test before the fix):

- A scheduled task always reuses the same conversation. If a person writes in it when the task starts, two turns run in one conversation; the task
  replaces the stop event of the person's turn (their Stop button then stops the task), and frees the seat when it ends, while the person's turn is still
  running, so a third turn can start.
- « Arrêter » abandons a turn that does not stop within 20 s (`core._rendre_la_main`): its seat is freed and the conversation can go on. Only the page
  marks its thread (`LOCAL_TOUR.stop`) so that the abandoned turn never writes the conversation again (`storage.conv_ecrire`); a turn of the four other
  launchers, if it finishes later, writes over what came after it, and its `finally` frees the seat of the newer turn.
- Telegram and the automatic replies choose the work folder outside the lock, against the rule written in `workspace_manager`.

## Decision (proposed)

1. **`src/lutin/turn_runner.py` is the only code that takes and frees a seat.**
   - `reserve(conv, *, launcher, work="", wait_s=0, give_up=None)` takes the lock, refuses a second turn in the conversation, refuses or waits (`wait_s`,
     checking `give_up`, an event) while the limit is reached, chooses the work folder, records the stop event and the folder, and returns a `Seat`.
     A refusal raises `TurnRefused(code, message)` with one of three codes: `turn_running`, `too_many_turns`, `workspace_conflict` (the codes the page
     already sends).
   - `Seat.run(text, emit, settings, **options)` marks the running thread (`LOCAL_TOUR.stop`) and calls `agent.tour`. `Seat` is a context manager: on
     exit it frees the seat only if it still holds its own stop event.
   - `run_turn(conv, text, emit, settings, *, launcher, ...)` is `reserve`, `run` and the release in one call, for the launchers that have nothing to do
     between taking the seat and running the turn.
2. **Each launcher keeps what is its own**: the page validates the request, deletes a conversation it has just created when the seat is refused, sends
   the head of its stream between `reserve` and `run` (a refusal must come before it), writes the heartbeat. The missions, the scheduled tasks, Telegram
   and the automatic replies call `run_turn` and turn `TurnRefused` into what they do today when no seat is free (return « no seat », note the failure,
   wait). The cheap checks made before any work (the page before it creates a conversation, `/scheduled-tasks/{id}/run` before it starts a thread) stay
   as they are and read `turn_runner.active()`.
3. **Stop and abandon move with it**: `core.arreter_conversation` and `_rendre_la_main` become `turn_runner.stop(conv_id)`; `core` keeps the old names
   as aliases until the old page goes.
4. **Readers do not change**: the bench, the calibration, the workspace manager, the status route and the health checks still read the registry, through
   `turn_runner.active()`. Where the registry lives is ADR 0014's business (stage 2): `turn_runner` is written against `core`'s dictionaries first, and
   moves with them.

## Behaviour changes

Step 5 promises no behaviour change outside items 4 and 5; this one changes behaviour, on purpose, and only where the table above shows a gap:

- the missions, the scheduled tasks, Telegram and the automatic replies no longer start a turn in a conversation that already has one: the mission
  tries again at its next round, the scheduled task notes « a turn is already running in its conversation », Telegram and the automatic replies wait as
  they wait for a seat;
- an abandoned turn writes nothing, whoever launched it, and never frees the seat of a newer turn;
- the work folder is always chosen under the lock.

## Tests

- `tests/test_turn_runner.py` (new): the seat (refusals and their codes, the limit, waiting and giving up, freeing only its own seat, the thread mark),
  with a fake `agent.tour`.
- One test per gap of the table, written first and seen failing on the current code: a scheduled task that starts while a person's turn runs in its
  conversation; an abandoned turn of a scheduled task that finishes later; Telegram choosing the folder under the lock.
- The existing tests of the page, the missions, the scheduled tasks and the add-ons, unchanged, then the full suite.

## Not chosen

- **One function for every launcher, the page included**: the page must refuse before it sends the head of its stream, and send it before the turn
  starts; a single call would need a callback in the middle, which is the two-step `reserve` and `run` under another name.
- **A queue of turns** (a refused launcher waits in line instead of polling): fairer, but it is a new feature (ADR 0003); the waiting of Telegram and the
  automatic replies stays as it is.
- **Fixing the gaps in each launcher**: five copies of the same rules is how the gaps appeared.

## Way back

One commit per launcher after the module itself; reverting a launcher's commit brings back its own code. No stored data changes.

## Questions for the maintainer

- Are the three behaviour changes wanted (they fix defects found by reading; each is proven by a failing test first)?
- Order: this ADR before or after ADR 0014 stage 2 (the registry in the application context)? Proposed: `turn_runner` first, on `core`'s dictionaries,
  since it is smaller and fixes defects; it moves with the registry later.
