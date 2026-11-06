**English** · [Français](ENGINE_STUDY.fr.md)

# Inference engine study (2026-11-06)

Basis for the [roadmap](ROADMAP.md). It states what was **read** (official pages, READMEs, release notes), what is **claimed by the authors** without independent measurement, and what is **unverified**. Nothing was installed or run to write it: every performance figure comes from the projects' own authors.

Key: ✔ read in an official source · ◐ author claim, unverified · ✘ not verified.

## 1. What Lutin already has (0.16.1)

Three engines: Ollama (historical), llama.cpp (managed by Lutin or external by address) and "OpenAI-compatible server" (address + key), which can plug in any engine speaking `/v1/chat/completions`. **Nothing llama.cpp-related has run for real yet**: it is all tested against fake servers.

## 2. Engines studied

### llama.cpp / `llama-server` — kept, the reference engine
- ✔ **Native router mode** (announced 11 December 2025): `llama-server` started without a model serves several models; `--models-dir`, `--models-max` (default 4, least-recently-used eviction), `--models-preset` (per-model INI), `--models-memory-margin`, `--no-models-autoload`; endpoints `GET /models`, `POST /models/load`, `POST /models/unload`. Each model runs in its own process. A reader reports `--models-max` is not always honoured under concurrent requests (unofficial, to check).
- ✔ **API key**: `--api-key`, `--api-key-file`; `/health` stays public.
- ✔ **Tool calling**: `--jinja` (on by default), native formats for Llama 3.x, Hermes, Qwen 2.5, Mistral Nemo, GPT-OSS…, otherwise a costlier generic format. The docs warn against heavily quantised KV caches (`-ctk q4_0`).
- ✔ **Mixture-of-experts**: `--cpu-moe`, `--n-cpu-moe N`, `--moe-cache-mib`, `-ot`; **`--fit` on by default** (adjusts unset arguments to fit in memory).
- ✔ **Vision**: `--mmproj` (experimental). **Embeddings**: `/v1/embeddings`, `--embedding`, `--pooling`. **Reranking**: `/v1/rerank`.
- ✔ **Official binaries** (build b12129 seen 2026-11-05): Windows (CPU, CUDA 12.4 and 13.4 + runtime libraries, Vulkan, ROCm, SYCL, OpenVINO), Linux (CPU, CUDA 12.8/13.4, Vulkan, ROCm, SYCL, OpenVINO), macOS (arm64, x64). **Every release is marked "pre-release" on GitHub**: a "never pre-release" rule makes no sense here; a **tested pinned version** is needed.
- ✔ **Official Docker images** `ghcr.io/ggml-org/llama.cpp`: `server`, `server-cuda`, `server-cuda13`, `server-vulkan`, `server-intel` (SYCL), `server-openvino`, `server-rocm`. The docs note GPU images are only built, not tested, by the project's CI.
- ✔ Server default port 9931 per the README (Lutin imposes its own, 8089).
- ✘ Exact response formats of `/models/load`, `/models/unload` and `/v1/models` (the "multimodal" capability field).
- Public measurements of the gain over Ollama: a few % to about twenty % when writing (mostly MoE), sometimes more; sources contradict each other and rarely compare identical conversions. **No measurement on real hardware yet.**

### Ollama — kept
- Simplest model management (library, `pull`, automatic unloading), one more service. On Intel GPUs: Vulkan **experimental** (0.12.6, 2025); a 2026 article says it is on by default but warns it can be slower on a small integrated GPU; a community report (March 2026) shows Ollama at 100 % CPU on Arc after a driver update. ✘ nothing verified on a Core Ultra Series 1.
- Ollama blobs **are GGUF files**: llama.cpp can read the very same bytes, allowing a fair comparison.

### Colibri (JustVugg/colibri) — real, active, **experimental** (candidate)
- ✔ C engine for large MoE models: "hot" experts on the GPU, "warm" in RAM, "cold" read from NVMe. Apache-2.0. v2.1.0 released 2026-10-31; 48,300 stars; 5,150 commits (GitHub counters, unaudited).
- ✔ Prebuilt archives: Windows x86-64 (AVX2, + separate CUDA archive, compute capability ≥ 8.0), Linux x86-64, macOS arm64; CPU-only possible; Vulkan 1.2 (AMD, Intel, NVIDIA).
- ✔ OpenAI-compatible (`http://127.0.0.1:8000/v1`) and Anthropic API; MCP server. **Reads GGUF as-is since 2.1.0** (`coli import`), but also uses its own converted format.
- ◐ Performance (authors' machine: i5-13500, 62 GB RAM, RTX PRO 4000 Blackwell 24 GB): Qwen3.6-35B-A3B Q4_K_M ≈ 105 tokens/s on CUDA; Qwen3.8-Flash-Next IQ2_XS (68 GB) ≈ 51 tokens/s with experts in RAM. The largest models fall to a few tokens/s or less, "the disk sets the speed".
- ✔ Limits written by the authors: "an open research platform", an integrated GPU can lose to the CPU, WSL: model folder under `/mnt/c` "many times slower", speculative decoding sometimes counter-productive.
- ✘ Internal inconsistencies noted (Qwen3.8 size, Kimi K3 speed). Fit with a machine with **32 GB of RAM**: a 68 GB model would not fit in RAM and would go to NVMe, hence much slower than the figures above.

### Strata (Niko1221/Strata) — real, active, **experimental** (external)
- ✔ MIT. v0.2.11 released 2026-11-05; 40,800 stars. Desktop app + CLI (`strata launch`), local OpenAI/Anthropic API, Windows / Linux / macOS installers (the README still cites 0.2.9).
- ✔ NVIDIA RTX 20–50 (Windows and Linux), AMD RX 7700+ (Linux), Intel Arc (Linux). CPU-only and Vulkan: **not mentioned**.
- ◐ The README performance table covers DeepSeek V4.1, not Qwen3.8; self-measured, not redone on the published version.
- ✘ Software base (llama.cpp or not), port and endpoints, "known problems" section not read.
- Article read earlier in the session: requires 12 GB VRAM and 32 GB RAM at least; **a machine with 32 GB of RAM is borderline**.

### llama-swap — **redundant** with router mode
- ✔ v270, MIT, Windows/Linux binaries, Docker images `unified-cuda13`, `unified-vulkan`, `intel`, `cpu`. Swaps llama.cpp (or other) servers on demand, `ttl`, `matrix`. Useful for someone running **several different engines** behind one address; not our need. → **external** (address), not managed.

### LocalAI — external only
- ✔ MIT, v4.11.0 (October 2026), 50,200 stars. All-in-one (text, image, voice, video), OpenAI / Anthropic API (and Ollama per April–May 2026 notes), CPU / CUDA / Intel / Vulkan Docker images. Native Windows and WSL2 **not mentioned**. Heavy; its backends install on demand in other images.

### RamaLama — external only
- ✔ MIT, v0.26.0, 3,100 stars. Runs llama.cpp/vLLM in containers (Podman by default); Windows via Docker/Podman Desktop + WSL2. Recognises Meteor Lake. Redundant with the planned Compose profiles. ✘ "alpha" status (automatic summary, not verified in the text).

### vLLM — external only, not managed
- ✔ "Does not support Windows natively" (WSL2 or community forks). NVIDIA compute capability ≥ 7.5; Intel GPU: basic features, built from source (Python 3.12); x86 CPU with AVX512 (recommended) or AVX2. WSL only gets 50 % of memory by default. Built for the throughput of **many simultaneous users**: no interest for personal use.

### SGLang — external only, not managed
- ✔ Apache-2.0, v0.5.23, Docker images. Cites RTX 30/40/50, Intel Arc, AMD, Apple. Windows and WSL2 **not mentioned**. Same audience as vLLM (production server).

### GPUStack — dropped
- ✔ Apache-2.0, v2.3.0. **Worker nodes only run on Linux** ("on Windows, use WSL2"). Engines: vLLM, SGLang, TensorRT-LLM; llama.cpp not named. Built for teams; "Enterprise" features. Lutin's own nodes (see roadmap) cover one person's need.

### KTransformers — dropped
- ✔ Apache-2.0, v0.7.2. "Research project", Linux x86-64 wheels only, no Windows or WSL2 instructions; the RTX 4090 only appears in **fine-tuning** measurements. Colibri and llama.cpp (`--n-cpu-moe`) cover the intended use.

### Exo — not feasible today
- ✔ (secondary sources, to verify on the repository) MLX engine first for Apple Silicon; on Linux, CPU only per the cited README; NVIDIA and Windows are on the authors' roadmap, **not shipped**. Unusable with the two reference machines.

### LM Studio — external only
- Closed (free) application with a local OpenAI-compatible server; handy on Windows for trying things out. Lutin cannot manage its installation.

## 3. Re-examining what I had called "unrealistic" or "pointless"

| Point | Verdict after study |
|---|---|
| A dedicated adapter per engine | **Confirmed pointless.** Two API families (Ollama, OpenAI); the rest is **data** (catalogue). Exception: an engine whose lifecycle Lutin manages (llama.cpp; Colibri if its trial is conclusive). |
| llama-swap | **Redundant**, llama.cpp's router mode does most of it natively. |
| vLLM, SGLang | **Not managed**, external. Native Windows impossible (vLLM), no gain for a single user. |
| GPUStack, KTransformers, Exo | **Dropped** (Linux-only / research / Apple first). |
| Colibri, Strata | **I was wrong about their apparent existence/maturity: they are real and active.** But their figures are self-reported, 0.x or "research", and a machine with 32 GB of RAM is borderline for their flagship models. → **experimental**, never offered by default, measured trial before any managed integration. |
| Signed catalogue (Ed25519) | **I was wrong: it is feasible.** The standard library has no Ed25519, but **verification** (RFC 8032) fits in about a hundred lines with `hashlib` (SHA-512) and Python integers; a reference pure-Python implementation verifies in ≈ 10 ms. No secret is handled, so the lack of constant time is harmless for verification. To test against the RFC vectors. Private key kept out of the repository, two embedded public keys (rotation). |
| "Stable version" of an engine | **Replaced** by "tested pinned version" (llama.cpp only publishes pre-releases). |
| Windows service | **Discouraged by default.** A service runs in "session 0", without access to the display driver: (old) sources say CUDA is impossible there on GeForce (possible with the TCC drivers of pro cards). NSSM/WinSW change nothing. → **scheduled task "at logon"**. Consequence for remote wake-up: without an open session (Windows auto-logon, the user's security choice), the agent does not start. To confirm with a trial on the NVIDIA PC. |
| Seven machine states | **Four observable**: unreachable, wake sent, node reachable, engine operational. "Off" and "asleep" cannot be told apart remotely. |
| Wake-on-LAN | **Feasible** (UDP packet, standard library) on one subnet, wired Ethernet, BIOS/UEFI option and "Wake on Magic Packet" network card; Windows "Fast Startup" to try both ways (contradictory sources); firewall UDP 9. Never from the Internet by default. |
| GPU CI | **Not free**: GitHub GPU runners are paid (≈ $0.052/min Linux 4-core GPU, $0.102 Windows) and limited to Team/Enterprise plans. A **self-hosted** runner is free but risky on a public repository → **manual trigger only**, never on external pull requests. Otherwise: scripted manual hardware tests. |
| Automatic machine discovery | **Out of scope** (mDNS needs a dependency): typed address + pairing code, which matches "never accept automatically". |
| Docker Desktop (Windows) for a PC with an NVIDIA card | **Discouraged**: near-native GPU per secondary sources (90–100 %), but the WSL2 virtual machine only gets **50 % of RAM by default** (16 GB of 32), and a model folder under `/mnt/c` is "many times slower" (Colibri). Native Windows recommended; Docker for Debian. |
| Installing an engine *inside* the Lutin image | **Replaced** by **companion** engines (official images) linked by address: no Docker socket mounted in Lutin (risk), the GPU stays managed by Docker. A binary in the volume is possible but to validate (glibc of `python:3.12-slim` vs Ubuntu binaries: CI trial planned). |
| 80 % coverage | **Measure without a blocking threshold** at first. |

## 4. Small PC with integrated Intel GPU (Core Ultra Series 1, Debian, Docker): what is and isn't known

- ◐ An IPEX-LLM benchmark on an Ultra 5: the integrated GPU is slightly faster than the CPU on small models (≈ 9.8 → 12.7 tokens/s on an 8 B; 20.6 → 23.2 on a 3 B), heavily limited by shared memory bandwidth.
- ✔ In llama.cpp, SYCL and Vulkan give results that depend a lot on drivers (Vulkan up to 2.9× faster than SYCL on an Arc in one case, the reverse in another).
- ✔ llama.cpp's **OpenVINO backend** (preview, OpenVINO 2026.1) is validated on the Core Ultra Series 1 (Meteor Lake) and is the only one able to use the NPU; ✘ no convincing measurement.
- ✘ **No measurement found for this kind of machine** in Docker. Conclusion: **measure** (CPU / Vulkan / OpenVINO / Ollama, same GGUF) before recommending anything for this kind of machine.

## 5. Main sources (consulted 2026-11-06)

- llama.cpp: server README and `docs/function-calling.md` (ggml-org/llama.cpp), "New in llama.cpp: Model Management" (Hugging Face, 11 December 2025), releases page (b12129), Docker image documentation.
- Colibri: JustVugg/colibri repository, releases page (v2.1.0), project site. Strata: Niko1221/Strata repository, releases (v0.2.11).
- llama-swap, KTransformers, LocalAI, GPUStack, RamaLama, SGLang: official repositories and latest-release pages; vLLM: installation documentation ("developer preview" pages).
- Intel / OpenVINO: Phoronix (OpenVINO 2026.1) and OpenVINO blogs; Ollama and Vulkan: Phoronix, Intel Community threads (secondary sources).
- Wake-on-LAN: Microsoft Q&A and Intel Community threads (community sources). Session 0: NVIDIA forum threads (old). GitHub Actions GPUs: price tables from the GitHub documentation (Enterprise Server versions) and third-party sites.
- Ed25519: `pyrixos-ed25519` package (≈ 10 ms per verification); RFC 8032.

This document will be **updated** when the real trials (see the roadmap, "Trials") produce figures.
