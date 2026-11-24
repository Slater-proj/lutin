# `/api/v1`: design

The contract the new interface will be built on ([ADR 0001](../adr/0001-english-and-clean-break-at-1.0.md), [ADR 0002](../adr/0002-frontend-svelte-typescript-vite.md)).
This page fixes the rules. Implemented so far (`src/lutin/api_v1.py`, contract in `tests/test_api_v1.py` and `tests/fixtures/api_v1_routes.json`): the dispatcher with declared rights and coded errors, `GET /status`, the settings (read, change), the conversations (list, create, read, rename/pin, delete, stop), the turn stream and the answer to an approval, the options of a conversation, the models (list, install, delete). Since 1.0 every screen of the interface uses it (243 routes in the fixture). The present contract — the exact routes, the prefixes, the stream events, the right each route asks —
is inventoried in `tests/fixtures/api_contract.json` and enforced by `tests/test_api_contract.py` and `tests/test_api_access.py`.

## Why not rename the present routes in place

The present page (4 500 lines of JavaScript) reads the French fields everywhere. Renaming in place means changing server and page together, in one step,
with nothing to compare against. A second, versioned API lets the new interface be built screen by screen while the old page keeps working, and the old
routes disappear with the old page, in one deletion.

## Rules

1. **Names.** English, from the [glossary](GLOSSARY.md). Paths in `kebab-case`, JSON fields in `snake_case`.
2. **Resources, not actions.** `GET /api/v1/conversations`, `POST /api/v1/conversations`, `DELETE /api/v1/conversations/{id}`,
   `POST /api/v1/conversations/{id}/turns` — instead of `/api/nouvelle`, `/api/supprimer`, `/api/chat`. The server only knows `GET` and `POST` today;
   `PUT`, `PATCH` and `DELETE` are added with the route table (plan step 5 brings the table, v1 is its first user).
   An action that is not a resource stays a verb under its resource: `POST /api/v1/engines/{id}/start`.
3. **Errors carry a code.** `{"error": {"code": "local_only", "message": "…"}}`. The message is for the user, in the user's language; the code is for the program.
   No behaviour ever depends on the wording again: today the server appends a hint when a refusal contains the French words « cette machine ». That cannot
   work once the caller has already translated the message, and it misses two refusals worded « depuis la machine de Lutin ».
4. **Status codes mean one thing each.** `400` invalid request, `401` no session, `403` session without the right (code says which: `page_token`, `configurator`,
   `local_only`, `node_right`), `404` unknown, `409` conflict with the present state (`turn_running`, `workspace_conflict`, `offline`), `413` too large, `429` too many attempts, `503` engine unavailable.
5. **Rights are declared, not scattered.** Each route of the table states one of: `public`, `session`, `read`, `configurator`, `local`, `node`. The check is done once,
   by the dispatcher, before the handler runs. The access test then reads the table instead of the source.
6. **The stream keeps its format** (`application/x-ndjson`, one JSON object per line, a heartbeat line to stay open behind a proxy) with English event names:

   | Today | v1 | Carries |
   |---|---|---|
   | `debut` | `start` | the turn begins |
   | `texte` | `text` | a piece of the answer |
   | `pensee` | `thinking` | a piece of the model's reasoning |
   | `outil` | `tool_call` | the model calls a tool |
   | `resultat` | `tool_result` | what the tool answered |
   | `approbation` | `approval_request` | an action waits for the user |
   | `accord_suspendu` / `accord_retabli` | `auto_approval_suspended` / `auto_approval_restored` | web content was read during this request |
   | `choix_memoire` | `memory_choice` | no longer emitted since ADR 0019 (kept for a paired machine running an older Lutin) |
   | `taches` | `tasks` | the task list changed |
   | `etat` | `status` | what the agent is doing |
   | `info` | `notice` | a message for the user, not part of the answer |
   | `essai` | `dry_run` | what would have been done |
   | `erreur` | `error` | same shape as rule 3 |
   | `fin` | `end` | the turn is over, with its figures |

   Implemented by `POST /api/v1/conversations/{id}/turns` (`api_v1.EVENTS`, contract in `tests/test_api_v1_turns.py`). Fields of each event, besides `type`:

   | v1 event | Fields |
   |---|---|
   | `start` | `conversation_id` |
   | `text`, `thinking`, `status`, `notice` | `text` |
   | `tool_call` | `name`, `arguments` — what the model wrote, not translated ([ADR 0007](../adr/0007-model-facing-language.md)) |
   | `tool_result` | `name`, `text`; when the tool produced files: `media`, `media_files`, `attached_files` |
   | `approval_request` | `id` (answered with `POST /api/v1/approvals/{id}`), `title`, `detail`, `diff`, `reason`, `auto_approval_suspended` |
   | `auto_approval_suspended` | `reason` |
   | `auto_approval_restored` | — |
   | `memory_choice` | `conversation_id` |
   | `tasks` | `tasks`: `[{"text", "state"}]`, state `todo`, `in_progress` or `done` |
   | `dry_run` | `title`, `detail`, `diff` |
   | `error` | `error`: `{"code": "turn_failed", "message"}` |
   | `tokens` | `used`, `total`, `measured` |
   | `speed` | `write_tokens_per_s`, `read_tokens_per_s` (may be null), `load_s`, `total_s`, `tokens` |
   | `end` | `conversation`: `{"id", "title"}` |

   `tokens` and `speed` are the two events the first inventory missed (their fields come from a variable). The request body: `message` and, optionally,
   `model`, `thinking`, `replace_from`, `images`, `attachments`, `workspace`, `machine` (a paired machine that answers this turn; an unknown one falls back to this machine). A refusal comes before the stream as an ordinary error: `400 invalid_request`,
   `409 turn_running` or `workspace_conflict`, `429 too_many_turns`. `memory_choice` was answered with `POST /api/v1/conversations/{id}/memory-choice` (now always `409 no_pending_choice`: no question is asked)
   (`{"choice": "summary" | "file", "remember": false}`; `409 no_pending_choice` when nothing waits). Not in v1 yet: the download of an attached document.
7. **Versioning.** `/api/v1` only ever gains optional fields and new routes. A change that breaks a client is `/api/v2`. The page and the server ship together,
   so the page never talks to a server of another version; the rule protects scripts and paired machines.
8. **Machine-to-machine protocol** (`/api/noeud/*` today): versioned separately (`/node/v1`), because two machines may run different versions of Lutin.
   A node states its protocol version in its status; an older or newer peer gets a clear refusal, not a malformed exchange.
9. **No route does two things depending on a missing field.** Thirteen routes today check the configurator right only for some inputs; in v1 each becomes
   two routes or one route with one rule.

## Settings

`GET /api/v1/settings` gives every setting; `PATCH /api/v1/settings` changes the ones it names and answers with all of them as they now stand
(`api_v1.SETTINGS`, contract in `tests/test_api_v1_settings.py`). Both ask for a session, as the French route does: a paired device may change them.

- One English name and one kind per stored setting (46 today). Engine parameters keep the engines' own names (`num_ctx`, `num_predict`, `temperature`,
  `top_p`, `top_k`, `min_p`, `repeat_penalty`, `num_thread`). A kind is `boolean`, `integer`, `number`, `string`, `strings` (a list) or `object`;
  seven settings also accept `null`, which means « automatic ».
- Four settings are a word, translated in both directions: `mode` (`general`, `technical`, `scenario`, `research`, `chat`), `thinking_steps`
  (`always`, `first`), `long_memory` (`summary`, `file`, `ask`: all accepted, all mean the progress sheet since ADR 0019, read back as `file`), `auto_recall` (`scenario`, `always`, `never`). The mission mode is not a setting:
  it is chosen conversation by conversation. Tool names (`disabled_tools`) are what the models see and are not translated (ADR 0007).
- A write is all or nothing: an unknown name or a value of the wrong kind answers `400 invalid_request` and nothing is stored. Values are then checked
  and bounded by the function the French route calls (a dangerous command in `commands_without_approval` is refused, `max_steps` is kept within 4-40…).
- `commands_without_approval`, `disabled_tools` and `tool_command_timeout_s` are read with the others but written only with
  `PATCH /settings/tool-safety` (right `configurator`, like approval rules): what runs without an approval is a stronger « allow ». `PATCH /settings`
  refuses them with `400 invalid_request`.

## Options of a conversation

`GET /api/v1/conversations/{id}/options` gives the options that apply to one conversation; `PATCH` changes the ones it names and answers with all of them
(`api_v1.OPTIONS`, contract in `tests/test_api_v1_settings.py`). They override the settings of the machine for that conversation, **except the two automatic approvals**
(`auto_approve_writes`, `auto_approve_commands`), which never come from the settings: they are false until the user ticks them for this conversation.
Options: `mode` (`general`, `technical`, `scenario`, `research`, `chat`, and `mission`, which is chosen conversation by conversation and makes the next message the brief of a long task),
`thinking`, `web`, `dry_run`, `num_predict` (0, 512, 1024 … 32768) and `mission_hours` (1, 2, 4, 8, 12, 24, 48, 72). A write is all or nothing. It is allowed while a turn runs: a box ticked during an answer counts from the next tool.

## Images and documents

`POST /api/v1/images` takes the **bytes of the image as the body** (not JSON; PNG, JPEG, GIF or WebP, recognised from the content, at most 8 MB) and answers `201 {"id", "url"}`.
`POST /api/v1/attachments` takes the bytes of a document (at most 20 MB), its name in the `X-Name` header (URL-encoded), and answers `201 {"id", "name", "characters"}`: the text is extracted at once and a file with none is refused (`400`).
`GET /api/v1/attachments/{id}?name=` (right `read`, like the images) gives the document back as it was sent, always as a download (`Content-Disposition: attachment`, never displayed); `name` is the name it is saved under.
An upload over its limit is read, thrown away and answered `413 too_large`. The next message names them: `images: ["<id>"]`, `attachments: [{"id", "name"}]` (4 images and 5 documents at most).
`GET /api/v1/images/{id}` gives the image back. It is the one route with the right **`read`**: a session is enough and the page token is not asked, because a browser tag (`<img>`) sends the cookie and cannot send a header.
The right is for a `GET` only (declared in `route()`, tested), and a test lists the routes that have it. Stored messages keep the shape of the chat format: `images` is a list of identifiers and `pieces` a list of `{"id", "nom"}`.

## Machine and guided choice

Three read-only routes, the first pieces of the guided choice of a model ([GUIDED_SETUP.md](GUIDED_SETUP.md)); contract in `tests/test_api_v1_guide.py`, on a fictive machine.

- `GET /api/v1/machine`: `{"detected": false}` while the detection runs (it starts programs, so it is never waited for: ask again in a second or two), else `cpu`, `cores`, `ram_gb`, `gpus`
  (`name`, `vendor`, `memory_gb`, `integrated`), `disks`, `budget_gb` (what a model may fill), `class` (`no_gpu`, `small`, `medium`, `large`, `very_large`) and a `summary` sentence.
- `GET /api/v1/models/catalog` (`?advanced=1` adds the advanced models): each model with its figures, `capabilities` (`tools`, `thinking`, `vision`), `roles` (editorial notes, 1 to 10),
  `fit` for **this machine** (`level`: `comfortable`, `good`, `tight` or `too_big`, with a `text`; null until the machine is detected), `compatibility` with the engine in use, and `installed`.
  The `disclaimer` of the catalogue says its notes are estimates, not measures: the page shows it.
- `GET /api/v1/models/recommendation?use=chat|code|documents|unsure`: the model that fits this machine and this engine best (`recommended`: the same entry as the catalogue, `context_tokens`, `memory_gb`,
  `runs_on`: `gpu`, `partial` or `cpu`), the other fitting choices (`alternatives`), and `download`: the models still to fetch, their size, the free space of the disk they go to and whether it fits
  (null when the disk cannot be reached). It also gives the engine state and whether strict offline mode is on. **It downloads nothing**: the page shows these figures, asks for a confirmation, then calls `POST /models`.

The verdicts are computed by the server (`model_fit`, `model_compat`) and never by the page. Not done yet: the manual correction of the machine, and the English text of the catalogue (summaries and families are French only).

## Engines

`GET /api/v1/engines` gives one card per program (ADR 0020: Ollama, llama.cpp, ExLlamaV3, LM Studio, Colibri, and another server compatible with OpenAI reached by its address): `id`, `name`, `kind`, `current`, `installed`, `running`, `version`, `models_count`, strengths and weaknesses,
`runs_here` (`possible`, and the `reason` when it cannot run on this machine: system, graphics card, Docker, Python),
the six `actions` (`install`, `uninstall`, `reinstall`, `start`, `stop`, `update`), each with `possible` and the `reason` (what it does, or why it cannot), and the `task` in progress
(`state`: `running`, `done` or `failed`; `text`, `done`, `total`, `error`). The engines are read at the same time and, for each, its three questions too: one that does not answer costs one wait of 2 s for the whole list, not three per engine.
`POST /api/v1/engines/{id}/actions/{action}` (right `configurator`) starts an action in the background and answers `202` with the task. **What changes the machine (install, uninstall, reinstall, update) needs
`{"confirm": true}`**: without it the answer is `400 confirmation_required` carrying what the action does, so that a client has to show it and have it accepted. What needs the network is refused in strict offline mode
(`409 offline`); an action the engine does not allow is `400 action_impossible` with its reason; a second task on the same engine is `409 task_running`.
`DELETE /api/v1/engines/{id}/task` asks the running task to stop (what was downloaded is kept). It is the machinery of the present page (`lutin.engines`), under English names.

`GET /api/v1/activity` (session) answers `{"items": [{id, kind, name, action, state, text, done, total, finished_at}]}`: everything Lutin is downloading or installing, whoever started it (an engine task: install, update, start, download of a model by the engine in use; a download of Ollama; the model that searches by meaning), in one shape, for the bar at the top of every screen. `state` is `running`, `done` or `failed`; a success is kept 25 s and a failure 10 min after its end (`engines.END_RESULT_S`, `END_ERROR_S`), so that nothing disappears without saying how it ended. `done` and `total` are bytes for a download and steps for an installation: only their ratio is meaningful. Stopping a server is not listed.
Not in v1 yet: the settings of an engine (address, key, folders, variant) and the catalogue of external servers.

## Devices and pairing

`GET /api/v1/devices` answers `{"devices": [{id, name, paired_at, seen_at}], "level", "pairing_possible", "address"}`; `id` is ten characters of the digest of a session (a token is never stored nor shown). `POST /api/v1/devices/pairing-code` has the right `local`: the person in front of the machine only, never a paired device nor a remote administrator; it answers 201 `{code, valid_seconds, address, qr: {size, rows}}`, or `409 local_only` at the access level `local` (Lutin then listens on this machine only). `DELETE /api/v1/devices/{id}` and `DELETE /api/v1/devices` (right `configurator`) end sessions for real. The pairing itself (the code typed on the other device) is unchanged.

## Approval rules

`GET /api/v1/approval-rules` answers `{rules, project_rules, hardline}`; `POST` (`{"effect": "deny" | "ask" | "allow", "command"}`) and `DELETE /{id}` need the right `configurator`. See [ADR 0009](../adr/0009-approval-rules.md). The event `approval_request` carries `can_remember` for a command, and `POST /api/v1/approvals/{id}` takes `remember`: `once`, `chat` or `always` (`always` needs the right `configurator`).
A page opened again while a card waits (a reload, another device) reads the cards of the conversation with `GET /api/v1/conversations/{id}/approvals`: `{approvals: [...]}`, each the `approval_request` event the stream sent, and answers them the same way.

## Projects

A project is a working folder. `GET /api/v1/projects` answers `{"projects": [{"id", "name", "path", "usable", "problem"}], "current"}` (`usable` is false, with the reason in `problem`, for a folder that cannot be used now). `POST /api/v1/projects/{id}/select` makes one the current folder (any session; `409 workspace_conflict` while an answer is being written in another folder). Adding (`POST /api/v1/projects` with `{"path", "name"}`) and removing (`DELETE /api/v1/projects/{id}`, nothing in the folder is deleted; `?clean=1` also removes the copies of conversations Lutin wrote there) need the right `configurator`: the machine itself. `GET /api/v1/projects/folders?path=` (`configurator`, it shows the disk) lists the sub-folders of a folder, never files: `{"path", "parent" (null at the starting points), "folders": [{"name", "path"}], "truncated"}`; without `path` it answers the starting points (home, documents, drives).

## Scheduled tasks

A request Lutin carries out by itself. `GET /api/v1/scheduled-tasks` answers `{"tasks": [{id, name, request, time, days, date, project, notify, active, next_run, running, last_run_at, last_state, last_error, conversation, history}]}`; `days` are numbers with Monday as 0; `last_state` is `never`, `running`, `ok`, `failed`, `stopped` or `interrupted` (a run cut by a stop of Lutin); `history` keeps the ten last runs. Everything else needs the right `configurator`: `POST` (`name`, `request`, `time` as `HH:MM`, and `days` or a `date` for a single run; `project` and `notify` are optional) answers 201 with the task; `PATCH /{id}` takes any of those fields and `active` (false pauses it; changing the moment starts it again from now); `DELETE /{id}` (`?conversation=1` also deletes its conversation); `POST /{id}/run` (202, in the background; 409 `busy` while it works or two answers are already being written); `POST /{id}/stop` (refused with the reason when it is not at work).

## First launch

`GET /api/v1/setup` answers `{"done", "needed", "skipped"}`: `needed` says the guide of the first launch should be shown (the maintainer's rule: after the first installation on a new machine).
A machine counts as new only if **nothing** shows a past use: no flag of the guide, no conversation, no settings file, no installed model. The first two are cheap and decided before the engine is asked,
so an existing installation whose engine is only stopped for a moment never sees the guide. `POST /api/v1/setup/complete` (right `configurator`; `{"skipped": true}` when it was skipped) records that it is over.
The flag is the file `setup.json` of the data folder.

Three routes serve the end of the guide. `GET`/`PATCH /api/v1/language` (`{"language": "fr" | "en" | "auto"}`, answers `{language, choice}`; pages read the language when they load, so the caller loads the page again). `GET /api/v1/speed-test` and `POST /api/v1/speed-test` (202; refused with 409 `busy` during an answer, `model_missing`, `not_supported` for an engine other than Ollama): one short text written by the model; `state` `idle|running|done|failed`, then `tokens_per_second` and `level` (`slow|fair|comfortable|fast|very_fast`). The memory models may fill is the setting `memory_budget_gb` (0 = calculated from the machine), shown by `GET /machine` as `budget_gb` and `budget_set_gb`.

## Models

`GET /api/v1/models` gives what the model selector needs: `engine`, `running`, `current`, `models` (`[{"name", "size_bytes"}]`, the size may be null) and
`downloads` (`[{"name", "state", "done_bytes", "total_bytes", "text", "restart_engine_advised"}]`, state `downloading`, `done` or `failed`).
`POST /api/v1/models` with `{"name"}` starts a download and answers `202` with its state; `DELETE /api/v1/models/{name}` deletes a model and says which
one is now `current`. A name that contains `/` is percent-encoded in the path. In strict offline mode a download is refused with `409 offline`.

## Paired machines

Other computers running Lutin whose engine this one may use ([ADR 0016](../adr/0016-paired-machines-in-v1-and-the-new-interface.md); contract in
`tests/test_api_v1_machines.py`). `GET /api/v1/machines` (right `session`) answers `{"enabled", "answering", "machines", "log"}`: `enabled` is the
multi-machine mode, `answering` the machine of the setting `machine` ("" for this one), and each machine `{id, name, address, mac, mac_auto, added,
warnings, state, detail, step, shutdown_in_s, wake_failed, models, load, version, update_available, allowed {lead, update, shutdown}, requested, shares
{skills, memory}}`. `state` is `unknown`, `unreachable`, `wake_sent`, `reachable` or `operational`; `shutdown_in_s` the seconds left before a shutdown (null unless `step` is `shutting_down`); `step` the wake or shutdown sequence (`off`,
`waking`, `powered_on`, `lutin_started`, `syncing`, `ready`, `shutting_down`, `updating`) or null. The list never waits for the network: each machine
comes with its last known state and a stale one is probed again in the background (`unknown` until a first answer). A token never leaves.
`GET /api/v1/models` gives `remote`: `[{machine, machine_name, state, models}]`, the machines that answered in the last 40 s (empty while the
multi-machine mode is off).

The actions on a paired machine (stage 2, contract in `tests/test_api_v1_machine_actions.py`) all need `configurator`, as on the old Machines tab:
`POST /machines` `{address, code, name?, mac?}` pairs with the one-time code the other machine shows (`201` and the machine); `PATCH /machines/{id}`
`{mac}`; `DELETE /machines/{id}` unpairs (this machine answers again if it was the one of the setting `machine`) and answers `GET /machines`;
`POST /machines/{id}/actions/{action}` with `wake` (`202 {mac, sent, interfaces, warnings}`), `shutdown` (`202 {shutdown_in_s}`), `cancel-shutdown`
(`200 {cancelled}`) or `update` (`202 {}`); `POST /machines/{id}/rights-requests` `{right: lead | update | shutdown}` (`202 {right}`; the owner answers on
that machine); `POST /machines/{id}/imports/{skills | memory}` answers the counts (`{added, updated, already_there}`, or `{notes_added, notes_skipped,
profile_copied, profile_truncated}`). Who answers by default stays `PATCH /settings {machine}`. Refusals, each before any effect: `404 not_found`
(unknown machine), `400 invalid_request` (a value), `409 machine_refused` (the other machine said no: code refused, right not granted, nothing shared),
`503 machine_unreachable`, `502 machine_error` (it answered something unexpected).

This machine as a node, what it lends to the others (stage 3, contract in `tests/test_api_v1_node.py`). `GET /node` (`session`) answers `{lending, id,
shares {skills, memory}, allow {lead, update, shutdown}, pending_shutdown {in_s, by} | null, requests [{machine, right, date}], authorized [{name, date}],
startup {installed, possible, limits}}`. With the right `configurator`: `PATCH /node` `{lending}` (`409 local_only` to turn it on at the level « this
machine only »); `POST /node/pairing-code` (`201 {code, valid_seconds}`, the code another machine types in `POST /machines`; `409 not_lending` while
lending is off); `DELETE /node/authorized/{name}` (the machine's token stops working; `404` for an unknown name). With the right `local`, from this
machine only (a remote administrator is refused too): `PATCH /node/permissions` `{shares?, allow?, autostart?}` (everything is checked before anything
is written, autostart first since the system may refuse it); `POST /node/requests/{machine}/{right}` `{accept}` (accepting grants the right, refusing
forgets the request; `404` when it is no longer there); `POST /node/shutdown/cancel` (`{cancelled}`). These routes answer `GET /node`, except the code
and the cancel. The protocol between machines (`/api/noeud/*`) does not change.

Conversations led on another machine (stages 6 and 7, contract in `tests/test_api_v1_remote_conversations.py`), all `session` (the two
downloads `read`, like `GET /images/{id}`): this machine relays to the host's own legacy routes (`/api/noeud/relais/…`, only if the host grants
« lead ») and answers in the shapes of the local routes. `GET /machines/conversations` `{conversations: [{machine, machine_name, id, title,
updated_at, message_count}]}` (gathered in the background, none for a machine that stopped answering); `GET /machines/{id}/conversations/{c}`
(the shape of `GET /conversations/{id}`, plus `machine`); `POST …/turns` `{message, replace_from?, images?, attachments?}` (the host's stream,
each event translated; model, mode and approvals are the host's own); `POST …/stop`; `POST /machines/{id}/approvals/{approval}` `{approved,
restore_auto_approval?}` (`remember` only `once`: a lasting rule is the host's to set); `POST …/memory-choice`; `PATCH …` `{title?, pinned?}`;
`DELETE …`; `POST /machines/{id}/images` and `/attachments` (the host keeps the file) and `GET /machines/{id}/images/{image}`,
`/attachments/{attachment}?name=`. Refusals: `404 not_found` (machine or conversation), `403 machine_refused` (the host does not grant « lead »,
its sentence passed on), `409 conflict`, `503 machine_unreachable`, `502 machine_error`, `400 invalid_request` before anything reaches the host.

## Lutin's own version

`GET /status` carries `new_version` (`{version, page, command}` when the check made at launch, at most once a day, found a newer release that was
not ignored; null otherwise; read from the cache, never the network) and `restart` (`{needed, possible}`: `needed` when the access level saved
differs from the running one, a backup was put back, or an update was installed with nothing to restart Lutin; `possible` when a supervisor
starts it again). `POST /lutin/check` (session) asks GitHub now: `{current, latest, new_version}`, `503 unreachable`, `409 not_available` when
the launch keeps no version cache. `POST /lutin/ignored-version` `{version}` (session). `POST /lutin/update` (configurator) starts what
`lutin update --app` does, in the background; `GET /lutin/update` (session) follows it: `{state, lines, before, after, command, can_update,
can_check, can_restart}`, `state` one of `idle`, `running`, `failed`, `up_to_date`, `restarting`, `installed`. Refusals: `409 in_docker` (the
image is replaced instead), `offline`, `turn_running`, `update_running`. `POST /lutin/restart` (configurator): `{restarting: true}`, then Lutin
stops with the code its supervisor restarts; `409 cannot_restart`, `turn_running`.

## Strict offline mode

`GET /offline` (session): `{active, forced, can_turn_off, allowed_hosts, blocks}`; `GET /status` carries `offline` as before. `POST /offline`
(session) turns it on: it only takes something away. `DELETE /offline` (configurator) turns it off, from this machine only, as on the old page.
Refusals: `409 forced` (LUTIN_HORS_LIGNE=1 keeps it on for the launch), `409 not_available` (no configuration file to keep it in).

## Web search

`GET /web-search` (session): `{searxng, keys: [{provider, kept, ends_with}], engines: [{id, configured, paused_s, at_home}], can_configure,
offline}`; a key is never sent back, only its last four characters. `engines` is the order in which they are tried (the ones set up first,
then DuckDuckGo and Bing). `PATCH /web-search` (configurator) `{searxng?, keys?: {brave?, tavily?, exa?, perplexity?}}` ("" removes);
`400 invalid_request` for an address or key that cannot be one. `POST /web-search/test` (session) asks each engine separately:
`{results: [{id, ok, count, ms, error, example}]}`; `409 offline`.

## Access

`GET /access` (session): `{level, port, public_url, proxy_ips, saved: {level, public_url, proxy_ips}, restart_needed, address, docker, can_change,
can_restart, remote_admin: {active, can_change}, levels: [{id, title, detail}], warnings: {network, proxy}}`. `PATCH /access` (local)
`{level, understood, public_url?, proxy_ips?}` saves the level for the next start (opening needs `understood: true`). `PATCH
/access/remote-admin` (local) `{active}`. Both are `local`, stricter than the old page's level route: they open the machine, so neither a paired
device nor the remote administration itself may change them. Refusals: `400 invalid_request`, `409 in_docker` (LUTIN_NIVEAU, LUTIN_ADMIN_TOUS).

## Model upkeep

`GET /models/proposals` (session, from the cache, never the network): `{proposals: [{key, kind: update | new | obsolete, model, role, replaces,
replaced_by, size_gb, summary, reason}], errors, checked_at, catalogue}`. `POST /models/check` `{scope: updates | new | all}` checks now (`409
not_available` without a checker). `POST /models/proposals/{key}/applied` (installed: for a role, the model becomes the one chosen) and `DELETE
/models/proposals/{key}` (not proposed again); `404 not_found`. Nothing is installed or deleted by these: the page calls `POST /models` or `DELETE
/models/{name}`. `GET /models/variants?model=` and `GET /models/library?q=&order=&page=&capability=&light=` read ollama.com and judge each size for
this machine (`fit`); `503 unreachable`, `409 offline`.

## Measures and managed servers

`GET /bench` (session): `{running, step, queue, error, results: [{model, date, complete, machine, engine, error, speed: {tokens_per_s, load_s,
reading_tokens_per_s}, tests: {tools|code|french|instructions: {points, out_of, details: [{test, ok}]}}, grades}], regressions: [{model, kind,
before, after, engine_changed}], history}`. `POST /bench` (session) `{models: [1 to 8], quick}`: 202; `409 busy`. `GET /engines/comparison`
(session): `{model, outdated, comparable, availability, running, step, error, recommendation, result: {date, mode, engines: [{id, name, model,
ok, errors, load_s, first_token_s, tokens_per_s, reading_tokens_per_s, ram_bytes, vram_bytes}], skipped}}`; `POST /engines/comparison`
(configurator) `{mode: quick | deep}`: 202, `409 busy`.

**The models of any engine, in the same way** (ADR 0020, stage 2), with `{id}` any engine of `GET /engines`; `409 not_chosen` when it is not the engine in use:
`GET /engines/{id}/models` (installed), `…/models/recommended` (what this machine runs well, the largest first, at most five), `…/models/search?q=&page=` (the
catalogue of Lutin, then the library of the engine: ollama.com, Hugging Face, the catalogue of the server; `more` says whether another page follows),
`…/models/variants?ref=` (the precisions of one model: quantisations, files), `POST …/models/check {scope: updates | new}` (the newer versions of what ExLlamaV3
downloaded, or new models that fit this machine, for the servers Lutin manages: `{models, errors}`; `400 action_impossible` for Ollama and llama.cpp, which have the
proposals of `POST /models/check`) (session); `POST …/models/downloads {ref, revision?, confirm: true}` (202) and `DELETE …/models/{name}` (configurator). The search
also reads `order=recent|popular` and `community=1` (ExLlamaV3, LM Studio) and `capability=tools|vision|thinking` (Ollama). A list whose catalogue cannot be read
answers `502 unreachable`. Every model, whatever the engine and the list, is one entry: `{id, name, revision, size_gb, approximate, fit: {level, text}
| null, installed, in_use, summary, download: {possible, reason}, has_variants, incomplete, removable}`. `id` is the name to give to « download »; `revision` the precision to take with it;
`download.reason` says why a model cannot be downloaded (too big for this machine, offline, a format the engine cannot read, already here); `incomplete` is a
download that stopped halfway; `removable` is false for a model Lutin did not put there (`DELETE` answers `400`) and for the models of a server reached by its address. A server reached by its
address (`openai`) lists the models it serves and downloads nothing (`400 action_impossible`). In strict offline mode the search gives the catalogue of Lutin only
(nothing is asked of ollama.com or Hugging Face), and `variants` and `downloads` answer `409 offline`. The older families `/managed-servers/{id}/*` and
`/engines/{id}/library*` were removed at stage 4 (2026-11-22).

## GitHub account

`GET /github` (session): `{github: {configured, source: environment | settings}, offline}`, never the token. `PATCH /github` `{token}` ("" removes
it) and `POST /github/test` (configurator). The account is Lutin's (engines' new versions, its own update, third-party skills), so these routes
left `/third-party-skills/github`.

## Engine settings, folders and tuning

`GET /engines/{id}/settings` (session): `{engine, address_changeable, url, key_set, variant, folder, server, advanced, managed_installed,
colibri?, lmstudio?, exllamav3?}`, never the key. `PATCH /engines/{id}/settings` (configurator) with any of `url, key, variant, router,
models_kept, cpu_moe_layers, pinned_version, install_folder, models_folder, server, colibri_model, colibri_port, lmstudio_port, exllamav3_port`.
`GET`/`PATCH /engines/folder` `{path}`. `GET /engines/measures`, `POST /engines/{id}/measure {model, mode}` (configurator, 202, `409 busy`).
`GET /models/folder`, `POST /models/folder/analysis {path}`, `POST /models/folder/copy {path}` (202), `PATCH /models/folder {path}`, `POST
/models/folder/restart-ollama` (configurator but the first). `GET /calibration`, `POST` (202), `DELETE`, `POST /calibration/apply`. `GET
/machine/advice` `{advice: [{setting, current, advised, text}], dismissed}`, `POST /machine/advice/apply` and `/dismiss`.

## Conversation tools, Git and the actions log

`GET /conversations/{id}/memory` (session): `{mode, own_mode, general_mode, sections, text, measure, first_request}` (`mode` and `general_mode` always `sheet`, `own_mode` null since ADR 0019).
`PATCH …/memory` `{mode?: summary | sheet | null, sheet?: text}` (`mode` accepted and without effect since ADR 0019); `DELETE …/memory/sheet`; `409 turn_running`. `POST …/handover`: `{text,
model}`, `503 engine_unreachable`. `GET …/folders` and `POST …/folders/open {path}` (configurator, `409 cannot_open`). `GET /git` (session):
`{available, reason, branch, files: [{path, state}], total}`; `POST /git/message {files}` (session); `POST /git/commit {message, files}`
(configurator; never a push). `GET /actions-log?n=` (session): `{entries: [{at, conversation, folder, tool, target, outcome, approval, who}]}`.

## Background work

`GET /background-jobs` (session): `{jobs: [{id, name, folder, patterns, instruction, regular, interval_hours, paused, validated, state: waiting
| running | to_validate | done | failed | paused, total, done, failed, message, has_report}]}`. `POST /background-jobs` `{name, folder, patterns,
instruction, regular?, interval_hours?, trial?}` (configurator, 201), `POST /background-jobs/{id}/{pause | resume | restart | validate}` and
`DELETE /background-jobs/{id}` (configurator), `GET /background-jobs/{id}/report` (session): `{text}`.

## Documents, notes and the search by meaning

`GET /documents` (session): `{folders, formats, files: [{name, passages}], errors, max}`; `GET /documents/search?q=`: `{passages: [{source,
title, extract, conversation}]}`, `400` for vague words. `GET /notes`: `{notes: [{line, date, text}]}`; `POST /notes {text}` (201); `DELETE
/notes?line=` (`404 not_found`). `GET /search-by-meaning`: `{active, model, installed, installation: {state, done_bytes, total_bytes, error}}`;
`POST /search-by-meaning/install` (configurator, 202, `409 offline`).

## Slash commands

`POST /conversations/{id}/compact` (session): `{before, after, sheet}`, `409 turn_running`. `GET /project-commands`: `{commands: [{name,
description}]}` (the `.claude/commands` of the work folder); `GET /project-commands/{name}?args=`: `{text}`, the message the command makes
(`404 not_found`). The other commands are carried out by the page with the routes it already has.

## Created files and locations

`GET /created-files` (configurator), `?conversation=<id>` for the files of one conversation: `{files: [{id, kind, name, path, size_bytes, date, conversation, conversation_exists}], total_bytes}`;
`POST /created-files/delete {ids}`: `{deleted, freed_bytes, skipped}`; `POST /created-files/{id}/open-folder` (`409 cannot_open`). `GET
/locations` (configurator): `{locations: [{key, name, path, explanation, exists, size_bytes, disk: {free, total, root}}], data_detail}`.

## Last gaps

`POST /mcp-connectors/demo` (configurator, 201). `GET /helper-programs` (session): `{programs: [{name, label, help, installed, by_lutin,
version}]}`; `POST /helper-programs/{name}/install` (`409 offline`) and `DELETE /helper-programs/{name}` (configurator). `PATCH
/conversations/{id}/messages/{index}` `{pinned}`: `{pinned, count}`. `POST /web-search/preview` `{q}` (session): `{query, removed, reasons,
results: [{title, url, extract, date, source, domain}]}`, never sent to the model; `409 offline`.

## What v1 keeps

- The security model, unchanged: Host and Origin checks, page token on every `/api/` request, session by PIN pairing, approvals.
- Stored data is not touched by v1: it is a second door to the same state. The storage migration is a separate piece of step 3.
- Files (`/image/`, `/piece/`, `/fichier/`, `/ouvrir/`) move under `/api/v1/files/…` with the same sandboxing headers.

## Order of work

1. Route table and dispatcher in the server (declared rights, error codes), serving the existing French routes first: no behaviour change, proven by the two contract tests.
2. `/api/v1` routes added to the table, one area at a time, each with contract tests on its fields (request, answer, errors).
   Order follows the screens of the new interface: status and settings, conversations and the stream, models and engines, then the rest.
3. The old routes are removed when the old page is: done at 1.0 (ADR 0022), but for the sign-in, the protocol between machines and the eleven
   routes of its relay, reached only through `/api/noeud/relais`.

## Open points

- Field-by-field description of the 184 routes: produced area by area in step 2 of the order above, not in advance.
- Whether paired machines keep a French-named protocol during a transition (they can only talk to the same version today): to decide when `/node/v1` is written.
