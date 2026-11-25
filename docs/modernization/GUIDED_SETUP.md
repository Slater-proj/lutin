# Guided models and first launch: design

Proposal for plan step 4 (onboarding and the Models screen). The maintainer answered the four open questions on 2026-11-14 (below). Built so far: the routes `GET /machine`, `/models/catalog`, `/models/recommendation`, `GET /engines` with its actions, `GET /setup` and `POST /setup/complete` ([API_V1.md](API_V1.md)), the « Recommended » tab of the Models screen and the screens of the first launch ([INTERFACE.md](INTERFACE.md)). Missing: language choice, manual correction of the machine, the optional speed test, the phone pairing step.

## Goal

A person who has never heard of a model name opens Lutin for the first time, understands in plain words what their machine can run, agrees to one download, and ends in the Chat with something that works.
The same guide serves the Models screen afterwards (« recommended » tab), so there is one piece of logic, not two.

Rules that do not bend:

- **Nothing is downloaded or installed without a click that shows its size** and the free space on the disk. Strict offline mode says so and offers nothing it cannot do.
- **The verdict comes from the server** (`model_fit`, `model_compat`), never from the page, and says it is an estimate: the editorial notes of the catalogue are « not measures » (its own warning).
- The guide can be left at any step and resumed; a download goes on without the page.
- The expert path stays one click away: the whole catalogue, a model by name, another engine.
- No network exposure is proposed by default (CLAUDE.md); phone pairing is an optional last step, off by default.

## What exists and is reused

| Need | Already in the code |
|---|---|
| Know the machine | `hardware.detecter()` gives a `Profil` (CPU, RAM, GPUs with memory, disks); `profil_demo()` and `imposer_budget()` for tests and manual limits |
| Say whether a model fits | `model_fit.judge(model, profil, ctx)` and `for_list`; `model_selection.memoire_necessaire_go` |
| Compatibility with the engine | `model_compat.evaluer(model, engine, installed)`: compatible, reasons, warnings, memory |
| Choose by use | `model_selection.choisir(profil, catalogue)` returns a choice per role (fast, creative, code, general…); `a_telecharger(choix, roles, installed)` |
| The catalogue | `data/modeles.json`: 43 models with a sentence, size, parameters, capabilities, licence, editorial notes per role, families |
| A guided first launch | `setup_wizard.py` (command line): language, security level, folders, roles, Ollama install, progress. The page must offer the same, in the same order |
| Downloads | `POST /api/v1/models` (exists) and its progress in `GET /api/v1/models` |

## What must be added (v1 routes, all English, each with a contract test)

| Route | Right | Gives |
|---|---|---|
| `GET /machine` | session | `{cpu, ram_gb, gpus: [{name, vendor, memory_gb, integrated}], disks: [{path, free_gb}], detected_at}`; a way to correct it (`PATCH /machine` for a memory budget) |
| `GET /models/catalog` | session | each model: `id`, `name`, `summary`, `size_gb`, `parameters_b`, `capabilities`, `licence`, `roles` (scores), `fit` `{level: comfortable \\| tight \\| too_big \\| unknown, reason, memory_gb, context_tokens}`, `compat`, `installed` |
| `GET /models/recommendation?use=` | session | what `choisir()` proposes for a use (`chat`, `code`, `documents`, `unsure`): the model, why, download size, other fitting choices, and the total with the free space |
| `GET /engines` | session | `{id, name, installed, running, version, can_start, can_install}` |
| `POST /engines/{id}/start` | configurator | starts it; `409 offline`-style refusals with a code |
| `POST /engines/{id}/install` | **local** | the official installer, only after an explicit confirmation carrying the size; refused offline |
| `GET /setup` and `POST /setup/complete` | session / configurator | `{done, steps: [{id, state}]}`; the flag is stored with the settings. First launch = no model installed **or** the guide never completed |

## The guide, screen by screen

1. **Welcome and language** (the language setting exists). One sentence on what Lutin is and that it runs here.
2. **This machine**: « 16 GB of memory, an NVIDIA card with 8 GB » in plain words, with « that is not right » (manual correction). Integrated graphics, containers and Apple unified memory are the cases where detection lies.
3. **Engine**: Ollama found and running: green. Found, stopped: « Start » . Absent: « Install Ollama » (size, official source, asks once) or « I use another engine » (expert path).
4. **What do you want to do?** Four choices, not model names: chat and write, code, documents and research, I do not know. Each maps to roles.
5. **Recommendation**: one model, a sentence on why, a plain verdict (comfortable, tight, too big) with its reason, the size. « Other choices » below, closed by default; « see everything » opens the catalogue with filters.
6. **Confirm**: the list, the total size, the free space, the network warning; one button. Progress with the existing download list; the page can be closed.
7. **Optional**: use it from a phone (pairing), off by default; skipping it is the normal answer.
8. **Done**: opens the Chat with the model chosen and the first suggestions.

## Tests

Contract tests per route with a fake profile (`profil_demo`), including the refusals; unit tests for the page's pure logic (steps, the total and free space); a Chrome test of the whole first launch against the fake engine with no model installed (the screens, the confirmation, the progress, the Chat at the end);
automatic accessibility checks on every step in both themes and at 360 px (the test already exists for the other screens); an honesty test: a verdict `too_big` never shows a download button without the expert path.

## Risks

- **Wrong detection** (integrated graphics, containers, shared memory): hence the visible correction and the word « estimate ».
- **Editorial notes presented as facts**: they stay labelled as estimates; a speed test after the install (`engine_bench` exists) is the way to replace opinion with a measure, later.
- **Installing Ollama runs a downloaded program**: use what `setup_wizard.installer_ollama_si_besoin` already does, check it, never run it without the confirmation, and only from this machine (right `local`).
- **Docker and servers**: no install is offered where the engine lives in another container; the guide detects it and goes to step 4.
- **Two sources of truth**: the command-line wizard and the page must call the same functions.

## Order of work (each a short step, tested)

1. `GET /machine`, `GET /models/catalog`, `GET /models/recommendation` with their tests.
2. The « recommended » tab of the Models screen on them.
3. `GET /engines`, then start and install, with the approvals and the offline refusals.
4. `GET /setup`, the guide's screens 1 to 6, the Chrome test of the first launch.
5. Phone pairing step, the end, polish, accessibility checks.

## Decisions of the maintainer (2026-11-14)

The four questions are answered; the original text is kept so that the reasons stay readable.

1. **Trigger**: the guide is shown **after the first installation on a new machine**.
2. **Installing Ollama from the page**: **kept, but framed** (a confirmation that shows the size, the right `local`, refused in strict offline mode, never without the click), as Lutin does today.
3. **Wording of the verdicts**: not discussed; the server has four levels (`comfortable`, `good`, `tight`, `too_big`) and the proposal stands: « very comfortable », « fits », « tight », « too big for this machine ». To change by one commit if wanted.
4. **Speed test** after the first download: **yes, but fast and behind a yes/no option.**

## The original questions

1. **Trigger**: show the guide when no model is installed only, or also once for existing installations that never saw it?
2. **Installing Ollama from the page**: offer it (with the confirmation), or only explain and link to the official site? The first is friendlier, the second never runs a downloaded program.
3. **Wording of the verdicts** and of the four uses: the words matter more than the code; the proposal above is a starting point.
4. **Speed test** right after the first download: worth the extra minutes for a measured result, or later and optional?
