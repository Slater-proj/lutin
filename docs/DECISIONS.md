**English** · [Français](DECISIONS.fr.md)

# Decisions

What the project chose, why, and what is still to be decided. A decision changes when there is a better reason, not because the file is old: a dated line is then added.

## Made

| Date | Decision | Reason |
|---|---|---|
| 2026-10-25 | **Name: Lutin.** Command `lutin`. | Short, easy to type; the lutin (a house sprite) works at your place, quietly. The bare name is taken on PyPI (another project): Lutin is **not** published on PyPI, it is distributed through GitHub Releases, the install scripts and the Docker image. |
| 2026-10-25 | **Public repository** `Slater-proj/lutin` on GitHub. | Owner's request. Everything committed is public (see CONTRIBUTING.md, « Personal data »). |
| 2026-10-25 | **Standard library only**, no dependency. | Simple installation, small attack surface, nothing to keep up to date. |
| 2026-10-25 | **Two interfaces on one engine**: browser (PWA) and command line (`lutin chat`). | The terminal talks to the same local server with a token reserved to the user: same tools, same approvals, same history. |
| 2026-10-25 | **Five roles**: general, fast, creative, code, images. | « Images » = understanding images (vision), not generating them. |
| 2026-10-25 | **Unfiltered models: offered, never imposed.** « Advanced models » option, warning displayed, never chosen automatically. | The choice is the user's; the project does not push them. |
| 2026-10-25 | **No model installation without approval.** The check at launch proposes. | A model weighs 2 to 60 GB. |
| 2026-10-25 | **No telemetry.** The only network accesses: Ollama's catalogue and registry (anonymous GETs), GitHub releases (`lutin update`), requested downloads, web search if the box is ticked. All cut by strict offline mode. | Trust. |
| 2026-10-25 | **No automatic approval outside the « machine » level** (hard rule in the code, tested). | Running commands remotely without approval is the worst scenario. |
| 2026-10-25 | **Installation by script (PowerShell / shell)** in a private environment of the user, without administrator rights; by default the latest GitHub release. Idempotent. | Simple, auditable, Windows and Linux with the same mechanism. |
| 2026-10-25 | **Strict offline mode** centralised (`horsligne.py`), checked by a test that watches the real connections. | A guarantee that can be audited in one place. |
| 2026-10-25 | **Several workspace folders, one active at a time**, adding reserved to this machine. | A single root at a time avoids conflicts and crossed accesses; remote adding would allow declaring `/`. |
| 2026-10-25 | **Measured ratings = indicator** (11 questions, no model code executed), with no automatic effect on the choice of models. | A tiny benchmark must not decide alone; it is there to challenge the editorial ratings. |
| 2026-10-25 | **Version deduced from git tags** (setuptools-scm); every merge into `main` publishes (tag, Release, image); every other branch produces a candidate **without a tag**. | Nobody sets a number by hand; candidates can be tested without polluting the version history. |
| 2026-10-25 | **Docker image**: access by PIN code, port published on `127.0.0.1` by default, non-administrator user. | « This machine only » makes no sense in a container: the port must never be opened without protection. |
| 2026-10-26 | **Two languages: French and English**, for the application (interface, messages, command line) and for the repository (README, docs). French stays the language the code is written in; every displayed text goes through a dictionary and a test fails if a translation is missing. | Lutin is written in French and used in French first; English opens it to everyone. Language: environment variable, then setting (`lutin langue`, page settings), then system. |
| 2026-10-26 | **Docker: one complete image by default** (Lutin + Ollama in the same container, `:latest`), and a slim image (`:slim`, Lutin alone) for those who already run Ollama elsewhere. | « I run the image and it works »: nothing else to install. The price is size (several GB, Ollama's libraries). |
| 2026-10-26 | **Windows installer** (`lutin-setup-*.exe`, Inno Setup): per-user, no administrator rights, English and French. It uses the Python already on the computer (a private environment, like `install.ps1`) and installs nothing else; without one, it copies the Python bundled with it. Built and tested (install, re-install, bundled Python, uninstall) in CI. | The people who most need an installer are those without Python; the people who have it should not get a second one. |
| 2026-10-26 | **Signing: SignPath Foundation** (free for open source) for the Windows installer. The workflow is ready and only activates once the account exists (docs/PUBLISHING.md). | Without a signature, Windows SmartScreen warns on download. |
| 2026-10-26 | **New Lutin version announced in the page** (a banner, once a day at most, silent offline, can be skipped): nothing is installed without the user. | Models were already checked at launch; Lutin itself was not. |
| 2026-10-26 | **Claude projects** (`CLAUDE.md`, `.claude/`) can be taken over, in place or in a copy. | Context built with Claude Code must not be lost when switching tools. |

## To be decided

- **SignPath application.** The Foundation must approve the project (open source, public, built by GitHub Actions): to be requested by the owner, then the variable and secret added (docs/PUBLISHING.md).
- **Catalogue: who rates the models?** The ratings are editorial (1 to 10), written without measurement on real hardware. The benchmark (`lutin bench --exporter`) now allows proposing justified corrections; published results on a few reference machines are missing.
- **More languages.** The mechanism is in place (`src/lutin/langues/`); adding one means a dictionary for the messages and one for the page, and a code in `i18n.LANGUES`.

## Known but not verified

- **Linux**: the whole test suite runs in CI on Ubuntu (Python 3.10 to 3.13), with a fake Ollama. **Never tried with a real Ollama and a real graphics card.**
- **macOS, AMD, Intel graphics**: the code is written for them and the detection is analysed on sample outputs, but **nothing has ever run on these systems or cards**.
- **Docker images**: built and started by the CI (page, PIN code, Ollama inside the complete image) and published on ghcr.io. **Never run with a real NVIDIA card**, nor on a NAS.
- **Comparison of model fingerprints** with Ollama's registry: assumes the fingerprint displayed by Ollama is that of the manifest. To validate on a real machine.
- **Online catalogue**: read from `raw.githubusercontent.com/Slater-proj/lutin/main/…`; the weekly CI checks the catalogue, but the real fetch from an installed Lutin has not been traced.
- **`install.ps1`**: run for real on Windows (local source: installation, relaunch without change, version upgrade) and from the published address, which revealed a BOM bug (fixed in 0.1.1, with a test). `install.sh`: syntax and CI only.
- **Ollama installation** on Linux and macOS: planned (Ollama's official script, with approval), not tested.
- **Web page**: headless Chrome loads the real page without a JavaScript error in French and in English (tests), and the README screenshots come from it. The scenarios (switching conversation during an answer, green dot, search buttons) have no automatic browser test.
- **Benchmark**: tested with a fake Ollama; never run on a real model.
- **Python**: suite green on Windows with 3.10, 3.12 and 3.13, and on Ubuntu with 3.10 to 3.13.
