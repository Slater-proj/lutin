**English** · [Français](ROADMAP.fr.md)

# Roadmap: from 0.16 to 1.0

Written 2026-11-06 from the maintainer's master plan and the [engine study](ENGINE_STUDY.md). It **replaces** the plan's numbering: that plan started from 0.15.1 and Lutin is already at 0.16.1.

Lutin stays what it is: **easy to install on any Windows, Linux or Docker machine, easy to use**, and able to do everything below **without imposing it**. A single machine must remain fully functional.

## 1. Principles (non-negotiable)

Those of the maintainer's plan and of [DECISIONS.md](DECISIONS.md):

1. **Standard library only**, no dependency (including for signature verification: see §3, D1).
2. **Script install, no administrator rights**; nothing installed without consent (no engine, no model); no large download without confirmation.
3. **Ollama and current behaviour never break**: every milestone passes the whole existing test suite.
4. **No telemetry**, strict offline mode honoured by every new feature, nothing exposed to the Internet by default, no data sent to a service without explicit permission.
5. **Two languages** (French and English) for the interface and the documents, with the completeness test.
6. **The user chooses**: Lutin recommends and explains, it does not decide.
7. **Never claim a platform, GPU or mechanism was tested when it was not.** The real trials are listed in §6; the developing assistant cannot use a graphics card, Docker or the two machines: the maintainer (or CI where possible) runs them.
8. Each big feature goes through a **feasibility study** and a **validation gate** before being written (§5).
9. **Version derived from git tags**: `feat:` bumps the minor version, `fix:` and `docs:` the patch; no fictitious tags.

## 2. Actual state (0.16.1) against the plan

| Plan | State |
|---|---|
| Common engine interface | **Done** (`moteurs.py`): Ollama, llama.cpp (managed or external), OpenAI-compatible server; possible actions per engine with reason; background tasks. **To complete**: capability grid (native / adapted / unsupported / untested), common conformance tests, formal healthcheck. |
| On-demand installation | **Done for llama.cpp** (download, fingerprint, safe extraction, uninstall, reinstall) and **Ollama on Windows** (signature). **Missing**: updates, clean cancel and resume, Docker, guided Ollama on Linux/Mac. |
| Adaptive Models tab | **Done** (hides what is Ollama-specific; Hugging Face for llama.cpp). |
| Updatable model catalogue | **Exists** (JSON on GitHub, weekly check). **Engine catalogue: to create.** |
| Hardware detection, benchmark, calibration | **Exist** (`machine.py`, `bench.py`, "Test my PC") but Ollama-centred. |
| Security | Access levels, pairing code, proxy, journal, approvals, MCP. **Nothing** for authentication between machines. |
| Docker | Full image (Lutin + Ollama), light image, GPU/AMD/Intel/proxy profiles, persistent volume. |
| CI | Ruff, Linux/Windows tests, install scripts, package, Windows installer, Docker image, secret detection. **Missing**: measured coverage, Docker volume test. |
| Cluster, remote wake-up, autostart | **Nothing.** |

## 3. Proposed architecture decisions

**D1. The engine catalogue is signed data, not code.** A JSON (engines, tested versions, platforms, files to download with their fingerprint, declared capabilities, prerequisites, notes), served over HTTPS from the repository like the model catalogue. **Ed25519 signature verified in pure Python** (≈ 100 lines, RFC 8032 vectors in tests, ≈ 10 ms), private key **outside the repository** (a `tools/` script signs), **two** embedded public keys for rotation. Invalid or offline catalogue: the catalogue **shipped with Lutin** is kept, always valid. No remote code is ever executed; a new engine that already speaks OpenAI is added **without a new Lutin release**.

**D2. Only two adapter families**: `ollama` and `openai`. Any other engine is a catalogue entry (default address, port, key, install help). Dedicated code exists only for an engine whose **lifecycle Lutin manages**: llama.cpp (done), possibly Colibri if its trial is conclusive.

**D3. llama.cpp moves to native router mode.** One managed server, `--models-dir`, `--models-max`, load and unload on demand (`/models/load`, `/models/unload`): we drop "a server restarted at every model change". Several models ready → **several roles** without restarts. Lutin generates a **random API key** for the server it manages (even on 127.0.0.1: another local program cannot use it). **Pinned, tested version** (never "latest": every release is a pre-release); updates **proposed**, never automatic.

**D4. Docker: companion engines, no engine inside the Lutin image.** The **full** image (Lutin + Ollama) **stays the default** (decision of 2026-10-26) **until the comparison bench (D5) shows better on real hardware**. In addition: **Compose profiles** adding a companion container (official images `ollama/ollama` or `ghcr.io/ggml-org/llama.cpp:server[-cuda|-vulkan|-intel|-openvino]`), linked to Lutin by **address** (the "external" mode already exists) with presets in the catalogue. No Docker socket mounted in Lutin (risk), the GPU stays managed by Docker. A native engine on the host from a container remains **impossible without a host agent**: we do not promise it. On Windows, **native recommended for a PC with an NVIDIA card** (WSL2 only gets half the RAM by default); Docker for Debian. `lutin doctor` detects and explains.

**D5. An engine comparison bench** (`lutin bench-engines`, and a button in the page): **same GGUF file** (Ollama blobs are GGUF: llama.cpp reads the same bytes), measuring load time, first token, tokens/s, RAM, VRAM, stability; shareable JSON output. It **settles** the open questions (small PC with integrated GPU: CPU / Vulkan / OpenVINO / Ollama; NVIDIA card: Ollama / llama.cpp / Colibri on expert models). It never runs at first launch; quick (about 1 minute with an installed model) or thorough, optional; results kept and redone only if hardware, a driver or a version changes.

**D6. Explainable engine recommendation**: a rule table (hardware → recommended engine, with the reason, disk space, dependencies, limits) fed by the catalogue and by bench results when they exist. Hardware diagnosis in seconds, **without downloading any model**. If no model is installed: theoretical recommendation, nothing is downloaded.

**D7. Machines, without a separate agent: every Lutin is a node.** A machine = name, address, own token, optional MAC address. **Added by explicit validation** (the existing pairing code, never automatic acceptance, no network discovery). The node exposes its machine's engine on an authenticated interface; the main Lutin routes a request to it and **silently falls back to the local engine** if unreachable. **Only four observable states**: unreachable · wake sent · node reachable · engine operational. Routing first, request spreading later; **splitting one model across machines is not in the 1.0 scope**. First step **already possible today**: an "external" engine pointing to the other machine's `llama-server --api-key`.

**D8. Power**: wake by magic packet (UDP, standard library), shutdown by the node (**explicit action, with approval and journal**), autostart by **per-user "Run" key (no administrator rights; a scheduled task at logon needs them)** on Windows (no service: session 0), systemd unit on Linux. Each limit is told to the user (BIOS, cable, Windows auto-logon).

**D9. Roles per engine**: the five current roles keep their meaning; each may name engine, model, context and fallback.

## 4. Milestones

Each milestone: study → validation gate → targeted code → tests → FR/EN documentation → report with known limits. The criteria are what must be true to **ship**.

### 0.16.x (`fix:`) — Validate llama.cpp for real
- Real trials S1 and S2 (§6) on a Windows PC with an NVIDIA card and in CI; fixes.
- **Criterion**: installation by Lutin on a Windows PC with an NVIDIA card, a GGUF model downloaded, a conversation with working tool calls; otherwise the precise list of what fails.

### 0.17.0 — Signed engine catalogue
- Strict format and schema, Ed25519 verifier (RFC 8032), signing `tools/`, copy shipped with Lutin, online reading, weekly watch (new llama.cpp, Colibri, Strata… versions: a pull request to review, never published on its own).
- An engine's card (Settings > Engine) comes from the catalogue; external engines (LM Studio, vLLM, SGLang, LocalAI, llama-swap, Strata…) are presets there.
- `ENGINE_CATALOG.md`, `ENGINE_DEVELOPMENT.md` (adding an engine).
- **Criterion**: an OpenAI-compatible engine is added with one catalogue line, without touching code; a modified or badly signed catalogue is refused; offline, the shipped catalogue suffices.

### 0.18.0 — llama.cpp router mode, capabilities and conformance
- Router mode, generated API key, pinned version, `--fit`, expert models (`--n-cpu-moe`), vision (`--mmproj`), embeddings through the engine (semantic search with llama.cpp).
- Per-engine capability grid (native / adapted / unsupported / untested) shown on the card; **common conformance suite** run on every adapter with fake servers.
- **Criterion**: two models used by two roles without restarting the server; the conformance suite passes for the three adapters.

### 0.19.0 — Comparison bench and recommendation
- D5 and D6; Diagnostics page; results kept.
- **Criterion**: on a real machine, the bench compares at least two engines on the same GGUF and produces a readable file; the recommendation shows its reason. **The Docker (default image) and small-PC decisions are taken here, on figures.**

### 0.20.0 — Advanced installation and first launch
- Proposed updates, cancel and resume, **companion Compose profiles** (Ollama, llama.cpp CPU / CUDA / Vulkan / Intel) with address presets, guided Ollama on Linux/Mac, Docker `lutin doctor` (WSL memory, model folder).
- First launch: quick diagnosis, recommendation, install / pick another / later; **while no engine is ready, the Models tab is cleanly disabled with the reason**.
- `DOCKER_INSTALLATION.md` (Docker Linux and Docker Desktop/WSL2).
- **Criterion**: restarting or recreating the container reinstalls nothing and loses no engine or model (CI volume test).

### 0.21.0 — Models and roles across engines
- **Already done in 0.16.8**: Ollama's models (uncensored ones included) are read in place by llama.cpp under the same names; same folder lines on every engine card.
- Model catalogue filtered by engine (format, quantisation, estimated memory, compatibility); roles per engine; quick and thorough bench independent of Ollama.
- **Criterion**: never a model offered that is not compatible with the chosen engine.

### 0.22.0 — Resources and large models
- Pre-load estimate and saturation warning, cautious mode for modest machines, presets for expert models (24 GB card + 32 GB RAM: experts in RAM, rest on the card), context and KV-cache advice.
- **Criterion**: a too-big model is flagged **before** loading; the estimate is compared with bench measurements and the gap documented.

### 0.23.0 — Machines (cluster, level 1)
- D7: registry, pairing, node token, visible state (four states), routing, silent local fallback, journal; **an unreachable machine produces no error or warning in the conversation**, only a visible state on the Machines page.
- `CLUSTER_ARCHITECTURE.md`.
- **Criterion**: a small Debian box's Lutin answers with the NVIDIA PC's engine, falls back locally if it is switched off, with no visible interruption outside the Machines page; no data is sent to an unauthorised node.

### 0.24.0 — Power
- D8: wake, shutdown, autostart; states "wake sent → node reachable → engine operational"; clear reason when it does not work.
- **Criterion**: trials S5 and S6 succeed or limits are documented (Windows auto-logon, BIOS).

### 0.25.0 — Experimental engines
- Colibri: **managed** integration (prebuilt archives + fingerprint) **only if trial S3 justifies it**; Strata and others: external presets. "Experimental" label, never offered by default.
- **Criterion**: each added engine is independent, tested with a fake server, documented with its limits.

### 0.26.0 — Stabilisation → 1.0.0
- End-to-end tests on both machines, with and without a graphics card, Windows, Debian, Docker, network failure, update, migration; security audit; full documentation; rollback procedure.
- **1.0.0** only if the stability, security, portability and testing criteria are met; experimental engines are **not** required.

- **Done (milestone 0.26.0, software part)**: a damaged data file no longer crashes Lutin (a real bug, found and fixed), backup before update + `lutin update --rollback-to` + `ROLLBACK.md`, security review (`SECURITY_AUDIT.md`), fresh-install walk-through test, one engine probe fewer per refresh.
- **Left for 1.0 (cannot be done without you)**: the real-hardware trials S1–S7, a rollback trial on a real release, (update wheel verification against `SHA256SUMS.txt` is now done and was checked on real releases), and the default Docker image decision from the bench figures.

**Ongoing (not a version)**: measured coverage without a blocking threshold; Docker volume CI test; **optional** self-hosted GPU runner, started by hand, never on external pull requests.

## 5. Method and validation gates

For each milestone, before writing code: feasibility, up-to-date technical information, architecture, files touched, dependencies, risks, criteria, tests, alternatives. **The maintainer validates**, then: working branch, targeted changes, tests, regression fixes, documentation, report. Never several big experimental changes in one modification; never an existing feature removed without agreement; never a failed test hidden.

## 6. Real trials (on hardware)

| # | Trial | Where | Decides |
|---|---|---|---|
| S1 | Install llama.cpp through Lutin (CUDA 12.4 + libraries), download a GGUF, chat with tools | Windows PC, NVIDIA card | 0.16.x |
| S2 | `llama-server` (Ubuntu archive) in `python:3.12-slim`: does it start? (glibc) + tiny test GGUF | **CI** | D4, 0.20.0 |
| S3 | Ollama / llama.cpp / Colibri on the same GGUF, dense then expert model | Windows PC, NVIDIA card | 0.19.0, 0.25.0 |
| S4 | Small PC with integrated Intel GPU: CPU / Vulkan (`/dev/dri` in Docker) / OpenVINO / Ollama, same GGUF | Small Debian box, Docker | **default image**, 0.19.0 |
| S5 | Docker Desktop: WSL2 VM memory, GPU, speed vs native; CUDA in a Windows service (GeForce) | Windows PC, NVIDIA card | D4, D8 |
| S6 | Wake the Windows PC from the small Debian box (BIOS, network card, "fast startup", firewall); shutdown | Both | 0.24.0 |
| S7 | A self-hosted runner on the NVIDIA PC for hand-started GPU tests | Windows PC, NVIDIA card | optional |

None of these trials has been run so far.

## 7. Risks

1. **Nothing llama.cpp-related has run for real.** Mitigation: milestone 0.16.x first.
2. **llama.cpp moves very fast**: tested pinned version, proposed update, weekly watch.
3. **Router-mode response format unverified** (`/models/load`…): tolerant adapter and tests against the real server in trial S1.
4. **llama.cpp's gain over Ollama is uncertain**: no figure is promised before the bench.
5. **Machine security**: a node receives conversations. Explicit authentication and authorisation first; current approvals are never weakened; the catalogue signing key is a critical point (outside the repository, rotation planned).
6. **Remote wake-up depends on hardware**: a Windows node with no open session has no agent (auto-logon is the user's decision).
7. **Documentation load**: every document exists in French and English; new files: `ENGINE_CATALOG`, `ENGINE_DEVELOPMENT`, `CLUSTER_ARCHITECTURE`, `DOCKER_INSTALLATION`, `BENCHMARKS` (migrations go in the existing `MIGRATION`).
8. **Assistant limits**: no access to the two machines or a graphics card; tests use fake engines, then are confirmed by the trials above.

## 8. What is dropped, and why

See the detail and sources in the [study](ENGINE_STUDY.md): dedicated adapter per engine (replaced by the catalogue), llama-swap (redundant with router mode), vLLM and SGLang (Linux first, no interest for one user: external), GPUStack (Linux-only nodes), KTransformers (research, Linux only), Exo (Apple first, no Windows), Windows service (session 0), splitting a model across machines (out of 1.0), automatic network discovery, coverage as a gate, paid GPU CI.

## 9. For the maintainer to decide

1. Validate this roadmap and its numbering.
2. The **default Docker image** stays "full" until 0.19.0, when figures will decide (trials S2, S4, S5).
3. Windows auto-logon for remote wake-up (0.24.0): the user's security choice, to explain when the time comes.

## 10. Status review (2026-11-07)

Plain reading: **the code and automatic tests of the plan are done; validation on real hardware is not.** Everything marked "done" below was tested with fake servers, browser tests and the CI (Windows, Linux, Docker), never on the two target machines.

| Milestone | Code and tests | Still to confirm on hardware |
|---|---|---|
| 0.16.x llama.cpp | Done | S1: install by Lutin on the NVIDIA PC, conversation with tools |
| 0.17 Signed catalogue | Done (Ed25519, weekly watch) | Back up the signing keys (outside the repository) |
| 0.18 Router, capabilities | Done | Router mode against the real `llama-server` (response format unchecked) |
| 0.19 Bench and recommendation | Done (`lutin bench-engines`, "Which engine…" card) | Real figures; they decide the default Docker image and the small integrated-GPU PC |
| 0.20 Install, first launch | Done, CI volume test | llama.cpp profiles with a card (CUDA, Vulkan, Intel) |
| 0.21 Models and roles per engine | Done on the command line and in lists | The page's bench buttons are still Ollama-only |
| 0.22 Estimate | Done | Estimate-vs-measure gap on real hardware |
| 0.23 Machines | Done (two real servers in one test) | Two real computers |
| 0.24 Power | Done | Wake, shutdown, autostart on real PCs (S6) |
| 0.25 Experimental engines | External presets done; `lutin colibri` (verified install) | S3; Colibri start-up with a real model; no page button |
| 0.26 Stabilisation | Software side done (see above) | Rollback trial on a real release; wheel check against `SHA256SUMS.txt` (open decision) |

**For 1.0**: trials S1 to S7 (§6), the Docker and small-PC decisions from the bench, the rollback trial, the decision on update verification. Experimental engines are not required.

**Numbering**: published versions carry the numbers the repository computes (latest: v0.23.x); the 0.24 to 0.26 numbers in this roadmap are working milestones, bundled into those releases.
