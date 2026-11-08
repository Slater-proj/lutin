**English** · [Français](TRIALS.fr.md)

# Real trials

Lutin's automatic tests use fake servers. The trials below run **on real hardware**, by you, and each produces a **report** to send back. They match the "trials" of the [roadmap](ROADMAP.md). Nothing is downloaded without your consent (the size is announced first).

## S1 — llama.cpp on a Windows PC with an NVIDIA card

**Before**: Lutin **0.16.3** or later (`lutin update`, or the update button in the page). Optional but useful: `nvidia-smi` in a terminal shows your card and driver version.

**Step 1 — the smallest trial (about 30 seconds, a 1 MB model).** It checks that the program installs, starts and answers. In a terminal:

```
lutin engine-trial llamacpp --test-model
```

Answer `y` to the download question (the program is 25 MB to about 700 MB depending on your card: the "CUDA" version with its libraries is the biggest).

**Step 2 — the real trial with a model that can call tools (2.5 GB).**

```
lutin engine-trial llamacpp --model unsloth/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

What you should see: `✔` lines for the machine, the installation, the model, the startup, `/v1/models`, the conversation (with the **tokens per second** and the **time to first token**), the tool call, the shutdown. A `⚠` on the tool call means the model did not call the tool: not a failure, but tell me.

**If it does not work**: the message names the failing step. Useful cases:
- the installation picks "CUDA" but the server does not start → retry with `--variant vulkan` then `--variant cpu`, and tell me which one works (and your NVIDIA driver version);
- "llama-server is not answering after 180 s" → look at the end of the log shown in the message (`moteurs/llamacpp/serveur.log` in Lutin's data folder).

**What you send back**: everything the command printed (copy-paste), or the `essai-llamacpp-….json` file from the `essais/` folder of your data folder (its path is printed at the end of the command). The report contains neither your conversations nor your keys; it contains your system version, the detected hardware and the measurements.

**To measure speed properly**: run step 2 a second time (the first load is slower: the file is not cached yet) and give me the second run's figures.

**Result (6 November 2026, version 0.16.5): passed.** CUDA 12.4 build (b12167) installed in 13 s in a folder next to Ollama's, test model served at ~2900 tokens/s, then Qwen3-4B Q4_K_M (2.5 GB): **~247 tokens/s, first token in 0.04 s, full tool call**, clean stop. Finding: the “Hardware detected” line said “not detected · cpu” while the right build (CUDA) was installed just after, because hardware detection runs in the background and the first call did not wait for it. Fixed in 0.16.6: choosing the build now waits for detection (25 s at most).

## S2 — llama.cpp in Docker's light image (automatic)

Not run by you: the `moteurs` GitHub Actions workflow installs llama.cpp in `python:3.12-slim` (Lutin's "light" image), starts a 1 MB model and tells whether the program published for Ubuntu starts with Debian's system library. It runs on every change to the engine code, every week, or by hand (Actions tab, "moteurs" workflow). It **never blocks** a release. Its output contains the same report as above.

## Next trials

The other trials (S3 to S7 of the roadmap: engine comparison, small PC with Intel GPU, Docker Desktop, remote wake-up…) will get their guide here when their milestone starts.
