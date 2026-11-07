**English** · [Français](EXPERIMENTAL_ENGINES.fr.md)

# Experimental engines (Colibri, Strata)

Two recent engines are offered as **external presets**: Settings > Engines > "OpenAI-compatible server" card > "Pick a known server…". They are marked **experimental**, listed last, **never preselected, never recommended** (neither by the recommendation rules nor by the bench).

> **Why no managed integration?** The roadmap only plans installing and starting Colibri from Lutin if trial S3 (Ollama, llama.cpp and Colibri on the same GGUF, on a real machine) justifies it. **That trial has not been done.** So Colibri stays a server you start yourself; Lutin can only talk to it.

## How to use one

1. Install and start the engine's server (follow its instructions: Lutin neither installs nor starts it).
2. In the page: pick it in "Pick a known server…", check the address, save.
3. Then choose the "OpenAI-compatible server" engine and one of its models.

Each engine is **independent**: setting one up touches neither Ollama, nor llama.cpp, nor the other one.

## Colibri (JustVugg/colibri)

- **What for**: very large mixture-of-experts models: hot experts on the card, warm in RAM, cold read from disk. OpenAI-compatible API, usual address `http://127.0.0.1:8000/v1`. Reads GGUF.
- **Limits**: research project; published figures come from its authors and were not redone here; with 32 GB of RAM, very large models go to disk and get slow; inconsistencies spotted in its figures (see [ENGINE_STUDY.md](ENGINE_STUDY.md)).

## Strata (Niko1221/Strata)

- **What for**: desktop app and command line with a local OpenAI-compatible API. NVIDIA RTX 20 to 50 cards (Windows, Linux), AMD and Intel Arc on Linux.
- **Limits**: the **port of its API is not checked** (empty address: copy the one Strata shows); self-measured figures on other models; needs a lot of memory (12 GB card and 32 GB of RAM at least according to its authors).

## What is tested

A fake OpenAI-compatible server: the preset, the address setting, the model list and an answer. **Neither of these two engines has been tried for real** with Lutin.

## Adding another engine

One more engine is an entry in the signed catalogue (see [ENGINE_CATALOG.md](ENGINE_CATALOG.md)): `type` `externe`, `genre` `openai`, `experimental` `true`. No code to write.
