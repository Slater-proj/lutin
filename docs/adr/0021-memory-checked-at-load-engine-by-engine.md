# ADR 0021 — Memory is checked when a model loads, engine by engine

Status: accepted on 2026-11-22 (the maintainer asked for « a clean, optimised memory management, engine by engine, like the other applications or better »).
Stages 1 to 6 are done; the rest is listed under « Not done yet ».

## Context

The maintainer, on an RTX 4090 (24 GB) with 32 GB of RAM: « the memory problems keep me from using models made for my card ». Lutin answered
« ⏳ Not enough memory for now (Memory + page file: 2.5 GB available; Video memory: 3.4 GB free of 24.0 GB (20.1 GB taken); the chosen model asks
about 16.5 GB) » and waited up to 15 minutes. Measured on that machine (read only, 2026-11-22):

- Lutin's `llama-server` held 20.8 GB of the card and **21.9 GB of commit** while it had 1.9 GB of RAM in its working set; 16 GB of RAM were free,
  but the commit was 43.8 of 44.8 GB. Windows counts the memory a program takes on the card in its commit charge (WDDM). « Memory + page file »
  stayed under the 3 GB threshold for as long as a large model was loaded, and the guard held **every** request of that model, although a request
  of a loaded model asks for no more memory.
- Three engines ran at once: `llama-server` (port 8089, the model), TabbyAPI (port 5000, no model: its last load had failed) and Ollama (11434,
  nothing loaded). When ExLlamaV3 was chosen, nothing unloaded `llama-server`: the guard waited for room nothing would give back.
- The guard compared the card's free memory with the weights only. TabbyAPI reserves the whole conversation cache at load (`cache_size`, Q8),
  on the card alone; it fails where Ollama or llama.cpp spill to the processor.
- ExLlamaV3 judged every model with 120 MB of cache per 1,000 tokens. A 32B with 64 layers and 8 KV heads of 128 asks 262: 4.7 GB at 36,864
  tokens, not 2.2.
- Lutin asked Ollama (`OLLAMA_KV_CACHE_TYPE=q8_0`) and TabbyAPI (`cache_mode: Q8`) for a cache in 8 bits, but started `llama-server` without
  `-ctk`/`-ctv`: twice the cache for the same model and window.
- The 27B that ExLlamaV3 « could not load » had a weights file cut during its download (« Tensor … extends past end of file »): listed complete.

What the other applications do: Ollama estimates weights plus cache before a load and evicts older models to make room; LM Studio checks a load
against the machine (« guardrails ») and keeps one model loaded by default; Jan unloads the previous model. None of them stops a request of a model
that is already loaded.

## Decision

1. **The guard judges a load, not a request.** A model already loaded by its engine is only stopped by a full data disk. Its own reservation in
   « memory + page file » is a warning in the health list, not « Problem ».
2. **Before a model loads, what Lutin's engines keep loaded comes back first**, when memory is short: Ollama's models, Lutin's `llama-server`, an
   ExLlamaV3/LM Studio/Colibri server other than the chosen one (the chosen one is never stopped: the request needs it, and it does not start
   by itself). The person is told what is unloaded. Memory is measured again; nothing loaded and nothing to unload is held as before.
   Memory is freed when a load needs it, not when the engine is changed: like Ollama, nothing is unloaded that nobody asked for.
3. **The need of a load is the weights plus what the engine reserves at once.** An engine says what it reserves for a window and cannot spill
   (`cache_reserve`, 0 by default; ExLlamaV3 from the model's `config.json`).
4. **The cache of a model is read from the model, not guessed** (`lutin.kv_cache`, from `config.json`: layers, KV heads, head dimension; the
   language model of a vision model; only the attention layers of a hybrid one, sliding ones counted whole). Ollama's already comes from
   `/api/show` (`model_info`). Unknown keeps the cautious 120.
5. **Every engine keeps its cache in 8 bits** where it is safe: llama.cpp too, with flash attention, on CUDA and Metal, when the server knows the
   options; a server that stops at start with them is started as before for the rest of the session.
6. **A model cut during its download is incomplete**, seen in its `.safetensors` headers without the network.

## Progress

| Stage | Commit |
|---|---|
| 1, 2 — a loaded model is not held; the other engines give the card back | `df3cfe5` |
| 4 — ExLlamaV3 judges with the model's own cache | `adaf666` |
| 5 — llama.cpp cache in 8 bits | `e7fc106` |
| 3 — the guard counts ExLlamaV3's reserved cache | `930d670` |
| 6 — cut weights are incomplete | `9f39760` |

## Not done yet

- The memory pill of the Chat has two states; a third, « loading », with the progress of the load (the card's memory growing towards the need)
  is the next step. While TabbyAPI is busy its `/v1/model` can take more than 3 s: the pill then says « not loaded ».
- llama.cpp's own cache for models outside Ollama's store is not read from the GGUF header (Ollama's is); the verdicts of llama.cpp use the catalogue
  or the cautious value.
- Not measured on a real machine with these commits: the maintainer's installed Lutin is an older version.

## Consequences

- A request may now start with less than 3 GB of commit left when its model is loaded: Windows can still refuse a large allocation to another
  program. The health list says so as a warning.
- Lutin may stop a non-chosen managed server under memory pressure, with a message; before, the guard never touched one (`test_liberation`).
- Way back: revert the five commits; no data is written or migrated.
