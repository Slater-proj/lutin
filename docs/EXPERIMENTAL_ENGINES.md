**English** · [Français](EXPERIMENTAL_ENGINES.fr.md)

# Experimental engines (Colibri, Strata)

Two recent engines are offered as **external presets**: Settings > Engines > "OpenAI-compatible server" card > "Pick a known server…". They are marked **experimental**, listed last, **never preselected, never recommended** (neither by the recommendation rules nor by the bench).

> **Colibri installs from the page** (Settings > Engines > "OpenAI-compatible server" > pick Colibri: Install, Update, Uninstall, Start, Stop, model folder and port) **and from the command line.** `lutin colibri install` downloads Colibri's official archive and **checks its SHA-256 sum** (the release's `SHA256SUMS.txt` is mandatory), `lutin colibri start --model <folder>` starts it on `127.0.0.1` only, `lutin colibri stop` stops it. **The install was tried for real** (v2.1.0 downloaded, verified, unpacked); **the start-up was not**: it needs a model of tens of GB prepared by Colibri, and nobody has run it with Lutin yet. Trial S3 (Ollama, llama.cpp and Colibri on the same model) is still to do.

## How to use one

1. Install and start the engine's server (follow its instructions: Lutin neither installs nor starts it).
2. In the page: pick it in "Pick a known server…", check the address, save.
3. Then choose the "OpenAI-compatible server" engine and one of its models.

Each engine is **independent**: setting one up touches neither Ollama, nor llama.cpp, nor the other one.

## Colibri (JustVugg/colibri)

- **What for**: very large mixture-of-experts models: hot experts on the card, warm in RAM, cold read from disk. OpenAI-compatible API, usual address `http://127.0.0.1:8000/v1`. Reads GGUF after conversion.
- **Limits**: research project; published figures come from its authors and were not redone here; with 32 GB of RAM, very large models go to disk and get slow; inconsistencies spotted in its figures (see [ENGINE_STUDY.md](ENGINE_STUDY.md)).
- **Checked against its public page (2026-11-07, not by running it)**: Apache-2.0 licence; archives for Windows, Linux (x86-64) and macOS (Apple Silicon) with a `SHA256SUMS.txt`; started by its own script (`start-here.sh` / `START-HERE.bat`), which prints the browser and `OpenAI base URL` addresses; **a GGUF file must first be converted** (`coli import model.gguf`), it is not read as is; no `--version` option is documented.
- **What Lutin does for it** (`lutin colibri`): install with a verified sum, start `coli serve --host 127.0.0.1 --port 8000 --model <folder>`, stop with `coli stop`. It does **not** prepare or download a model (use Colibri's own `coli setup` or `coli import`; the folder it makes is what you give to `--model`), and never exposes it on the network. These commands come from reading Colibri's `coli` script (v2.1.0), **not from running it**; it needs Python, which Lutin has. Then pick it in the page as described above. Trial: [TRIALS.md](TRIALS.md), S3.

## Strata (Niko1221/Strata)

- **What for**: desktop app and command line with a local OpenAI-compatible API. NVIDIA RTX 20 to 50 cards (Windows, Linux), AMD and Intel Arc on Linux.
- **Limits**: the **port of its API is not checked** (empty address: copy the one Strata shows); self-measured figures on other models; needs a lot of memory (12 GB card and 32 GB of RAM at least according to its authors).

## What is tested

A fake OpenAI-compatible server: the preset, the address setting, the model list and an answer. **Neither of these two engines has been tried for real** with Lutin.

## Adding another engine

One more engine is an entry in the signed catalogue (see [ENGINE_CATALOG.md](ENGINE_CATALOG.md)): `type` `externe`, `genre` `openai`, `experimental` `true`. No code to write.
