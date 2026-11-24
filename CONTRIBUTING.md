**English** · [Français](CONTRIBUTING.fr.md)

# Contributing

## Running the tests

```bash
python tests/lancer_tests.py            # one process per file (the engine keeps global settings)
python tools/captures.py                # regenerates the README screenshots (English and French) after an interface change
python tests/lancer_tests.py securite   # only the files whose name contains « securite »
python -m pip install ruff && python -m ruff check src tests tools
cd frontend && npm ci --ignore-scripts && npm run check && npm test && npm run build   # the interface
```

Nothing to install to run Lutin or its tests: standard library only. Keep it that way. The interface tests use a real browser (Chrome, Chromium or Edge) and are skipped if there is none.

## Code layout

`src/lutin/core.py` holds the shared state (settings, paths, constants) and re-exports the rest. The work lives in modules that read that state late (`from . import core as _m`): `server` and `api_v1` (HTTP; every v1 route declares its right in one table), `agent` and `turn_runner` (a turn, the agent loop, one entry for every launcher: ADR 0015), `tools`, `storage` and `store` (conversations in SQLite, ADR 0017), `recall` (recall and document search), `scheduled_tasks`, `mission`, `images`, `access`, `health`, `change_review`, `machines` (paired computers). A constant that a test patches must live in `core`. The interface is in `frontend/` (Svelte 5, TypeScript, Vite; see [frontend/README.md](frontend/README.md)); `tools/construire_icones.py` regenerates the icons by hand.

## Commits and releases

Every merge into `main` **publishes a version** (see [docs/PUBLISHING.md](docs/PUBLISHING.md)). The number comes from the commit titles: write conventional titles (`feat: …` for something new, `fix: …` for a fix, `feat!: …` or « BREAKING CHANGE » for a breaking change; `docs:`, `chore:`, `ci:`, `test:`, `refactor:` for the rest). Merge with a **squash** and a careful title: it is the one shown in the release notes.

Until 1.0 is released, work and pull requests target the `modernization` branch; `main` only receives the release. `tools/release_channel.json` decides whether a merge publishes an alpha, beta, release candidate or stable version.

## Rules

- One change = one test (or a sentence explaining why there is none).
- The **model catalogue** (`src/lutin/data/modeles.json`) is data: a short description sentence (140 characters), the « tools » capability checked with `ollama show`, the licence, ratings from 1 to 10 justified in the pull request description. `python tools/verifier_catalogue.py` must pass.
- No network access during the tests: use the fake Ollamas of the existing files.
- A test must never run a real system command nor modify the user's environment (see `Parcours.setUp` in `test_installation_cli.py`).
- No telemetry, ever.

## Languages (French and English)

The code, its comments and its tests are written in **English** ([ADR 0001](docs/adr/0001-english-and-clean-break-at-1.0.md)); a module still in French keeps its language until its names are renamed. The application and the repository are bilingual, and French stays the language the texts are written in.

- In Python, every text shown to the user goes through `_t("texte français")` (`from .i18n import t as _t`); its English translation goes into `src/lutin/langues/messages.en.json`, keyed by the exact French text.
- In the interface, texts live in `frontend/src/lib/messages.ts` (French and English, one key each) and are shown with `t("key")`; a Vitest test fails if a key is missing in one language.
- A text built by concatenation cannot be translated well: write it as a template (`_t("{} libres sur {}").format(a, b)`).
- `tests/test_langue.py` fails if a Python text has no translation, if a translation loses a `{}` variable, or if a translation is left over. Without a translation, the French text is shown: never an error, but never a silent gap either.
- Documentation: `X.md` is English, `X.fr.md` is French; each starts with a link to the other. Update both in the same pull request.

## Personal data

Never commit a conversation, a personal memory file, a `config.json` or a log. `.gitignore` excludes them; `gitleaks` runs in CI.
