# The engine catalogue

Lutin knows model servers (LM Studio, vLLM, SGLang, LocalAI, llama-swap…) through a **catalogue**: a data file, never code. In Settings > Engines, the "OpenAI-compatible server" card offers these servers in one click: the usual address is filled in, with a short description, strengths, limits and a link to the website.

## Why it is signed

The catalogue can be updated online without a new Lutin release. So that nobody can slip in a booby-trapped address, it is **signed** (Ed25519, RFC 8032):

- Lutin embeds **two public keys** (`2026a`, `2026b`): only one is used; the second allows changing key without breaking existing installs.
- Verification is pure Python (`src/lutin/ed25519.py`, about 6 ms), dependency-free, and tested with the RFC 8032 vectors.
- A catalogue **changed by a single comma**, signed by another key, or breaking the schema is **refused**. The schema is strict: an unknown field is refused, addresses must be `http(s)`, websites `https`.
- No remote code is ever executed: the catalogue holds only texts and addresses.

## Where the catalogue comes from

1. The copy **shipped with Lutin** (`src/lutin/data/moteurs.json`): always valid, enough when offline.
2. A copy **fetched online** (at most once a week, in the background, only if updates are not disabled and not in offline mode): kept only if properly signed, valid and newer. The `catalogue_moteurs_url` configuration setting changes the address (empty: no online read).

## Format

```json
{
  "catalogue": { "version": 1, "date": "2026-11-06", "moteurs": [ { "id": "lmstudio", "nom": "LM Studio", "genre": "openai",
      "adresse_defaut": "http://127.0.0.1:1234/v1", "site": "https://lmstudio.ai", "plateformes": ["windows", "linux", "macos"],
      "description": { "fr": "…", "en": "…" }, "points_forts": [ { "fr": "…", "en": "…" } ], "points_faibles": [ … ] } ] },
  "cle": "2026a",
  "signature": "<base 64>"
}
```

The signature covers the sorted, compact JSON text of `catalogue` (see `catalogue_moteurs.canonique`). Fields: `id` (lowercase letters, digits, `-` and `_`, never `ollama`, `llamacpp` or `openai`), `nom` (name), `genre` (only `openai` exists), `description` are required; `adresse_defaut` (default address), `cle_requise` (key required), `points_forts` (strengths), `points_faibles` (limits), `plateformes` (platforms), `site`, `remarque` (note) are optional. Texts are a string or `{ "fr": …, "en": … }` (French is required).

## Signing (maintainer)

Private keys (32-byte seeds in hexadecimal) stay **out of the repository**, by default in `~/.lutin-signature/cle-a.seed` and `cle-b.seed`. Back them up elsewhere: without them, no more online catalogue updates.

```
# 1. edit tools/moteurs.source.json (and raise "version" and "date")
python tools/signer_catalogue_moteurs.py            # signs -> src/lutin/data/moteurs.json
python tools/signer_catalogue_moteurs.py --verifier # checks the shipped file
```

A test fails if the source and the shipped file differ: re-signing cannot be forgotten.

**Changing key**: sign with `--cle 2026b`, publish; once every install has that version, replace key `2026a` with a new one in `CLES_PUBLIQUES` in the next release.

**Lost or leaked private key**: remove that key from `CLES_PUBLIQUES` in a new Lutin release (up-to-date installs then refuse its signatures) and sign with the other one.

## What the catalogue does not do yet

The Ollama and llama.cpp cards (which Lutin installs and drives) still come from code; they will move to the catalogue with tested versions and files to download (0.18.0 onwards). The automatic watch for new engine versions (a pull request to review, never published on its own) will come later too.
