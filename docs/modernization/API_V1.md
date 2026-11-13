# `/api/v1`: design

The contract the new interface will be built on ([ADR 0001](../adr/0001-english-and-clean-break-at-1.0.md), [ADR 0002](../adr/0002-frontend-svelte-typescript-vite.md)).
This page fixes the rules; it is not implemented yet. The present contract — 184 exact routes, 17 prefixes, 15 stream events, the right each route asks —
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
   `local_only`, `node_right`), `404` unknown, `409` conflicts with a running turn, `413` too large, `429` too many attempts, `503` engine unavailable.
5. **Rights are declared, not scattered.** Each route of the table states one of: `public`, `session`, `configurator`, `local`, `node`. The check is done once,
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

   Three event types the page handles are produced elsewhere than by a literal `emit` and are not in the inventory: token counts, speed, and a retry notice.
   They are to be listed when the stream is specified field by field.
7. **Versioning.** `/api/v1` only ever gains optional fields and new routes. A change that breaks a client is `/api/v2`. The page and the server ship together,
   so the page never talks to a server of another version; the rule protects scripts and paired machines.
8. **Machine-to-machine protocol** (`/api/noeud/*` today): versioned separately (`/node/v1`), because two machines may run different versions of Lutin.
   A node states its protocol version in its status; an older or newer peer gets a clear refusal, not a malformed exchange.
9. **No route does two things depending on a missing field.** Thirteen routes today check the configurator right only for some inputs; in v1 each becomes
   two routes or one route with one rule.

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
