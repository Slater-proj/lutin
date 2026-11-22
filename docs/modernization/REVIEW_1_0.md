# Review before 1.0.0 (plan step 7)

The report that step 7 of [PLAN.md](PLAN.md) asks for: what was reviewed, what was found, what was fixed, and what is left. The maintainer placed the
whole step in 1.0 (2026-11-22, evening). This first part was written that evening; the step is **not finished** — see « Left ».

## What was already in place before the review

| Plan item | Where it stands |
|---|---|
| 1. How other assistants serve chat and prompts | Studied for the context of small models: [CONTEXT_RESEARCH.md](CONTEXT_RESEARCH.md) (Open WebUI, Cline, Goose, Manus, AnythingLLM, Gemini CLI, studies on multi-turn instructions and tool counts). Not yet written for the tool-call protocol and approvals as such. |
| 2. Prompt assembly in one place | A request has a prefix that stays (system message, tools) and a tail that changes ([ADR 0013](../adr/0013-a-request-has-a-prefix-that-stays-and-a-tail-that-changes.md)); the tool list comes from one table ([ADR 0010](../adr/0010-tool-table.md)); on a small window a core of tools only ([ADR 0018](../adr/0018-keeping-the-thread-on-a-small-window.md)); one entry runs a turn whoever asks ([ADR 0015](../adr/0015-one-entry-runs-a-turn.md)). |
| 3. Reliable tool use | A call missing a required argument is not run and the model is told what to fix (06a2fbd); the turn is made of parts and says where it is ([ADR 0012](../adr/0012-a-turn-says-where-it-is.md)); a model whose template refuses tools answers in text only, said to the person. |
| 4. Bug sweep of the chat path | Each area has tests on the fake engine (stop, stop with a frozen model, approvals, edits and regeneration, attachments, images, memory choice, missions in a conversation, concurrent turns, work folders). |

## Found and fixed during the review

1. **Rephrased searches went past the loop guard.** The guard counted calls identical to the character; a small model that asks « couleur robots
   Marly » then « Marly : la COULEUR des robots » got the same results again and again. Searches (`chercher`, `trouver`, `rappeler`,
   `web_chercher`) are now judged on their words. — f23bbf7, `tests/test_boucles.py`.
2. **A tool failing again and again with other arguments was not a loop.** One wrong path after another, or an edit whose old text is never quoted
   right, could fill the whole turn. From the third error in a row of the same tool, the error comes with advice (read it, check with another tool,
   change the approach, or say what blocks); at the sixth, the turn is brought to a conclusion with its own notice. — f23bbf7,
   `tests/test_boucles.py`, `tests/test_moteur.py`.
3. **The strict offline mode relied on every caller.** One caller that forgot `offline.guard` had let the llama.cpp search reach Hugging Face. A
   single net now refuses, below every caller, a connection to a public address. — e4a79f2, `tests/test_hors_ligne.py`.
4. **A refusal in Docker no longer said how to open the right** (`LUTIN_ADMIN_TOUS`) once the French routes were gone. — 230641a,
   `tests/test_serveur_securite.py`.
5. **The interface page no longer declared its manifest**: a phone could not add Lutin to its home screen any more. — 230641a, `tests/test_moteur.py`.
6. **The verdict of a model wrote « 13.2 Go » next to « 22,6 Go »** on the same card. — 4cbaf70, `tests/test_adequation.py`.

## Reviewed and kept as it is

- **The tool list changes once per conversation**, when the progress sheet becomes active (the tool `suivi` appears). Proposal 8 of
  CONTEXT_RESEARCH.md says to keep the set fixed, because a change empties the engine's cache of the prefix. Here it happens once, and sending
  `suivi` from the first message would cost about 240 tokens on every request, heavy on a small window. Kept.
- **The turn runner** (`turn_runner.py`): seats taken under the lock, freed only by the turn that holds them, a launcher's registry undone when it
  fails. No change.
- **The page's entry of a turn** (`server.Handler._chat`): the seat is freed in a `finally`, an unknown mode is refused before the stream starts,
  a page that stops reading does not stop the turn (the conversation is written at its end). No change.

## Left (the rest of step 7)

- Item 1: write down how the other assistants handle the tool-call protocol, its errors and the approvals, as ATOMIC_AGENT.md does.
- Item 2: proposal 8, « UnTooled »: a model without tool support today answers in text only; describing the tools in the prompt and reading a
  JSON answer would give it the tools. To measure with the bench before deciding (ADR 0007).
- Item 2: proposal 8, the one-line catalogue of the tools on a 4,096-token window (today: a core of tools with full schemas).
- Item 4: read the rest of the chat path line by line (`agent.turn`: approvals, the « Stop » while a tool runs, the resume after a reconnection,
  attachments in a long conversation) and add a test for each bug found.
- Item 5: a before/after on the fake engine for every prompt change; the evaluation suite (`tests/test_evaluation.py`) is the reduced one.
