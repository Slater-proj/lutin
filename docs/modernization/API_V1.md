# `/api/v1`: design

The contract the new interface will be built on ([ADR 0001](../adr/0001-english-and-clean-break-at-1.0.md), [ADR 0002](../adr/0002-frontend-svelte-typescript-vite.md)).
This page fixes the rules. Implemented so far (`src/lutin/api_v1.py`, contract in `tests/test_api_v1.py` and `tests/fixtures/api_v1_routes.json`): the dispatcher with declared rights and coded errors, `GET /status`, the settings (read, change), the conversations (list, create, read, rename/pin, delete, stop), the turn stream and the answer to an approval, the options of a conversation, the models (list, install, delete). Not yet: engines and everything else. The present contract — 184 exact routes, 17 prefixes, 15 stream events, the right each route asks —
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
   | `choix_memoire` | `memory_choice` | the conversation is long: summarise or keep in a file |
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
   `409 turn_running` or `workspace_conflict`, `429 too_many_turns`. `memory_choice` is answered with `POST /api/v1/conversations/{id}/memory-choice`
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
  (`always`, `first`), `long_memory` (`summary`, `file`, `ask`), `auto_recall` (`scenario`, `always`, `never`). The mission mode is not a setting:
  it is chosen conversation by conversation. Tool names (`disabled_tools`) are what the models see and are not translated (ADR 0007).
- A write is all or nothing: an unknown name or a value of the wrong kind answers `400 invalid_request` and nothing is stored. Values are then checked
  and bounded by the function the French route calls (a dangerous command in `commands_without_approval` is refused, `max_steps` is kept within 4-40…).

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

`GET /api/v1/engines` gives every engine (Ollama, llama.cpp, servers compatible with OpenAI…): `id`, `name`, `kind`, `current`, `installed`, `running`, `version`, `models_count`, strengths and weaknesses,
the six `actions` (`install`, `uninstall`, `reinstall`, `start`, `stop`, `update`), each with `possible` and the `reason` (what it does, or why it cannot), and the `task` in progress
(`state`: `running`, `done` or `failed`; `text`, `done`, `total`, `error`). The engines are read at the same time and, for each, its three questions too: one that does not answer costs one wait of 2 s for the whole list, not three per engine.
`POST /api/v1/engines/{id}/actions/{action}` (right `configurator`) starts an action in the background and answers `202` with the task. **What changes the machine (install, uninstall, reinstall, update) needs
`{"confirm": true}`**: without it the answer is `400 confirmation_required` carrying what the action does, so that a client has to show it and have it accepted. What needs the network is refused in strict offline mode
(`409 offline`); an action the engine does not allow is `400 action_impossible` with its reason; a second task on the same engine is `409 task_running`.
`DELETE /api/v1/engines/{id}/task` asks the running task to stop (what was downloaded is kept). It is the machinery of the present page (`lutin.engines`), under English names.
Not in v1 yet: the settings of an engine (address, key, folders, variant) and the catalogue of external servers.

## Devices and pairing

`GET /api/v1/devices` answers `{"devices": [{id, name, paired_at, seen_at}], "level", "pairing_possible", "address"}`; `id` is ten characters of the digest of a session (a token is never stored nor shown). `POST /api/v1/devices/pairing-code` has the right `local`: the person in front of the machine only, never a paired device nor a remote administrator; it answers 201 `{code, valid_seconds, address, qr: {size, rows}}`, or `409 local_only` at the access level `local` (Lutin then listens on this machine only). `DELETE /api/v1/devices/{id}` and `DELETE /api/v1/devices` (right `configurator`) end sessions for real. The pairing itself (the code typed on the other device) is unchanged.

## Approval rules

`GET /api/v1/approval-rules` answers `{rules, project_rules, hardline}`; `POST` (`{"effect": "deny" | "ask" | "allow", "command"}`) and `DELETE /{id}` need the right `configurator`. See [ADR 0009](../adr/0009-approval-rules.md). The event `approval_request` carries `can_remember` for a command, and `POST /api/v1/approvals/{id}` takes `remember`: `once`, `chat` or `always` (`always` needs the right `configurator`).

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

## What v1 keeps

- The security model, unchanged: Host and Origin checks, page token on every `/api/` request, session by PIN pairing, approvals.
- Stored data is not touched by v1: it is a second door to the same state. The storage migration is a separate piece of step 3.
- Files (`/image/`, `/piece/`, `/fichier/`, `/ouvrir/`) move under `/api/v1/files/…` with the same sandboxing headers.

## Order of work

1. Route table and dispatcher in the server (declared rights, error codes), serving the existing French routes first: no behaviour change, proven by the two contract tests.
2. `/api/v1` routes added to the table, one area at a time, each with contract tests on its fields (request, answer, errors).
   Order follows the screens of the new interface: status and settings, conversations and the stream, models and engines, then the rest.
3. The old routes are removed when the old page is.

## Open points

- Field-by-field description of the 184 routes: produced area by area in step 2 of the order above, not in advance.
- Whether paired machines keep a French-named protocol during a transition (they can only talk to the same version today): to decide when `/node/v1` is written.
