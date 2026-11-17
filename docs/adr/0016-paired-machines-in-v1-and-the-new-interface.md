# ADR 0016 — Paired machines in `/api/v1` and in the new interface

Status: **proposed**, to be validated by the maintainer before any code (plan step 4: « the models of other machines », the last missing piece of
the Models screen; « conversations led on another machine » is left to a later decision, see below).

## Context

A paired machine is another computer running Lutin whose engine this one may use (glossary: *machine*, *node*). The mechanism exists and is well
tested (about 125 tests: `test_machines`, `test_machines_distantes`, `test_partage_machines`, `test_partage_moteur`, `test_reveil`, `test_alimentation`,
`test_machines_navigateur`): pairing by a one-time code, four states (`injoignable`, `reveil_envoye`, `joignable`, `operationnel`) and a five-step wake
sequence, routing of a turn to the node with a silent local fallback (`machines.Routage`), rights a node grants (lead a conversation, update, shut down),
sharing of skills and memory, Wake-on-LAN. Read on `96009ca`:

- **Nothing of it is in `/api/v1`.** `/devices` is about phones and browser sessions, `GET /machine` about this computer's hardware. `GET /models` lists
  local models only, and the body of a turn has no `machine` field: the new Chat cannot make another machine answer, except through the setting
  `machine` (`PATCH /settings`), which changes it for every conversation.
- **The old page** has a Machines tab (`index.html` 4036-4257) built on `GET /api/machines` and twenty actions `POST /api/machines-<action>`, and a
  model selector that groups the models of operational machines (`ETAT.modeles_distants`) under the machine's name.
- **Two levels of right are used**: most actions need `configurator`; seven need the stricter rule « from this machine itself » (`_configurateur_strict`,
  v1 `LOCAL`): answering a rights request, allowing shutdown, update or leading, cancelling a local shutdown, autostart, sharing skills or memory.
  `GET /api/machines` has no right of its own: a paired phone can read the list, with the addresses.
- **`machines.etats()` probes every machine on a cache miss**, synchronously (1.5 s each, 3 s during a wake): a page that asks every few seconds may
  wait several seconds when a machine is off.

## Decision (proposed)

1. **Routes, in English, rights declared in the table** (`api_v1.ROUTES`), the logic staying in `lutin.machines` (as the engines routes did):

   | Route | Right | Does |
   |---|---|---|
   | `GET /machines` | `session` | `{"enabled", "answering", "machines": [...], "log"}`: each machine with `id, name, address, mac, mac_auto, added, warnings, state, detail, step, shutdown_in_s, wake_failed, models, load, version, update_available, allowed {lead, update, shutdown}, requested [], shares {skills, memory}` (the fields of `vue` and `sonder`, renamed, never the token) |
   | `POST /machines` | `configurator` | pair a machine: `{address, code, name?, mac?}` → `201` and the machine |
   | `PATCH /machines/{id}` | `configurator` | `{mac}` |
   | `DELETE /machines/{id}` | `configurator` | unpair (clears the setting `machine` if it was this one) |
   | `POST /machines/{id}/actions/{action}` | `configurator` | `wake`, `shutdown`, `cancel-shutdown`, `update` (the pattern of `/engines/{id}/actions/{action}`) |
   | `POST /machines/{id}/rights-requests` | `configurator` | `{right: lead \| update \| shutdown}` |
   | `POST /machines/{id}/imports/{kind}` | `configurator` | `skills` or `memory`, with the counts the old route gives |
   | `GET /node` | `session` | this machine as a node: `{lending, id, shares, allow {shutdown, update, lead}, pending_shutdown, requests, authorized, startup}` |
   | `PATCH /node` | `configurator` | `{lending}` (refused at the level « this machine only », as today) |
   | `PATCH /node/permissions` | `local` | `{shares?, allow?, autostart?}`: what this machine grants, from this machine only |
   | `POST /node/pairing-code` | `configurator` | a code for another machine to pair with this one |
   | `DELETE /node/authorized/{name}` | `configurator` | revoke a machine that may use this one |
   | `POST /node/requests/{machine}/{right}` | `local` | `{accept}`: answer a rights request |
   | `POST /node/shutdown/cancel` | `local` | cancel a shutdown asked by another machine |

   The rights are those of the old routes, with the split between `configurator` and `local` read in the code, not changed. Turning the multi-machine
   mode on and off stays `PATCH /settings {cluster}`; who answers by default stays `PATCH /settings {machine}`.
2. **The model of another machine, per turn**: `GET /models` gains `remote: [{machine, machine_name, state, models}]` (from `modeles_distants`, the
   machines operational and probed in the last 40 s), and the body of a turn gains `machine` (an unknown id falls back to this machine, as the old route
   does; a relayed request still cannot set it). The new Chat's selector shows the models of each machine under its name.
3. **`GET /machines` does not wait for the network**: it answers from the probe cache and starts a refresh in the background when an entry is stale;
   a machine not probed yet says `state: "unknown"`. The old route keeps its synchronous behaviour until the old page goes.
4. **In the new interface**:
   - **Models screen, a « Machines » tab** (shown when the multi-machine mode is on, with a button to turn it on otherwise): who answers, one card per
     machine (state, wake sequence, wake / shut down / update, rights granted and the button to ask for one, details: load, MAC address, imports,
     unpair), the form to pair a machine, the log.
   - **Settings, a « Lend this machine » group**: lending on or off, pairing code, authorized machines and revoke, what is shared and allowed,
     autostart, a pending shutdown; the rights requests waiting for an answer, with a badge on Settings as on the old page.
   - **Chat**: the model selector groups the models of operational machines; a machine that went off is shown as such.
5. **The machine-to-machine protocol (`/api/noeud/*`) does not change**: its English, versioned form (`/node/v1`) belongs to step 3, because two machines
   may run different versions.

## Stages (one commit each)

1. `GET /machines`, `GET /models` with `remote`, `machine` in the turn body; contract and access tests against a fake node (the helpers of
   `test_machines`), fixture `tests/fixtures/api_v1_routes.json` regenerated.
2. The action routes on machines (pair, unpair, MAC, actions, rights requests, imports).
3. The node routes (`/node`…).
4. The Machines tab of the Models screen and the Chat selector; unit tests, a Chrome test with axe against a loopback node (as `test_machines_navigateur`).
5. The « Lend this machine » group in Settings, with its Chrome test.

## Not chosen

- **One `POST /machines/{id}/actions/{action}` for everything, the node settings included**: the rights differ (`configurator` against `local`), and a
  right is declared per route, never checked in the body.
- **A screen of its own for machines**: the shell has five areas; machines serve models (Models) and this machine's lending is a setting (Settings).
- **Keeping the synchronous probe in v1**: a page that polls would freeze for seconds whenever a machine is off.

## Way back

Each stage is one commit; the old page and its routes are untouched until parity, so reverting a stage only removes the new routes or screens.

## Questions for the maintainer

- Lending this machine in Settings, and the paired machines in the Models screen: is that where you look for them?
- Today a paired phone can read the list of machines with their addresses. Keep it (proposed: yes, the phone shows who answers), or keep the list for
  the configurator?
- « Conversations led on another machine » (read and continue on this page a conversation hosted by a paired machine): in this work, or a next step?
