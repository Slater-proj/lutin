# Adding an engine

Two cases, from simplest to most involved. (Version française : [ENGINE_DEVELOPMENT.fr.md](ENGINE_DEVELOPMENT.fr.md).)

## 1. The server already speaks the OpenAI interface (`/v1/chat/completions`)

No code. Add one entry to `tools/moteurs.source.json` (id, name, `"genre": "openai"`, default address, French and English description, optional strengths/limits, website), raise `version` and `date`, then run `python tools/signer_catalogue_moteurs.py` (see [ENGINE_CATALOG.md](ENGINE_CATALOG.md)). The engine then shows up in the "Pick a known server…" list of the external server card. Lutin does not install or start it: you give its address, it manages its models itself.

## 2. Lutin must install, start or update the engine itself

Write a subclass of `MoteurOpenAI` (`src/lutin/moteur_openai.py`) for OpenAI-style servers, or of `Moteur` (`src/lutin/moteurs.py`) otherwise, and register it next to the others in `dialogue.py`. The model is `MoteurLlamaCpp` in `moteur_llamacpp.py`. What it must provide:

- `actif`, `modeles`, `chat`, `chat_flux`: talk, in Ollama's message format (translation happens at the engine's borders).
- `statut`, `actions` (install, uninstall, start, stop, update, each with `possible` and a `raison` when not possible), `faire`: the Settings card is built from these.
- `telechargeable`, `supprimer_modele` when Lutin can manage models for it.
- Tests with a fake server (no network, no real binary); the existing tests for llama.cpp show the pattern.
- Texts in French in the code, English in `src/lutin/langues/messages.en.json` (tests check completeness).
