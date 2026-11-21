# ADR 0015 — One entry runs a turn, whoever asks for it

Status: accepted by the maintainer on 2026-11-17, implemented (plan step 5, the idea that organises it: « one runtime owns a turn »; ADR 0012,
« Not done yet »). Code: `src/lutin/turn_runner.py`, the five launchers; tests: `tests/test_turn_runner.py`.

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

What follows from it, found by reading the code, then **reproduced**: each point below is a test of `tests/test_turn_runner.py` that went through the
real launcher with a fake turn, and failed on `3d67702` before the launcher used `turn_runner` (six failures: two for the scheduled tasks, one for the
missions, three for Telegram and the automatic replies).

- A scheduled task always reuses the same conversation. If a person writes in it when the task starts, two turns run in one conversation; the task
  replaces the stop event of the person's turn (their Stop button then stops the task), and frees the seat when it ends, while the person's turn is still
  running, so a third turn can start.
- « Arrêter » abandons a turn that does not stop within 20 s (`core._rendre_la_main`): its seat is freed and the conversation can go on. Only the page
  marks its thread (`LOCAL_TOUR.stop`) so that the abandoned turn never writes the conversation again (`storage.conv_ecrire`); a turn of the four other
  launchers, if it finishes later, writes over what came after it, and its `finally` frees the seat of the newer turn.
- Telegram and the automatic replies choose the work folder outside the lock, against the rule written in `workspace_manager`.
- Telegram, the automatic replies and the missions start a turn in a conversation that already has one.

## Decision

1. **`src/lutin/turn_runner.py` is the only code that takes and frees a seat** (besides the abandon of a frozen turn, below).
   - `reserve(conv, *, work=None, wait_s=0, give_up=None, poll_s=2, also=None)` takes the lock, refuses a second turn in the conversation, refuses or
     waits (`wait_s`, every `poll_s`, giving up early when the event `give_up` is set) while the conversation or every seat is taken, chooses the work
     folder (`work`; `None` leaves the folder in use as it is), records the stop event and the folder, calls `also(stop)` under the same lock for a
     launcher's own registry (the task at work, the running mission; if it raises, the seat is given back), and returns a `Seat`. A refusal raises
     `TurnRefused` with `code` one of `turn_running`, `too_many_turns`, `workspace_conflict` (the codes the page already sends) and, for the last, the
     reason given by the work folder in `message`.
   - `Seat.run(text, emit, settings, replace_from, **options)` marks the running thread (`LOCAL_TOUR.stop`) for the time of the turn, calls `core.tour`,
     and puts the previous mark back: a thread that runs several turns (a mission, an add-on) is never left marked by an abandoned one. `Seat` is a context
     manager; `release()` frees the seat only if it still holds its own stop event.
   - `run_turn(...)` is `reserve`, `run` and the release in one call (Telegram, the automatic replies). `full()` and `active()` are the cheap reads.
2. **Each launcher keeps what is its own**: the page validates the request, deletes a conversation it has just created when the seat is refused, sends
   the head of its stream between `reserve` and `run` (a refusal must come before it), writes the heartbeat. The scheduled tasks and the missions use
   `reserve` and `run`, because they need the stop event afterwards; Telegram and the automatic replies use `run_turn`. Each turns `TurnRefused` into
   what it did when no seat was free. The cheap checks made before any work stay as they are.
3. **Readers do not change**: the bench, the calibration, the workspace manager, the status route and the health checks still read `core.TOURS_ACTIFS`.
   Where the registry lives is ADR 0014's business (stage 2): `turn_runner` is written against `core`'s dictionaries, and moves with them.

## Behaviour changes

Step 5 promises no behaviour change outside items 4 and 5; this one changes behaviour, on purpose, and only where the table above shows a gap:

- the missions, the scheduled tasks, Telegram and the automatic replies no longer start a turn in a conversation that already has one: the mission
  tries again at its next round, the scheduled task is refused as when the machine is busy (« a reply is already running: the task waits », the sentence
  it already had), Telegram and the automatic replies wait as they wait for a seat;
- an abandoned turn writes nothing, whoever launched it, and never frees the seat of a newer turn;
- the work folder is always chosen under the lock.

## Tests

- `tests/test_turn_runner.py` (new, 12 tests): six through the real launchers (the gaps above, seen failing first), six on the seat itself (refusals and
  their codes, the limit, a launcher's registry that refuses, waiting and giving up, freeing only its own seat, the thread mark).
- The existing tests of the page, the missions, the scheduled tasks and the add-ons pass unchanged (`test_planifie`, `test_mission`, `test_telegram`,
  `test_mail`, `test_x`, `test_moteur`, `test_acces`, `test_web_app_chat` among them), then the full suite.

## Not done yet

- `core.arreter_conversation` and `_rendre_la_main` (Stop, and the abandon of a turn frozen 20 s after it) stay in `core`; the abandon is the one other
  place that frees a seat. Moving them is a move without a change of behaviour, left for the registry's move into the application context (ADR 0014).

## Not chosen

- **One function for every launcher, the page included**: the page must refuse before it sends the head of its stream, and send it before the turn
  starts; a single call would need a callback in the middle, which is the two-step `reserve` and `run` under another name.
- **A queue of turns** (a refused launcher waits in line instead of polling): fairer, but it is a new feature (ADR 0003); the waiting of Telegram and the
  automatic replies stays as it is.
- **Fixing the gaps in each launcher**: five copies of the same rules is how the gaps appeared.

## Way back

One commit per launcher, the first one with the module; reverting a launcher's commit brings back its own code. No stored data changes.

The maintainer validated the three behaviour changes and the order (this ADR before ADR 0014) on 2026-11-17.
