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
7. **The file and the image of a request were lost after three tool calls.** Their content went to the model only while their message was among
   the last six; inside one request, three tool calls pushed it out, and from the fourth step the model read « non rejoué ici » instead of the
   file it was working on (and the start of the request changed mid-turn, which also emptied the engine cache). The message of the request in
   progress is now always replayed, with its images. — 58443f9, `tests/test_moteur.py`.
8. **A search result of ExLlamaV3 could have no precision and no button** (seen by the maintainer). Some GGUF repositories carry the « exl3 » tag
   of their base model and came back from `filter=exl3`; they are left out. Community EXL3 repositories that keep their only quantisation on
   `main` had an empty list; `main` is offered when it holds a whole model. — 2af53f6, `tests/test_exllamav3_modeles.py`.
9. **The importance matrix of « i1 » GGUF repositories (`.imatrix.gguf`) was listed as the lightest precision** by llama.cpp and LM Studio,
   so it could be advised and downloaded. — 93ec052, `tests/test_moteur_llamacpp.py`, `tests/test_modeles_geres.py`.
10. **CI**: the Docker job asked `/api/v1/setup` after a `PATCH /settings` that makes the installation look used (147cefc); a test compared a
    short 8.3 path with a long one on the Windows runner (c409a16).
11. **At the forced last step, the question of the user could be removed.** The fitting of the history took the added « Tu as assez
    d'informations… » message for the question to keep; after an earlier request, on a small window, the real question went before the tool
    results of the turn. The messages Lutin adds to a step are now marked and never taken for the question. — 684ca2d, `tests/test_moteur.py`
    (4,096 tokens, thirteen reads after a first request).
12. **A model whose template refuses tools lost its images** in the flattened request, even when it sees. They follow their message now. —
    0f20908, `tests/test_moteur.py`.

## Found, not fixed yet

- **A page opened again while an approval card waits cannot show it.** The card goes only to the stream of the page that sent the message; a
  reloaded page says so (`chat.elsewhere.waiting`) and can only stop the answer. Fix proposed: `GET /conversations/{id}/approvals` (the pending
  cards, from `PendingApproval.EN_COURS`) and the same card in the Chat. About half a day with its tests: for the maintainer to place in 1.0 or 1.x.

## Reviewed and kept as it is

- **The tool list changes once per conversation**, when the progress sheet becomes active (the tool `suivi` appears). Proposal 8 of
  CONTEXT_RESEARCH.md says to keep the set fixed, because a change empties the engine's cache of the prefix. Here it happens once, and sending
  `suivi` from the first message would cost about 240 tokens on every request, heavy on a small window. Kept.
- **The turn runner** (`turn_runner.py`): seats taken under the lock, freed only by the turn that holds them, a launcher's registry undone when it
  fails. No change.
- **« Stop » in `agent.turn`**: during a tool, the calls left each get an « Interrompu » answer before the turn ends, so the conversation stays
  valid for the engine; during an approval, the turn ends as soon as the wait does; while the model writes, the text already written is kept.
  At the next turn, `repair_conversation` answers any call still without a result (a crash). No change.
- **The notices of `agent.turn` written without `_t`** (« Arrêté… », « Accord automatique : »…): `translate_event` translates every event by its
  template on the way out, and each of them is in `messages.en.json` (checked by a scan of the event literals). Not a bug.
- **The retries of `_call_model`**: after a repeated or empty answer, the text already shown stays on the page, followed by the notice of the
  retry; the conversation keeps only the answer of the last try. Kept.
- **The memory choice**: one value since ADR 0019 (the progress sheet); the old answer of the page gets `no_pending_choice`. No change.
- **The resume of a request that got no answer**: the same text sent again is not added twice, and its images and files are given back. No change.
- **The page's entry of a turn** (`server.Handler._chat`): the seat is freed in a `finally`, an unknown mode is refused before the stream starts,
  a page that stops reading does not stop the turn (the conversation is written at its end). No change.

## Tool calls, their errors and approvals in other assistants (item 1)

Study made on 2026-11-22, in the manner of ATOMIC_AGENT.md: what each does, what Lutin takes, leaves, and why. **Sources and their limits**: public
documentation only, read through search summaries; no source file of these projects was read nor run. The pages: OpenHands
(`openhands.llm.fn_call_converter`, docs.all-hands.dev), Continue (docs.continue.dev, agent « how it works » and model capabilities), Cline
(docs.cline.bot auto-approve and YOLO mode, release blog 3.35), Goose (block.github.io/goose, permission modes and tool permissions), Codex CLI
(developers.openai.com/codex, agent approvals and sandboxing), Claude Code (code.claude.com/docs/en/permissions), the Anthropic API
(platform.claude.com, « Handle tool calls ») and the OpenAI API (function calling, structured outputs). Some of these pages disagree with older
copies of themselves (Continue's fallback, OpenAI's strict mode with parallel calls): the newest official page was taken.

| Area | Others | Lutin | Verdict |
|---|---|---|---|
| A model without native tools | OpenHands writes the tools into the system prompt, adds examples to the first message, and reads calls in function tags, stopping at the closing tag; Continue does the same in XML, marked experimental and « may not work as well », 7B–13B models said to struggle; Cline sends native tools since 3.35 and keeps the text format only for models without them | answers in text only; a call that a tooled model writes as text is read (`extract_text_calls`); a template that refuses tools gets a flattened request | **to measure** (proposal 8a): the two who do it warn that small models do it badly, which is the case it would serve. No change without a measure on the bench |
| A malformed call | Anthropic and OpenAI offer a strict schema (`strict: true`) that the server enforces; Atomic Agent a GBNF grammar | `check_arguments`: a missing or unreadable argument is not run, the model gets what to correct with the expected form; `normalize_arguments` repairs a bare string, `key=value`, a neighbour name | kept. A grammar on llama-server is the strict mode of a local engine: 1.x, with the bench |
| A tool that fails | Anthropic: `tool_result` with `is_error: true` and the message, so the model retries with a corrected input; its tool runner turns an exception into such a result | the result starts with « Erreur : » and says what went wrong; after 3 errors of the same tool in a row, advice; after 6, the turn concludes (f23bbf7) | kept: Ollama's and OpenAI's messages have no error field, the text prefix carries it to every engine. Taken from Anthropic: the error says what to correct (already so) |
| Parallel calls | OpenAI: several calls per answer by default, `parallel_tool_calls: false` for one | every call of an answer is run in order; neighbouring reads are read at the same time (`grouped_reads`) | kept |
| Approvals, levels | Codex: sandbox modes (read-only, workspace-write) × approval policy (on-request…), network off in the workspace sandbox; Goose: auto, smart approve (read-only allowed, state changes ask, an LLM judges unknown tools), approve, chat (no tool); Cline: auto-approve per tool, YOLO for everything | reads never ask; writes and commands ask unless the switch of the conversation says otherwise; dry run; missions refuse what is not granted; read-only scheduled tasks | kept. Left: a global YOLO switch (one conversation at a time is the rule here) and an LLM that judges risk (a small local model judging its own calls is no guard) |
| Approvals, rules | Claude Code: deny → ask → allow, the first match wins, a bare tool name removes the tool; Goose: per tool always allow / ask / never | `approval_rules`: deny > ask > allow, a hardline list never remembered, project rules can only ask or deny, « once / this chat / always » | kept: the same precedence. Lutin's project rules cannot grant, which Claude Code's project settings can |
| Sandbox | Codex runs commands in an OS sandbox; Atomic Agent says it is not one | no OS sandbox: paths checked against the working folder, a validator without shell, a copy before every edit, the strict offline net | left for 1.0: an OS sandbox differs on each system. Now said plainly in docs/SECURITY.md (« Workspace folders ») |

## Left (the rest of step 7)

- Item 2: proposal 8, « UnTooled »: a model without tool support today answers in text only; describing the tools in the prompt and reading a
  JSON answer would give it the tools. To measure with the bench before deciding (ADR 0007).
- Item 2: proposal 8, the one-line catalogue of the tools on a 4,096-token window (today: a core of tools with full schemas).
- Item 4: the line by line reading of `agent.turn` is done. Left: the approval card of a reloaded page, if the maintainer places it in 1.0.
- Item 5: a before/after on the fake engine for every prompt change; the evaluation suite (`tests/test_evaluation.py`) is the reduced one.
