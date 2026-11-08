# Comparing engines (Ollama, llama.cpp) on your machine

(Version française : [BENCH_MOTEURS.fr.md](BENCH_MOTEURS.fr.md).)

Lutin can run the same model with Ollama or with llama.cpp (Ollama's models are GGUF files that llama.cpp reads as they are, under the same names). Which one is faster **on your machine**? The comparison bench measures it, and the recommendation tells you which engine to pick **and why**.

## Using it

- **In the page**: Settings > Engines, "Which engine for my machine?" card: the recommendation and its reason, then "Compare the engines" (about 1 minute) or "Thorough comparison" (about 5 minutes).
- **On the command line**: `lutin bench-engines [model] [--mode rapide|approfondi] [--output result.json]`.

The model has to exist on each engine compared (an Ollama model shows up as is in llama.cpp). The bench **never runs by itself**, never at first launch, and downloads nothing. Before measuring an engine, it unloads the other one's model so memory and the graphics card are all its own.

## What is measured

For each engine: cold loading, first token, writing speed (tokens per second, median of several passes), reading speed of the text sent, RAM and video memory used, and stability (one failed pass makes the engine "not recommendable").

## The recommendation

- **With a valid bench** (at least two engines succeeded, hardware and versions unchanged): the fastest is recommended **only if it wins by at least 10 %** over the simplest (Ollama); below that, the simplest is kept. The reason quotes the figures.
- **Without a bench**: general rules (NVIDIA card, AMD or Intel card, integrated card, no card, Docker), always shown as **not measured**, with their limits. Nothing is downloaded to build them.
- A result is **to redo** when the processor, memory, graphics cards or an engine version changes; a stale result no longer decides anything.

## Sharing a result

The file written by `--output` holds no path and no user name: only the hardware (processor, memory, cards), engine versions and figures. This is what will settle the questions still open on real measurements: the default Docker image, the small PC with an integrated graphics card (processor, Vulkan or Ollama), and llama.cpp against Ollama on an NVIDIA card with mixture-of-experts models. **These decisions are not made until figures from several real machines exist.**
