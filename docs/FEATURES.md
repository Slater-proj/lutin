**English** · [Français](FEATURES.fr.md)

# Everyday features

What Lutin does besides chatting. Everything runs on your machine; nothing here sends anything to the Internet.

## Test my PC

Models tab > **⏱ Test my PC** (or `/pc` in the chat). Lutin measures the active model's speed on this machine (about 20 seconds), then explains in plain words what it means: how many words per second, how long a 300-word answer takes, whether the model fits on the graphics card, and what to change if it is slow (a lighter model already installed or recommended for your machine, a smaller context window, the « Quiet » load profile). Nothing is changed for you.

## Dry run

Tick **Dry run** under the message box (or `/essai on`). Lutin works normally but **writes nothing and runs nothing**: each file it would write and each command it would run is shown (with the diff for files) instead of asking for approval, and the model is told it is only a simulation. Reading and searching still work for real, so the proposal is based on your actual files. Use it to see what Lutin intends to do before letting it do it: turn it off and ask again, this time for real.

## Memory notes

Memory tab > **Assistant notes**: the list of what Lutin decided to remember, each with its date and a *Delete* button. A wrong or outdated note no longer needs a manual edit of the file (that stays possible under « Edit the file by hand »).

## Documents (PDF, Word, LibreOffice text, PowerPoint, Excel…)

Drop your documents in the `docs/` folder of the workspace (or `documents/`). Lutin reads **PDF, .docx, .odt, .pptx, .xlsx and HTML pages**, besides Markdown and text without any external program, searches them offline and **quotes the page** (or slide, or sheet) it found the answer on. Memory tab > **Documents** lists what was read and has a search box; the assistant also uses it by itself through the `rappeler` and `lire` tools. Limits: scanned PDFs (pictures of text) and encrypted PDFs cannot be read; a document over 30 MB is refused; an unreadable document is reported, it never blocks the others.

## Scheduled tasks

Memory tab > **Scheduled tasks**: a request Lutin handles by itself at a set time, on the days you choose (« every morning, sum up what changed in the repository »). The result is a conversation named « ⏰ name » in the list, with a *See the result* button.

- **Read-only**: nobody is there to approve anything, so the task runs like a dry run: it reads and searches for real, every write or command is only shown.
- Starts only when no answer is in progress (one graphics card); a task missed because the PC was off runs when Lutin starts, the same day only.
- Created, paused and deleted from this machine only (like workspace folders). *Run now* tests a task without waiting.
- Lutin must be running at the set time (the page does not need to be open).

## Attachments: images, documents, text and code files

Click **📎** next to the message box, or paste (Ctrl+V) or drop files. Up to 4 **images** (PNG, JPEG, GIF, WebP, 8 MB each) and 5 **files** (20 MB each) per message:

- **Documents**: PDF, Word, LibreOffice (text, sheets, slides), PowerPoint, Excel, HTML. The text is read once, on upload (a scanned PDF with no text is refused right away, with the reason).
- **Text and code files**: notes, Markdown, CSV, JSON, logs, subtitles, and source code in the common languages (a text file is recognized by its content too, whatever its extension).

The text of the files is added to your message **for the model only**: the conversation keeps just the name. Only the most recent messages replay their files, and a long file is cut to a share of the context window (with a note saying how much was cut), so it never swamps the model. Nothing in a file is ever executed. Files stay in Lutin's data folder (`pieces/`) and orphans are deleted after two days.

## Images

Click **📎** next to the message box, or paste (Ctrl+V) or drop an image: PNG, JPEG, GIF or WebP, 8 MB and 4 images per message at most. If the current model cannot see images, Lutin switches for that request to an installed model that can (see the « Images » role in the Models tab), or tells you there is none and ignores the images. Images stay in Lutin's data folder (`images/`), only the most recent ones are sent back to the model, and orphan images are deleted after two days.

## X addon

Post on your X account and answer mentions, **without ever publishing anything behind your back**.

- **Setup**: create an app on the X developer portal with the *Read and write* permission, generate the API key + secret and the access token + secret, paste the four values (stored apart, never shown again) and check: the account handle is displayed. Requests are signed in OAuth 1.0a (checked against the example in X's documentation).
- **Posting**: *Write with Lutin* prepares one to five drafts from a subject (no tool, 280 characters at most); you edit, then **Publish now** or **Schedule** at a date and time. Your click is the approval: a draft you did not publish or schedule never leaves, nothing is ever published twice, and at most 25 posts a day go out.
- **Mentions** (off by default): answering mentions needs X read access, which is part of a paid API plan (the free plan only posts; X's error is shown if it refuses). Sorting rules like the email addon (`de:@handle`, `texte:*word*`, `ton:agressif` judged by the model…): each answer is a **draft** you approve, unless a rule says `auto` (10 a day at most). Mentions are data, never orders: the model has no tool, and the mentions already there on first activation are ignored.

## Email addon

Lutin watches your inbox (IMAP) and prepares replies (SMTP) following **your rules**: by default every reply is a **draft you approve** on the page; nothing leaves without you. Use an **app password** (created in your provider's security settings), stored apart and never shown again.

- **Rules**, one per line, the first match wins: `de:*@bank.com -> ignorer`, `sujet:*invoice* -> brouillon: Say I am looking into it.`, `ton:agressif -> ignorer`, `* -> brouillon`. Criteria: sender, subject, text, and the **tone** (aggressive, passive, neutral, friendly, judged by the model only if a rule asks); actions: ignore, draft, or **answer alone** (at most 20 a day). No matching rule: the message is ignored.
- **An email is never an order**: anyone can write any sender name, so the model has **no tool** to answer (it can only write the reply) and the message is data. Automatic messages (noreply, mailing lists, receipts, out-of-office), your own messages and duplicates are never answered.
- **Only new emails**: on first activation the existing ones are ignored, and the mailbox is read without marking anything as read.
- **Limits**: some personal Outlook.com / Hotmail accounts no longer accept app passwords over IMAP and require a modern sign-in that Lutin does not handle yet. A server on your local network is refused unless you say so in the settings.

## ComfyUI addon

Ask for an image in the conversation: **Lutin starts ComfyUI itself** when needed, after giving the memory back from the language model (the two do not fit together), generates, then **closes ComfyUI again** (only the one it started; your own is never closed). You never launch anything by hand.

- **Setup in one click**: enabling the addon looks for ComfyUI by itself (usual places, running process) and remembers the folder. The panel says plainly whether the folder is right (✔ with the number of models found, or the reason it is not: no main.py, no models folder…), with *Detect* and *Choose the folder…* buttons (pointing at the portable version's parent folder works too). Lutin starts it with its own Python (`python_embeded` or `venv`).
- **Easy setup**: *Choose the folder…* opens a folder browser (no path to type), and *Add a model* downloads a model from a Hugging Face or Civitai link straight into the right ComfyUI folder (nothing is overwritten, only those two sites are allowed, redirects are checked before being followed, the download can be cancelled; models that need you to be signed in do not work). Lutin does not install ComfyUI itself: download its portable version from the project page and unzip it anywhere.
- **Installed models**: read from ComfyUI (what it really sees: checkpoints, LoRA, VAE, diffusion models), or from the installation folder when ComfyUI is off. The model can also list them (`comfy_modeles`) before choosing.
- **Generating**: the model calls `comfy_generer` with a description (and size, model, seed…). **Each generation asks for your approval** (simulated, never done, in read-only runs such as scheduled tasks or Telegram), the language model gives up the graphics card first, then Lutin submits the workflow, waits for the result (the *Stop* button interrupts ComfyUI too) and tells where the file is.
- **Your models decide the workflow**: a classic checkpoint uses the `image` workflow; a model in `diffusion_models` uses the one of its family, recognized by its file name (**Flux**, **Qwen-Image**, **Z-Image**), with the text encoder and the VAE picked among those installed (and a clear message naming the missing file and its folder if one is absent). Both ComfyUI list formats are understood. These workflows follow ComfyUI's standard ones; if one does not suit your files, edit it in **Flow…**.
- **Workflows are data**: an image workflow is shipped; for video or sound, paste your own workflow (ComfyUI: *Save (API Format)*) in the addon's **Flow…** editor under `workflows`, with `{prompt}`, `{largeur}`, `{hauteur}`, `{graine}`, `{pas}`, `{cfg}`, `{negatif}`, `{modele}` where Lutin should write. The JSON is checked before saving, and the shipped version comes back in one click.

## Telegram addon

Talk to Lutin from your phone. Create a bot with @BotFather, paste its token (Automation tab > *Optional extensions* > Telegram > *Set up…*), check, enable, then write `/appairer CODE` to your bot (the code is shown in the card): that chat is now **yours**.

- **Your messages are requests**: Lutin works **read-only** (it reads and searches, but changes nothing and runs nothing from Telegram) in a conversation "✈ Telegram" you can also read on the PC, and answers you directly.
- **Other people**: ignored by default (not even a refusal). You can choose **a draft you approve on the page** before anything is sent, or **answering on its own**. In both cases the model has **no tool at all**: it can only write a reply following your instruction, the received message is treated as data, never as an order, and one person cannot trigger more than 20 replies an hour.
- **Solid**: the reading position is saved after each message (nothing is processed twice after a restart), the pairing code changes after each use and after five wrong tries, only private text messages are read, and a service outage is waited out with a growing delay. The token is never shown nor logged.

## Long missions: a big job for hours

Extensions > **Long missions**. You write a **specification** (“build me a complete game from this: code, tests, git repository”), pick the working folder, the maximum duration (8 h by default, 72 h at most) and whether Lutin is **autonomous**. Then you leave: Lutin carries the mission out **turn after turn, alone**, with all its tools (read, write, run commands and tests, commit), until it declares it is done.

- **The mission is your request.** Nothing is tailored to one kind of task: a game, a refactoring, a test suite, sorting documents… it all depends on what you write. For a long text, put it in a file of the folder and write “read this file and carry it out”.
- **Autonomous**: Lutin writes files and runs commands without asking, **in the chosen folder only**, with the usual safeguards (every modified file is backed up, commands are bounded). Text read from the internet suspends this automatic approval (a booby-trapped page cannot run a command): whatever is not approved is refused and the model knows it. **Unticked**, it is a dry run: it shows what it would do, nothing is written.
- **It keeps the thread**: the tracking sheet is forced (goal, plan, current step, done), the scribe keeps it up to date, the start of the conversation is archived and retrievable, the loop detector watches.
- **It stops** when the model calls `mission_terminer` (with its summary), when it needs a decision from you (`mission_bloquee`: one question, the mission waits for your answer), when time runs out, after three errors in a row (paused) or three answers in a row without any action (it asks for help).
- **You stay in control**: pause, resume, stop, an instruction added on the way (taken into account on the next turn), the “🎯 name” conversation to read and continue like any other. The two answer slots are shared: you can chat during the mission.
- **Resuming**: the state is written after every turn; if Lutin or the PC restarts, the mission picks up where it was.

The former “Background work” is now called **Document processing**: it applies an instruction to every document of a folder, read-only (summarise, sort, extract). Anything that codes, tests or changes files is a mission.

## Creating PDFs, Word documents, Markdown

The model has a `creer_document` tool: depending on the extension (`.pdf`, `.docx`, `.md`, `.txt`, `.html`, `.csv`) it writes the file in the working folder, after your approval, keeping a backup of the previous version. The content is simple Markdown (headings, paragraphs, lists, code blocks, separators, tables; bold, italic and code in Word). No library: the PDF (A4, numbered pages, standard fonts, accents kept) and the Word file are built by Lutin, then **read back** before being announced. A character outside the Latin alphabet (emoji, ideogram) becomes “?” in the PDF rather than breaking the file. No images, formatted tables or custom footers for now.

## Addons: optional features, one by one

New features arrive as **addons**: optional modules shipped with Lutin, **off until you turn them on** (Automation tab > *Optional extensions*). Each one has a setup guide (the steps to follow, with the fields to fill in), a **check** that must succeed before it can be enabled (the settings are right, the service answers as expected), and a **flow** (`flux.json`): the list of calls the addon makes to a service (address, method, fields, expected answer). The flow is data, not code, so it can change without touching Lutin.

- **Checked again every day.** If a service changes (new address, new format), the check fails and the addon shows *needs repair* instead of silently breaking.
- **Repair with Lutin's help.** The model reads the service documentation and proposes a corrected flow; you see the difference and accept (or not). The previous version is kept and the shipped one comes back in one click. Nothing is ever applied on its own.
- **Contained.** An addon can only reach the sites its shipped manifest declares: a corrected flow, even one inspired by a booby-trapped page, cannot send anything elsewhere. Secrets (tokens) are stored apart, never sent back to the page nor written in the log.
- **First addon: background work.** Applies one instruction to every document of a folder (PDF, Word, notes), one after the other, for hours if needed: read-only, resumable after a restart, with pause, a report, and a *regular* mode that only processes what is new. It yields to conversations (the document in progress is redone later), checks the PC's memory and space before each document, and stops after five errors in a row. The folder must already be one of your work folders.

## Long conversations: summary or tracking sheet

A small local model forgets a long conversation, or loops (\"shall we act?\" - \"yes\" - it plans everything again). Settings > **Long conversation memory** (and the **🧾 Tracking sheet** button, or `/memory`) offers two methods, switchable at any time, per conversation:

- **Automatic summary** (default): when the conversation nears the limit, the model summarizes the beginning. Nothing to manage, but each summary costs seconds to a minute of computing and loses details.
- **Tracking sheet**: one short sheet per conversation (goal, decisions, plan, current step, done, open questions, files touched, last requests), read again at every answer. The model updates it with the `suivi` tool and Lutin fills it by itself (requests, files), so even a model that forgets the tool leaves a usable sheet. You can read and edit it. A *yes* from you means **run the current step**: no new plan, no new question.

**Which one? Lutin asks you.** The default setting is **Ask at the first summary**: while the conversation is short nothing is asked; when it nears the limit, Lutin lets you choose between the two, with a box *keep this choice for the whole conversation* (without it the question comes back later). Scheduled tasks, which nobody can answer, use the summary. Switching to the sheet fills it from the start of the conversation (one model call).

**Nothing is really lost.** Neither method keeps every word in the model's window, but everything stays on disk: the summary archives the messages it removes (`data/archives/<conversation>.jsonl`), and the `rappeler` tool (with `ici=true` for this conversation only) finds a decision, a name or a figure again by keywords. Lutin tells the model it can do so, and its index only re-reads the files that changed.

**Two helpers so the thread is hardly ever lost.** (1) **Automatic recall of the thread**: before each answer, Lutin searches the *whole* conversation (kept messages and the start archived by the summary) for passages related to your request and puts them in front of the model, without it having to ask. A bare « yes » is completed with the last answer and the current step. (2) **The scribe**: every three answers or so, a short separate model call reads the latest exchanges and updates the sheet (new decisions, current step, what is done, open questions). It is checked (known keys, short lines, no duplicate, at most four lines added per section, a decision is never removed) and can be turned off in Settings if your machine is slow.

**Pinned messages.** The 📌 button under a message keeps it **always in front of the model**: it is never dropped when the context is trimmed, and the automatic summary leaves it as it is. Up to eight per conversation, and only within a quarter of the context window (a huge pinned message would otherwise choke the rest). Good for a rule (« never touch production »), a name, a constraint.

**Search by meaning (optional).** Word search does not find “detention” when you write “prison”. In Settings > Memory of long conversations, *Search by meaning* uses a small Ollama embeddings model (`nomic-embed-text`, about 270 MB, installable with one click from the page): every passage becomes a vector, and the conversation recall merges both rankings (words and meaning). Off by default; without the model or if Ollama does not answer, Lutin falls back to words without any error. Vectors are kept on disk (`donnees/embeddings/<conversation>.json`, deleted with the conversation) and vectorising is time-bounded on every answer.

**Loop detector.** If the model repeats the *same tool call* (same tool, same arguments) the third one is not run any more: it is told to move on, and at the fifth the answer stops. If it repeats its *previous answer almost word for word* (the same plan, the same request for confirmation), Lutin says so and, at your next request, orders the model to carry out the current step instead of re-planning.

Safeguards: the sheet is capped (lines per section, line length, at most 10 % of the context window by default, adjustable from 5 to 25 % in Settings > Long conversation memory; the page warns at seven tenths of that cap) so it cannot grow or slow every answer; it is placed just before your last question so the start of the conversation stays identical and Ollama keeps it in cache; it is stored in `data/suivis/<conversation>.md`, deleted with the conversation, and orphans are cleaned.

## Updating from the page and the icon

**Update now** (the banner, or Settings > Lutin version, or the icon's right-click menu) downloads and installs the new version, restarts Lutin and reloads the page. The command line stays available: `lutin update` (add `--app` for Lutin only). In Docker, update by pulling the image.

## Where things are: resizable columns and settings groups

Drag the line between the conversation list and the chat, or between the list and the options, to resize (double-click resets; arrow keys work too; remembered per device, off on small screens). Settings are grouped (General, Folders and data, Conversation, Machine and advanced settings), each group collapsible. The **Automation** tab holds scheduled tasks.

## Ollama models folder

Settings > Locations in use > **Change…** analyzes the chosen folder (network or local, measured write speed, free space), sets `OLLAMA_MODELS` (user variable on Windows) and Lutin's configuration, can **copy** the models already downloaded (verified; the old folder is never deleted), and **restarts Ollama** to apply it. Ollama alone decides where it reads its models: a network folder works but every load reads the model over the network (minutes for 17 GB on gigabit), and Ollama fails if the NAS is off. Prefer `\\server\share\folder` to a mapped drive letter.

## Models: suitability, families, disk space

In the Models tab each model carries a badge for **your machine**: *Very suitable*, *Suitable*, *Borderline* (fits barely, short conversation, or partly on the processor) or *Too big* (hover for the reason, with the memory it needs). Each family has a one-sentence explanation (for example why Qwen 3.8 exists next to Qwen 3: newer and better, but a single large size). A gauge shows the free space of the disk that holds the models, and a model that would not fit on it is flagged before you download it.

## Locations: where everything is

Settings > **Locations in use** lists every folder Lutin uses (program, configuration, data, memory, cache, Ollama models, workspace folders) with its size and the free space of its disk. The **Ollama models folder** can be changed there (models already downloaded are not moved).

## Workspace folders: what Lutin found

After you add a folder, Lutin says what it found and uses (files, CLAUDE.md, `skills/`, `.claude/`, copies of conversations). If the folder is **an old assistant** (conversations in `donnees/`, notes in `memoire/`), a *Take over its data…* button imports them: adding a folder only lets Lutin work in it, it does not copy the old conversations by itself. **Remove** asks for confirmation and can also delete the conversation copies Lutin put in that folder; your own files are never deleted.

## Finding new models

The Models tab has three ways to follow what comes out, none of which needs a new version of Lutin:

- **Check for updates** compares your installed models with their latest version in the Ollama registry.
- **Look for new models** reads the catalogue Lutin keeps online (checked once a day) and suggests better choices for your machine. The catalogue is a hand-written selection with a mark per role: it follows the new releases only when someone adds them (a weekly check also reports models that disappeared from the registry).
- **Ollama library** lists what ollama.com shows (newest or most popular, with a search box): name, description, abilities (tools, vision, thinking) and the available sizes, with an **Install** button per size. Nothing is installed without your click, and if the site changes or is unreachable the list says so and you can still install a model by its name.

## Modes

Settings > **Mode** (or `/mode` in the chat) changes what Lutin may do, and how it behaves. Every file change and every command still asks for your approval in every mode.

| Mode | Tools | When |
|---|---|---|
| **General** (default) | read, search, edit, commands, web, notes | everyday questions, writing, analysis, a bit of code |
| **Work** | everything, including code symbols | understand, modify and test the files of a folder |
| **Writing** | no commands; your documents and past conversations are recalled automatically | write, rephrase, search your documents |
| **Research** | read-only: read, search, web; recall on | read and cross-check files, PDFs and notes, answer with sources, change nothing |
| **Chat** | no tools | plain conversation, fastest |

## Access and devices

The **Access** tab gathers who can use Lutin (level), the PIN code with a **QR code** to connect a phone by scanning it, and the list of connected devices (with *Revoke*). A level change that needs a restart shows a banner with a *Restart* button when Lutin can do it itself (`lutin` command or Docker), and says what to do otherwise. Details: [SECURITY.md](SECURITY.md).

## Workspace folders and the default folder

Network folders (`\\server\share\folder`, a mapped drive, a NAS) work like any other: if one is refused, Lutin says why (the service account has no access, the share is off…). Use **Browse…** to pick a folder, **Move…** to move a folder (with its files) somewhere else (the same dialog lets Lutin just remember the new path when you moved the folder by hand). Settings also has a switch to keep a readable Markdown copy of every conversation in the working folder (`conversations-lutin/`).

Everything about folders is in Settings > **Workspace folders** (the sidebar has no folder selector any more, to leave room). The folder in use is marked ★ and is also the one Lutin opens at startup: **Use this folder** changes it, now and for the next starts. **Add a folder…** adds one and **Remove** takes any folder out of the list, the principal one included (the files are never deleted). Removing the folder in use switches at once to the next one; with no folder left, Lutin works in its default folder (`Lutin`, in your personal folder).

## Check for updates

Settings > **Lutin version** shows the installed version and a **Check for updates** button: it asks GitHub right away and says either « up to date » or which version is available (then a banner offers the update command). If GitHub cannot be reached, the real cause is shown (firewall, certificate, strict offline mode…); when the GitHub API is blocked, the public releases page is used instead. Lutin also checks by itself at startup, at most once a day. Nothing is installed without you.

## Icon in the notification area (Windows)

The **Lutin** shortcut opens Lutin **without a console window**: a Lutin icon in the notification area (bottom right). Left click opens the interface; right click offers **PIN code** (to connect a phone), **Open the interface**, **Restart** and **Quit**. On the very first start, the guided setup opens in a console. The server runs in the background; if it stops on an error it is restarted, and its output goes to `donnees/serveur.log` (the icon's own errors, if any, to `donnees/zone.log`). The terminal version stays available as `lutin` (and the « Lutin (terminal) » shortcut). Only one icon runs at a time: starting it again opens the interface.

## Commands in the chat

Type `/` for the list: `/pc`, `/essai`, `/acces`, `/sante`, `/model`, `/compact`… and the commands of a Claude project (`.claude/commands/*.md`, see [CLAUDE-PROJECTS.md](CLAUDE-PROJECTS.md)) are available too, with their arguments.
