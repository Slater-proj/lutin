# Modernization plan

From the Phase A audit (2026-11-11) and the decisions recorded in [../adr/](../adr/README.md). One step at a time; a step starts when the maintainer has validated the previous one.
Sizes are relative (S, M, L, XL), not durations.

## Rules for every step

- Work happens on the `modernization` branch, in small commits with one intention each. Nothing is pushed or merged without the maintainer.
- `modernization` carries `tools/release_channel.json` (alpha, target 1.0.0): if it reaches `main`, what is published is a pre-release `1.0.0aN`, never `:latest` (ADR 0004). Merging stays the maintainer's decision.
- No user data is modified, no destructive migration is run, outside the versioned migration of step 3.
- A step is done when: its acceptance criteria below are met; the full suite passes (`python tests/lancer_tests.py`) and `ruff check src tests tools` is clean;
  the documentation is updated; the residual risks are written down; the way back is stated.
- A test that fails is fixed or reported, never skipped or loosened to pass.

## Steps

| # | Step | Size | State |
|---|---|---|---|
| 0 | Baseline: reproducible test run, hermetic tests, contract inventory, ADRs | S | Done — [BASELINE.md](BASELINE.md) |
| 1 | Security and reliability | S/M | Done except update signing and installer signing, which need the maintainer (below) |
| 2 | HTTP contract: schemas and contract tests, design of `/api/v1` | M | Access contract and design done ([API_V1.md](API_V1.md)); v1 started: dispatcher, status, conversations, the turn stream, approvals (9 routes, `src/lutin/api_v1.py`). Next: settings, models and engines |
| 3 | English: catalogues inverted, identifiers and modules renamed, data migration | L | Glossary and module names done ([GLOSSARY.md](GLOSSARY.md)); the rest not started |
| 4 | Interface: foundation and design system, then screen by screen on `/api/v1` | XL | Not started |
| 5 | Backend, targeted: route table, application context, agent loop split | L | Not started |
| 6 | Retained differentiators: model router, projects, monitoring | M each | Not started |

### Step 1 — Security and reliability

Done:

- Approval-free commands no longer go through a shell (ADR 0006).
- Outbound web requests: pinned address, redirections checked hop by hop, carrier-grade NAT refused, test switch needing two variables (ADR 0008).
- `docs/SECURITY_AUDIT.md` corrected: it stated that no command ran through a shell.

Remaining, each its own commit:

1. **Update authenticity** (M). `SHA256SUMS.txt` sits next to the wheel: it proves integrity, not origin. Sign it with the Ed25519 mechanism already used for the
   engine catalogue; refuse an unsigned release from a given version on. Needs a key ceremony by the maintainer.
2. ~~Release workflow~~ — done: release channel and pre-releases (ADR 0004, [PUBLISHING.md](../PUBLISHING.md)).
3. **Windows installer signing** (decision already recorded as postponed in DECISIONS.md): to reconsider before 1.0, it conditions adoption by beginners.
4. **Security review of what the audit did not cover** (M) — partly done (2026-11-13). Read, nothing to fix: backup restore (`backup.py`: names checked against a closed list,
   links and oversize refused, previous state kept), installation of third-party skills (`third_party_skills.installer`: paths checked, never executed, danger and licence confirmed),
   the relay whitelist (`server._relais`: closed list of routes, no access-changing route), document extraction limits, upload names (random identifiers).
   One documentation error found and corrected: SECURITY_AUDIT stated a paired machine can never read files; the optional « lead conversations » right lets it run and approve actions.
   **Still not read in depth**: the rest of `machines.py` (pairing, probes, wake-up, imports), the MCP client (`mcp.py`), the add-on modules, `open_file.py`.
5. **Logic tied to message text** (S): `server.py` recognises a refusal by the French words « cette machine »; replace by an error code. Fits naturally in step 2.
6. ~~Add-on downloads~~ — not retained: `addons_comfyui` only downloads over HTTPS from a fixed list of hosts (Hugging Face, Civitai) and controls each redirection against that list; pinning the address adds nothing there.

Acceptance: each audit finding has a test that failed before the fix and passes after; no finding is closed by documentation alone, except where the decision is to accept the risk, written in SECURITY.md.

### Step 2 — HTTP contract

Done:

- The inventory records the right each route asks; `tests/test_api_access.py` calls every route for real, without a session and as a paired device (184 exact routes, 17 prefixes; no defect found).
- The design of `/api/v1`: [API_V1.md](API_V1.md) — English names, resources, error codes instead of sentences, declared rights, the same NDJSON stream with English event names, a versioned node protocol.

Remaining, with the implementation of v1 (it needs the route table of step 5, brought forward for that purpose):

- Fields in, fields out and errors of each route, area by area, with contract tests run against the real server.

Acceptance: every v1 route has a contract test on its fields; a field renamed in the server fails a contract test. The access test reads the route table instead of the source.

### Step 3 — English

Order matters, to touch each file once:

1. ~~Glossary~~ — done: [GLOSSARY.md](GLOSSARY.md). It was not submitted for validation term by term: the maintainer asked for the plan to be carried out without stopping. Any term can still be changed by a mechanical commit.
2. Catalogues inverted by script: the English sentence becomes the key, `messages.fr.json` and `interface.fr.json` are generated. `tests/test_langue.py` already guarantees every sentence is translated, so the inversion is total.
3. Feature freeze starts (ADR 0003).
4. ~~Modules renamed~~ — done: 76 modules, one mechanical commit, contents unchanged, package kept flat (moving into sub-packages is left to step 5, when responsibilities are actually separated: a deviation from the first version of this plan, which wanted both at once). Then identifiers, module by module, with a syntax-tree tool; then comments and docstrings; then the test file names.
5. Environment variables: English names, old names read as aliases through one function.
6. Data migration 0.x → 1.0: versioned schema for every stored file, backup first, idempotent, tested on data written by 0.50.

Acceptance: the full suite passes after each renaming commit; a search for French identifiers in `src/` returns only the catalogue and the alias table;
data written by 0.50.3 opens after migration, and the backup restores it under 0.50.3.

Way back: every renaming commit is mechanical and reverts cleanly; the data migration keeps its backup.

### Step 4 — Interface

- Foundation: project layout, build integrated to the wheel, design tokens, light and dark themes, the base components, the five areas (Chat, Agents, Projects, Models, Settings).
- Then one screen at a time, each with its end-to-end tests, starting with Chat.
- Onboarding: hardware detection, a recommended configuration with its size and compatibility explained, confirmation before any download.

Acceptance, per screen: functional parity with the old page listed and checked; keyboard-only use possible; automated accessibility checks clean (target WCAG 2.2 AA);
usable at 360 px wide; works with the network cable unplugged. The old page is removed only when every screen is accepted.

Way back: the old page stays the default until parity (ADR 0002).

### Step 5 — Backend, targeted

Only what the earlier steps showed to hurt: a route table in place of the two `if` chains, an explicit application context in place of module-level state
(which is why each test file needs its own process today), the agent loop split into context building, model call, tool dispatch, approval and persistence, with explicit task states.

Acceptance: test files can share a process; no behaviour change (the contract tests of step 2 and the end-to-end tests of step 4 are the proof).

### Step 6 — Differentiators

Each starts with a short study of use and a prototype (ADR 0003 lists what is retained, deferred and dropped).

## Global rollback

- Code: `main` and the 0.50.x line are untouched by this work; abandoning the migration is deleting the branch.
- A single step: `git revert` of its commits; each step states anything beyond that.
- Installed versions: `lutin update --rollback-to X.Y.Z` reinstalls a published version; a backup is written before every update.
- Data: untouched before step 3; from step 3 on, the migration's backup.
