**English** · [Français](VALIDATION.fr.md)

# Validating Lutin on real hardware

Lutin's automatic tests use fake services (a fake Ollama, a fake Telegram, a fake paired PC). They prove the logic is right, **not** that your Ollama, your graphics card or your second PC behave as expected. This list is the manual pass to do once per important version: one tick per line, one sentence in the report when it fails.

For each line: **Do** what is written, **see** what is expected. If not, note the line and paste the output of `lutin doctor` (no personal content) into a problem report.

## 1. Engines (one by one, on a machine that can run it)

Settings > Engine: only the engines that can run on this machine are offered (the others are folded away, with the reason).

| Engine | Do | See |
|---|---|---|
| Ollama | "Install" (or use your existing install), download a small model from the Models tab | The model shows in the list; an answer arrives within seconds |
| llama.cpp | "Install", pick a suggested GGUF model, "Start" | State "running", an answer arrives; "Stop" frees the memory |
| LM Studio | "Install" (Linux: the libatomic library is installed, or the exact command is given) | Server started, installed models listed |
| ExLlamaV3 (NVIDIA, not in Docker) | "Install", then download a model by its Hugging Face repository (owner/model) | Card visible on NVIDIA only; an answer arrives |
| Colibri | "Prepare the model" from the Models tab | No command to type by hand; state becomes "ready" |
| Every engine | "Compare engines" with the same model | Speed and memory measured, no error |

For **each** engine: the installed models are listed, a model downloads in one click with a progress bar, and "Test" returns an answer. Note the one that fails and at which step.

## 2. Several computers

Do this with two real PCs (A = where you work, B = the other one).

| Step | Do | See |
|---|---|---|
| Pair | On B: Settings > Machines, turn on, copy the code; on A: "Add a machine" | B appears, green status within 10 s |
| Wake | Switch B off, "Wake" button on A | B starts; the status turns green without a second click (the machine is probed every 2 s) |
| Icon | On B, after Windows starts | Lutin's icon sits next to the clock (maybe under the "^" arrow) |
| Answer here | Choose "This machine" or "B" in "Who answers your messages?" | The answer really comes from the chosen engine (engine name shown in the conversation) |
| Permission | On A: "Ask" for the update right | On B: the bell lights up; accept; on A the right appears. **Nothing is granted without B's answer** |
| Update | "Update" B from A | B shows the new version after restarting |
| Refusal | Withdraw the right on B | A can no longer update B, and says so |

## 3. Notifications and scheduled tasks

| Step | Do | See |
|---|---|---|
| Channel | Automation > Notifications: add Gotify / ntfy / Telegram / webhook, "Send a test" | The message arrives on your phone or your Discord/Slack channel |
| Task | Create a "tell me the time" task, run it twice | One conversation, two dated exchanges |
| Result | Attach the channel to the task, run it | The task's answer arrives on your channel |
| Failure | Switch the engine off, run the task again | The conversation shows the reason (not silence) and the notification says it |

## 4. MCP connectors (catalogue)

| Step | Do | See |
|---|---|---|
| No program | If Node.js or uv is not installed, connect "Time and time zones" | Lutin installs uv on the way (the "Programs used by the connectors" block shows it, with a button to remove it) |
| Time | Connect "Time and time zones" | "Connected" with the number of tools; ask for the time in Tokyo in a conversation |
| Files | Connect "Files" with a test folder | The model reads that folder; refuses to write while the connector is read-only |
| Broken | Connect with a folder that does not exist | Clear message, nothing is added |
| Home Assistant | Connect with the `/api/mcp` address and a long-lived token | "Connected" with its tools, or a clear error (its transport is not confirmed by the official documentation: check on your side) |
| Removal | "Remove" | The connector disappears, and its tools too |

## 5. Memory and search

| Step | Do | See |
|---|---|---|
| Recall | State a precise fact, chat for a long while, ask for it again in other words | The fact is found (plural, accents, rewording) |
| By meaning | Turn on meaning search (embeddings model), ask again with a synonym | The fact is found; without the model, word search carries on with no error |
| Measure | `python tools/mesurer_rappel.py` | Recall@1 of at least 92% on the reference corpus |

## 6. Security

| Step | Do | See |
|---|---|---|
| Secrets | Ask the assistant to read Lutin's data folder | A flat refusal (reserved folder) |
| Channels | Reload the Notifications page | No token shown again |
| Access | Open Lutin from another device on the network | The PIN code is asked |

## 7. Conversation

| Step | Do | See |
|---|---|---|
| Scrolling | While a model thinks for a long time, scroll up in the conversation | The conversation stays where you left it; a ↓ button takes you back down; sending a message takes you to the bottom |
| Loop | Ask it to read, change then re-read a file several times | No cut while the result changes; if the model really repeats itself, it is stopped and says so |
| Full window | With a small window (8k), chain several web searches | A "To fit in the context window…" message says what was shortened |
| Dry run | Turn it on, ask for a file to be created | The model says "here is what I would do", never "it is created"; the file does not exist |
| Background job | Create a job on a folder with more than 3 documents, "Stop after the first 3" ticked | It stops at "to validate"; the report can be read; "Validate" processes the rest |

## When everything is ticked

Put the date, the version (`lutin --version`), the system and the graphics card in your report, with the lines that failed. A version is ready for 1.0 when every line passes on at least one Windows and one Linux machine.
