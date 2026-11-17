# ADR 0014 — One application context holds what the modules kept for themselves

Status: **proposed**, to be validated by the maintainer before any code (plan step 5, item 1). Scope decided on 2026-11-17: the application context
only. The route table is left out: the French routes go away with the old page, and `/api/v1` already has its table (`api_v1.ROUTES`).

## Context

Plan step 5, item 1 asks for « an explicit application context in place of module-level state (which is why each test file needs its own process
today) », and its acceptance says « test files can share a process ». Counted on `cf30e93`:

- **The configuration is read from the environment when a module is imported.** `core.py` reads `LUTIN_RACINE`, `LUTIN_DONNEES`, `LUTIN_MEMOIRE`,
  `OLLAMA_URL`, `LUTIN_OUTIL_URL`, `LUTIN_PORT`, `LUTIN_CATALOGUE`, `LUTIN_MODELE`, `LUTIN_SANS_GARDE` and `LUTIN_SANS_DEMARRAGE` at import;
  `web.py` and `web_search.py` read five search addresses the same way. A second test file that sets other values after the first one imported Lutin
  gets the first one's. These names are used as module attributes across the code (`_m.RACINE` 56 times in `src`, `DONNEES` 80, `OLLAMA` 25,
  `SECURITE` 22) and written by the tests (`SECURITE` 24 times, `OLLAMA` 16, `RACINE` 5, `DONNEES` 5). No module imports them by value
  (`from .core import RACINE`): every use goes through the module, which leaves room for an indirection.
- **About 109 registries, caches and locks live at module level, in some 45 modules**: the running turns (`core.TOURS_ACTIFS`, written by six
  modules: the page, the scheduled tasks, the missions, Telegram, the automatic replies, `core`), the turn records (`turn_state`), the project map,
  the recall index, the probes of the machines, the engines and their servers, MCP connections, add-on threads, web caches. Nothing lists them, nothing
  empties them: a test file inherits what the previous one left.
- **Some modules start threads** (add-ons, background jobs, the scheduler, the machine watcher, the MCP watcher) that outlive what started them.
- **The tests do their own setup at import**: 131 of 158 files import `tests/context.py` (which sets the environment and patches `tempfile`),
  11 set the environment at module level, 32 start fake servers at module level.
- **The cost of a process is small**: importing `lutin.core`, `lutin.agent` and `lutin.api_v1` (93 modules) takes 0.46 to 0.55 s on this machine
  (three runs), about 80 s for 158 files in a suite of 10 to 25 minutes. Speed is not the reason for this item. The reasons are: one place that reads
  the environment, a known list of what a running Lutin holds, isolation between test files that does not depend on a process, and a home for the
  registry of running turns that a single `run_turn` needs (ADR 0012, « Not done yet »).

## Decision (proposed)

1. **`src/lutin/app_context.py` defines `AppContext`**, made of:
   - `settings`: what is read from the environment, **read once**, by `AppContext.from_env(environ)` and nowhere else (the root of the work, the data and
     memory folders, the engine and tool addresses, the port, the catalogue, the default model, the two test switches, the search addresses). The English
     aliases of the environment variables planned for step 3 are added here, in one place.
   - `secrets` and `security`: the two tokens, `Securite`, `Appareils`, the PIN limiter, the LAN address, the model checker (today replaced by the launcher
     before the server starts).
   - `turns`: the registry of running turns with its lock, the root used by each turn, the background tasks shown in the status bar.
   - a list of **registered parts**: `register(name, reset=..., close=...)`.
2. **One context per process at a time**, held in a module-level slot: `app_context.current()`, `install(ctx)`, and `scope(ctx)` for tests (installs,
   then closes and restores). Not a `ContextVar`: the server answers each request in a new thread, and a new thread does not start in the context of the
   thread that created it on the usual build of Python. Two test files can share a process one after the other, not at the same time.
3. **The names stay, they read through the context.** `core` (and `web`, `web_search`) give their module a class with properties
   (`sys.modules[__name__].__class__ = ...`, allowed since Python 3.5): `core.RACINE` reads `current().settings.root`, and `core.RACINE = x` writes it.
   **The module's dictionary keeps a mirror** of each name, refreshed by the setter and by `install()`. Without it, `mock.patch.object` cannot restore
   the value (it reads the original from the module's dictionary, and when the name is missing it deletes the attribute on exit and fails); with it,
   a patch, a plain assignment by a test and a new context all leave the context and the mirror equal (checked on Python 3.14.7 with a probe, outside the
   repository). The bare names inside `core.py` (about 50 uses) read the mirror and need no change. `settings` is frozen: a change (the work root,
   `definir_racine`) goes through one function of `app_context`, which refreshes the mirrors. No call site outside `core` changes in this stage.
4. **Each module that keeps state registers it** (`reset` empties its caches and registries, `close` stops its threads and joins them, bounded in time),
   at import, under its own name. The registries stay where they are, in their modules: moving 109 objects into one class would rewrite most of the code
   during the feature freeze, for no change a person sees. `AppContext.close()` closes the parts in reverse order of registration.
5. **A conformance test proves the list is complete**, as the access test does for the routes: it imports every module of `src/lutin`, finds every
   module-level dictionary, list, set, deque, lock and event, and fails for any that is neither in a registered part nor marked constant. Constant tables
   are made immutable where it costs nothing (tuple, `frozenset`, `types.MappingProxyType`); the others are listed in the test with the reason.
6. **The tests**: `tests/context.py` installs a fresh context built from the environment it sets. `tests/lancer_tests.py` keeps one process per file
   by default and gains a mode that runs a group of files in one process, each in its own `scope`. A file joins the group when it does its setup in
   `setUpModule` instead of at import; files are moved when they are touched, not all at once.

## Stages (one commit each, the full suite after each)

1. `app_context.py`, the settings read once, the module classes and their mirrors. No behaviour change; tests of the context, including a patch, an
   assignment and a change of context.
2. The registry of running turns moves into `turns`. This is what ADR 0015 (`run_turn`, to be written) builds on.
3. `register` in every module with state; the conformance test.
4. `close` for the modules that start threads.
5. The runner's group mode and a first group of test files (those that import `context.py`, start no server and set nothing at import).

Acceptance, proposed: item 1 is done when stage 5 runs a group of test files in one process with the same results as one process each, and the
conformance test passes. Moving all 158 files is not part of it.

## Not chosen

- **Passing the context as a parameter to every function**: the most explicit, but it rewrites the signatures of most of the code during the feature
  freeze, with a large risk and no visible gain.
- **A `ContextVar`**: it would allow two contexts at the same time in one process, which nothing needs; it does not follow new threads (the server
  starts one per request), so every thread start would have to copy it.
- **A `reset()` per module without a context**: cheap, but the configuration would still be read at import, and nothing would say what the list is.
- **Module `__getattr__` (PEP 562) instead of a module class**: it only answers names that are missing, so an assignment by a test (`core.OLLAMA = ...`)
  would create a real attribute that the context would not see.
- **Properties without the mirror**: `mock.patch.object` fails on exit (it deletes the attribute, and a property without a deleter refuses), and a
  deleter could not know the value to put back.

## Consequences

- The environment is read in one place; a test sets a value by building its context, not by ordering imports.
- Every piece of state that a running Lutin holds is named, and a new one cannot be added without registering it (the conformance test fails).
- `core`'s module class is unusual Python; it is limited to the names listed in stage 1 and documented in `app_context.py`. A write to the context
  that bypasses `app_context` would leave a mirror stale: `settings` is frozen for that reason.
- No user data and no stored format change: this is about memory, not disk.

## Way back

Each stage is one commit. Before stage 3 the old names still work as before; reverting stages 1 and 2 brings back the module attributes as they are
today.

## Questions for the maintainer

- Is the scope right (context only, the registries staying in their modules but registered), and is the acceptance above enough?
- Should stage 5 be done now, or left until the test files are touched for another reason?
