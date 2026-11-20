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
- **The RAM share of the fit rule** (half of the free RAM) is kept. It is cautious: with a 12 GB card and 32 GB of RAM (about 22 free), Qwen 3.6
  35B (22.6 GB) is judged "too big" although public reports run it on 8 GB cards. Raising the share to about 0.8 would offer it. That is a
  change of the rule tested by `tests/test_selection.py`, left to the maintainer's decision.
