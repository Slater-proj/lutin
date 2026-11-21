# Models larger than the graphics card: study and decisions (2026-11-20)

The question: people run models much larger than their card's memory by spreading them over the card, the memory (RAM) and the SSD, and say
that mixture-of-experts (MoE) models suit this. Should Lutin do it, in a guided way, and should the catalogue offer larger models?

## What was found

Sources were read on 2026-11-20. The llama.cpp facts come from its source (`common/arg.cpp`, `common/fit.cpp` on `master`, release v1.0.0 of
2026-11-13), not from articles. The speeds come from public reports and were not measured here.

- **An MoE model only uses a few experts for each word** (Qwen 3.6 35B: 3.5 billion of 35.5 work for each word). Its experts are 85 to 97 % of the
  file (read from the GGUF headers of seven models on the Ollama registry). Keeping the experts in RAM and the rest (attention, shared weights,
  the conversation's cache) on the card costs little speed. Public reports give 25 to 33 words per second with an 8 to 12 GB card. Examples:
  Qwen 3.6 35B with 8 GB, and gpt-oss 120B with 12 GB and 64 GB of fast DDR5. The speed of the RAM matters most: slow DDR4 gives about a third.
- **llama.cpp does this placement by itself.** `--fit` (on by default in recent versions) adjusts what the user did not set. It already keeps
  expert weights in RAM when the model does not fit on the card. It gives up, with a warning only, when `-ngl` or tensor placements
  (`--n-cpu-moe`, `-ot`) are already given. Ollama ≥ 0.30 runs GGUF models through llama-server and keeps this behaviour as long as `num_gpu` is
  not set; Lutin never sets it.
- **Reading the model from the SSD (when it does not fit in RAM) is not usable**: about 1 to 3 words per second with stock llama.cpp, and
  minutes for a long prompt.
- **Strata** (github.com/Niko1221/Strata, MIT, autumn 2026) does this better: hot experts cached on the card, the rest in RAM, a large table
  read from the SSD. But it is a whole application for a few models (Qwen 3.8 Flash Next mostly), young (0.1 to 0.2), and its speeds are
  mostly its author's own.
- **llama.cpp 1.0 removed `--no-mmap`, `--mmap` and `--mlock`**, folded into `--load-mode` (`none`, `mmap`, `mlock`…).

## What Lutin already did

- The catalogue knows the active parameters of each model (`actifs_b`).
- `model_selection.best_context` lets an MoE model whose active part is at most a third of its weights take the RAM's help ("partial"). The rule:
  card budget plus half the free RAM must hold the model with an 8,192-token conversation.
- `llamacpp_engine` passes `--fit on` when a model does not fit the card, `--n-cpu-moe N` when it is set in the engine's settings, and `--no-mmap`
  on a graphics card.

## What changed (this commit)

1. **llama.cpp 1.0**: when the server no longer knows `--no-mmap`, Lutin passes `--load-mode none` (and `load-mode = none` in the router's
   presets). Without it, a model on the card was also kept whole in RAM again: the problem that `--no-mmap` fixed.
2. **Experts imposed in the settings**: `--fit` is no longer passed with `--n-cpu-moe` (it would give up); every layer goes on the card (`-ngl 99`)
   and the experts of the first N layers stay on the processor, the usual recipe. Without imposed experts nothing changes: `--fit` places them.
3. **The verdict** for an MoE model that takes the RAM's help no longer says "the rest on the processor: usable but slow". It says the experts wait
   in RAM, that it answers at a good pace, and that it reads long messages more slowly.
4. **The catalogue** (version 7) gains three MoE models. Their sizes, parameters, context and conversation cache were read from the GGUF files on
   the Ollama registry, and their licences and capabilities from the registry and ollama.com:
   - `qwen3.6:35b` (22.6 GB with its image projector, 35.5 B / 3.5 B active, images, 21 MB per 1,000 tokens);
   - `glm-4.7-flash:latest` (19.0 GB, 29.9 B / 3.9 B active, MIT; compressed cache counted without compression: 105 MB);
   - `qwen3-next:80b` (50.4 GB, 79.7 B / 3.9 B active, for 64 GB of RAM).

   Their notes are editorial, like the others.

## Not done, and why

- **SSD streaming**: rejected for the guided product: too slow, and long prompts take minutes.
- **Strata as an engine**: not now. It is an application tied to one family and young. To look at again if it becomes a server for many models.
- **`--moe-cache-mib`** (experts cached on the card, llama.cpp ≥ Oct 2026): off by default upstream, crashes reported on some AMD and Windows set-ups.
  Not offered.

## The fit rule for MoE models (maintainer's decision, 2026-11-20)

"Coherent with the measured machine": a mixture-of-experts model fits when what is not an expert (attention, shared weights), the conversation
and the margin fit on the card, and the experts that do not fit on the card fit in the **free RAM measured on the machine minus a 2 GB reserve**
(`model_selection.experts_split`, `RAM_RESERVE_GB`). It replaces "card budget plus half the free RAM". The share of experts is estimated as
1 − active / total parameters, a little below the real share read from the GGUF files: the estimate keeps a little more on the card than needed,
never less.

- The longest conversation that still fits is chosen (it was always 8,192 tokens), and an MoE model that would fit on the card only with a short
  conversation (under 16,384 tokens) prefers to keep a few experts in RAM.
- The verdict says "fine" when at least 4 GB of RAM stay free and the conversation is long enough, "tight" otherwise, with the figures.
- It applies only on an engine that keeps experts in RAM: a new capability, `experts_in_ram` (Ollama yes; llama.cpp when its server knows `--fit`
  or `--n-cpu-moe`, or is not installed yet; an OpenAI-compatible server no). Elsewhere the verdict says the model is too big *with this engine*
  and names the engines that can. The catalogue, the variants and the roles read it.
- Example, RTX 4090 (24 GB) and 32 GB of RAM, 22 free: Qwen 3.6 35B fine (3 GB of experts in RAM), Gemma 4 26B fine (1 GB in RAM, instead of a
  8,192-token conversation), Qwen 3 Next 80B and gpt-oss 120B too big (30 and 45 GB would have to wait in RAM).

## Colibri (studied 2026-11-20)

Lutin already installs Colibri (archive checked against `SHA256SUMS.txt`), starts and stops `coli serve`, lists the models of `coli setup` and
prepares one. Read in its repository (v2.1.0, 2026-10-31; nothing run here):

- **Where it adds value**: models much larger than RAM, read from NVMe. The authors report 3 to 8 words per second (DeepSeek V4 Flash 85 GB,
  MiMo Flash 106 GB) with 62 GB of RAM and two NVMe drives. llama.cpp gives 1 to 3 in that case.
- **Where it does not, so far**: for models that fit in card plus RAM, no independent comparison with llama.cpp exists. Its processor kernels are
  measured 2 to 5 times slower than ggml (issues #2189, #2831). It reads only some families (Qwen 3/3.5/3.6/3.8, DeepSeek V4, GLM 5, MiMo, Kimi):
  no gpt-oss, Gemma or Llama.
- **What the current integration misses**:
  - The card. Without the CUDA overlay archive (NVIDIA, compute ≥ 8.0) or `COLI_VULKAN=1` (AMD, Intel), Colibri runs on the processor.
  - A fixed `--model-id`.
  - `coli import` of a GGUF already downloaded. It works by link: an Ollama Qwen 3.6 is reused without a second copy.
  - `max_tokens` on every request (issue #2900: stall on 8 GB cards without it).
- **Blocking for an agent**: issue #2869 (open). When a client disconnects mid-answer, the slot is never freed and every later request hangs,
  and Lutin's Stop does exactly that. Until it is fixed, Colibri stays an expert option, never offered by default.
- Proposed next step, for the maintainer to decide:
  1. finish the integration above, as an "expert, very large models" option;
  2. try it on a machine with 64 GB of RAM and an NVMe drive.

  With 32 GB of RAM, the models it is made for are read mostly from disk.
