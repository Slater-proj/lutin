# ADR 0020 — Every engine is installed, chosen and fed with models the same way

Status: accepted by the maintainer on 2026-11-21 with the answers below. Stage 1 is done (see « Progress »); stage 2 is next.

## Context

The maintainer's request of 2026-11-20: « every engine, from the point of view of the person, installed the same way and used the same way, even if
the back end differs. The catalogues must be explicit. » With it, the report that the models offered « look small », that some have no download
button, and that nothing says which one is best. Read on `b76932c`:

- **The engines the person sees are not the programs.** The Engines tab of the Models screen has three cards: Ollama, llama.cpp and « OpenAI-compatible
  server ». ExLlamaV3, LM Studio and Colibri are not cards: they are a choice in a select inside the settings of the third card
  (`EngineSettings.svelte`, `SERVERS`), and the Install, Start and Stop buttons of that card act on whichever server the select names
  (`MoteurExterne` reads the `serveur` setting, `llamacpp_engine.py`). To install ExLlamaV3, the person opens the settings of a card that does not
  carry its name.
- **Each engine has its models somewhere else.** Ollama: the Catalog tab (the curated catalogue, `ModelCatalog`) and a Library tab (ollama.com)
  shown for Ollama only. llama.cpp: the Catalog tab shows the curated catalogue, and its Hugging Face search (`EngineLibrary`) sits in the Engines tab.
  ExLlamaV3, LM Studio, Colibri: `ManagedModels`, in the Catalog tab and again in the Installed tab, with its own « recommended » block (`f379f0a`).
- **Three families of routes** for the same questions: `/models*` (the engine in use), `/engines/{id}/library*` (llama.cpp),
  `/managed-servers/{id}/*` (ExLlamaV3, LM Studio, Colibri: models, catalogue, quantizations, recommended, check, downloads).
- **What is already uniform**, and stays: every engine is an `engines.Moteur` with the same actions (`installer`, `desinstaller`, `reinstaller`,
  `demarrer`, `arreter`, `mettre_a_jour`), the same background task (`engines.launch_task`, `TASKS`) and the same fit judge (`model_fit.evaluer`).
  Since `f89bdcf` every engine task and every Ollama download shows in the bar at the top of every screen.
- **The cost of separating the programs is small**: 9 places in `src/lutin` test the engine id `openai`, 13 read the `serveur` setting (in
  `api_v1.py`, `engine_metrics.py`, `llamacpp_engine.py`), 2 in the interface.
- **ik_llama.cpp** (a fork of llama.cpp, faster on large MoE models split between the card and the processor, with its own quantizations) publishes no
  binaries: one release, in 2025, with no files. Managing it would mean building it on the person's machine (CMake, a compiler, the CUDA toolkit).

## Decision

1. **One card per program.** `GET /engines` lists Ollama, llama.cpp, ExLlamaV3, LM Studio, Colibri and « another server (OpenAI-compatible) ». Every
   card has the same parts, in the same order: name and state, version and update, what it is good and bad at (from the signed catalogue),
   **whether it can run on this machine** (hardware, system, Python, from the `materiel` and `plateformes` fields the catalogue already holds), and the
   same buttons: Use, Install, Start, Stop, Update, Reinstall, Uninstall. A button that cannot act is replaced by the reason (« needs an NVIDIA card »),
   never hidden without a word. The settings of a card hold only what is its own (port, folders, advanced options); the select of servers goes.
2. **ExLlamaV3, LM Studio and Colibri become engines of their own**: `exllamav3`, `lmstudio`, `colibri`, registered in `engines.ENGINES`, each a
   `MoteurExterne` whose server is fixed. The setting `moteur` names the program. `openai` stays, for a server reached by its address alone.
   **Old settings are read, not migrated**: `moteur: "openai"` with `serveur: "exllamav3"` is read as `moteur: "exllamav3"`. This is the way ADR 0019
   kept its old values; nothing is written until the person changes the engine.
3. **One models page, the same for every engine, in three parts**:
   - **Recommended for this machine**: at most five, ranked by the fit judge on the exact file (size of the quantization, not of the family), each
     with its verdict and the reason.
   - **Search**: the engine's own source. Ollama: the curated catalogue, then ollama.com. llama.cpp and LM Studio: Hugging Face, GGUF files.
     ExLlamaV3: Hugging Face, EXL3 repositories. Colibri: its own list.
   - **Installed**: use, remove, in memory or not (`GET /models/loaded`).
   **Every entry either has a Download button or says why not** (too big for this machine, a format this engine cannot read, a licence to accept on
   the site, offline). A size is the size of what will be downloaded.
4. **One route family** for the models of any engine: `GET /engines/{id}/models` (installed), `…/models/recommended`, `…/models/search?q=&page=`,
   `…/models/variants?ref=`, `POST …/models/downloads`, `DELETE …/models/{name}`. Each engine gives one **model source** object with those six
   operations. The existing code is behind them: `model_catalog`, the ollama.com library, `EngineLibrary`'s search, `managed_models`. A download is an
   engine task, so it shows in the bar at the top and on the card, as installs already do.
5. **ik_llama.cpp is not managed now.** It can be used today as « another server »: the person starts its `llama-server` and gives its address. It
   becomes a managed engine (a llama.cpp variant with its own release source) when its project publishes binaries; building it on the person's machine
   is not chosen. An entry « ik_llama.cpp, external » in the signed engine catalogue would tell people it exists: that needs the maintainer's private
   key, and is the maintainer's decision.

## Stages (one commit each, the full suite after each)

1. The three engines registered, the reading of old settings, `GET /engines` with six cards, compatibility on each card, the select of servers
   removed. Tests: an old `openai` + `serveur` setting opens on the right engine; every card has the same fields; a card that cannot run here says why.
2. The model source of each engine and the routes of item 4, next to the old ones. The contract fixture (`tests/fixtures/api_v1_routes.json`) is
   updated in the same commit.
3. The one models page (`EngineModels.svelte`): Recommended, Search, Installed, for whichever engine is in use. The Library tab, `EngineLibrary` in
   the Engines tab, and `ManagedModels` go. Browser tests on every engine with fake servers; screenshots for the maintainer.
4. The old routes (`/engines/{id}/library*`, `/managed-servers/{id}/*`) are removed once the page no longer calls them, with the fixture.

Acceptance: the person installs, starts and uses each of the six engines from its own card with the same buttons. The models page of each engine has
the same three parts. Every model offered either downloads or says why it cannot.

## Progress

**Stage 1 (2026-11-21).** `MoteurServeurGere` (in `llamacpp_engine.py`) is a `MoteurExterne` whose `serveur` is fixed; `MoteurExLlamaV3`, `MoteurLMStudio` and
`MoteurColibri` are registered as `exllamav3`, `lmstudio`, `colibri`, between llama.cpp and `openai`, which is now a server reached by its address only
(« Autre serveur (compatible OpenAI) »). How it was done, and what was decided while coding:

- **Old settings.** `engines.chosen_id` reads `moteur: "openai"` with `moteurs.json` → `openai.serveur` set to one of the three as that engine; `core.reglages`
  applies it. Saving any other setting writes the stored value back (`storage._enregistrer_reglages`), so `reglages.json` keeps `openai` until the person
  changes the engine. A managed engine with no section of its own in `moteurs.json` reads its port (and Colibri's model, ExLlamaV3's models folder) from
  the old `openai` section (`llamacpp_engine.section`); its first change copies them into its own section and leaves the old one as it was.
- **One server at a time, as the select did.** Changing the engine from one managed server to another, or to `openai`, stops the server Lutin started.
  Choosing `openai` itself removes its old `serveur`, otherwise it would be read as that server again. An older client may still send `server` to
  `PATCH /engines/openai/settings`: it is read as before (it names the engine in use); a managed engine refuses it.
- **Can it run here.** `Moteur.compatibilite()` reads the signed catalogue entry of the same id, whatever its type (`engine_catalog.entree`), with
  `engine_catalog.compatibility` (system, Docker, graphics card maker); a machine whose cards are not measured yet excludes nothing. ExLlamaV3 adds the
  Python check of TabbyAPI. `GET /engines` gives it as `runs_here: {possible, reason}` on every card. The descriptions of the three cards stay in the code:
  their catalogue entries are of type `externe` and describe a connection, not what Lutin installs.
- **The page.** `Engines.svelte` draws every card with one snippet; the engines that cannot run here (and are not in use) are folded under « Other
  engines (n) », each with its reason and without Use. The select of servers is gone from `EngineSettings.svelte`; the Catalogue tab shows the managed
  page for `exllamav3`, `lmstudio`, `colibri` and says « no catalogue » for `openai`. The routes did not change (`tests/fixtures/api_v1_routes.json` unchanged).
  The old page (`/ancienne/`) shows the same six cards: each managed server's settings are on its own card, its select of known servers no longer offers
  them, and its buttons act on the engine in use instead of `openai`.
- **Two existing rules met the decision.** `tests/test_moteurs_experimentaux.py` said no experimental engine has an engine of its own: Colibri now has
  one (answer B of the maintainer, « finish the integration »), so the test checks instead that it is a `MoteurServeurGere` with no adapter of its own;
  Strata still has none. The bench keeps its rule: Colibri, experimental, is not compared (`engine_bench.ENGINES_BENCH`).
- **The grid of the LM Studio card** said « Lutin does not install this server »: true of the old shared card, false on its own card; it now says what
  its weaknesses already said (the official installer, not tried on a real installation).

## Answers of the maintainer (2026-11-21)

1. **Incompatible engines folded** under « Other engines », with the reason on each. The engines that can run here are shown first.
2. **Old routes removed at stage 4**, with the contract fixture updated in the same commit.
3. **Strata under « another server »** until it is tested on a real machine.
4. **ik_llama.cpp not added to the signed catalogue** for now.

## Questions for the maintainer (answered)

1. **All six cards always**, or the engines that can run on this machine first and the others folded under « other engines »? Proposed: folded.
2. **The old routes**: removed at stage 4 (proposed), or kept until the contract step of the plan (step 2)?
3. **Strata** (experimental, in the catalogue as external): a card of its own, or only under « another server »? Proposed: under another server until
   it is tested.
4. **ik_llama.cpp in the signed catalogue** as an external server: yes or no.

## Not chosen

- **Keep one `openai` engine and only show its servers as cards.** It touches less code, but every route that takes an engine id (actions, settings,
  measures, comparison, the routing of paired machines) would need a second id for the server. The person's choice would still be stored in two
  settings that can disagree.
- **One page per engine, each drawn its own way** (today's situation, made complete). The person would learn six pages, and the differences that hurt
  today (no download button, sizes of the family instead of the file) would come back with each new engine.
- **Building ik_llama.cpp on the person's machine.** It needs gigabytes of tools that Lutin does not install anywhere else, and a build that fails
  half way is the worst first experience of an engine.

## Consequences

- The person sees the programs by their names; installing ExLlamaV3 is a button on the ExLlamaV3 card.
- A new engine is one `Moteur` and one model source; the page and the routes do not change.
- Old settings keep working without a migration; a settings file written after the change cannot be read by an older Lutin with ExLlamaV3 in use
  (the old Lutin falls back to Ollama, `moteur_actuel`'s rule for an unknown engine).
- This changes what the person sees during the feature freeze (ADR 0003): it was asked by the maintainer on 2026-11-20.

## Way back

Each stage is one commit. Stage 1 can be reverted alone: the old settings were never rewritten, so the select of servers reads them as before.
