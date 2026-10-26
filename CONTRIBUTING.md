**English** · [Français](CONTRIBUTING.fr.md)

# Contributing

## Running the tests

```bash
python tests/lancer_tests.py            # one process per file (the engine keeps global settings)
python tools/captures.py                # regenerates the README screenshots (English and French) after an interface change
python tests/lancer_tests.py securite   # only the files whose name contains « securite »
python -m pip install ruff && python -m ruff check src tests tools
```

Nothing to install to run Lutin or its tests: standard library only. Keep it that way. The interface tests use a real browser (Chrome, Chromium or Edge) and are skipped if there is none.

## Code layout

`src/lutin/moteur.py` holds the shared state (settings, paths, constants) and re-exports the rest. The work lives in modules that read that state late (`from . import moteur as _m`): `serveur` (HTTP routes), `dialogue` (a turn, the agent loop), `outils` (tools), `donnees` (conversations, memory), `rappel` (recall and document search), `planifie` (scheduled tasks), `images`, `acces`, `conseil`, `sante`, `revue`, `plan`. A constant that a test patches must live in `moteur`.

## Commits and releases

Every merge into `main` **publishes a version** (see [docs/PUBLISHING.md](docs/PUBLISHING.md)). The number comes from the commit titles: write conventional titles (`feat: …` for something new, `fix: …` for a fix, `feat!: …` or « BREAKING CHANGE » for a breaking change; `docs:`, `chore:`, `ci:`, `test:`, `refactor:` for the rest). Merge with a **squash** and a careful title: it is the one shown in the release notes.

## Rules

- One change = one test (or a sentence explaining why there is none).
- The **model catalogue** (`src/lutin/data/modeles.json`) is data: a short description sentence (140 characters), the « tools » capability checked with `ollama show`, the licence, ratings from 1 to 10 justified in the pull request description. `python tools/verifier_catalogue.py` must pass.
- No network access during the tests: use the fake Ollamas of the existing files.
- A test must never run a real system command nor modify the user's environment (see `Parcours.setUp` in `test_installation_cli.py`).
- No telemetry, ever.

## Languages (French and English)

The code, its comments and its tests are written in **French**; the application and the repository are bilingual.

- Every text shown to the user goes through `_t("texte français")` (`from .i18n import t as _t`) in Python, or `T('texte français')` in the page (`src/lutin/web/index.html`). Its English translation goes into `src/lutin/langues/messages.en.json` (Python) or `interface.en.json` (page), keyed by the exact French text.
- A text built by concatenation cannot be translated well: write it as a template (`_t("{} libres sur {}").format(a, b)`).
- `tests/test_langue.py` and `tests/test_interface.py` fail if a text has no translation, if a translation loses a `{}` variable, or if a translation is left over. Without a translation, the French text is shown: never an error, but never a silent gap either.
- Documentation: `X.md` is English, `X.fr.md` is French; each starts with a link to the other. Update both in the same pull request.

## Personal data

Never commit a conversation, a personal memory file, a `config.json` or a log. `.gitignore` excludes them; `gitleaks` runs in CI.
