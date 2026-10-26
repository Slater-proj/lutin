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

## Images

Click **📎** next to the message box, or paste (Ctrl+V) or drop an image: PNG, JPEG, GIF or WebP, 8 MB and 4 images per message at most. If the current model cannot see images, Lutin switches for that request to an installed model that can (see the « Images » role in the Models tab), or tells you there is none and ignores the images. Images stay in Lutin's data folder (`images/`), only the most recent ones are sent back to the model, and orphan images are deleted after two days.

## Access and devices

The **Access** tab gathers who can use Lutin (level), the PIN code with a **QR code** to connect a phone by scanning it, and the list of connected devices (with *Revoke*). A level change that needs a restart shows a banner with a *Restart* button when Lutin can do it itself (`lutin` command or Docker), and says what to do otherwise. Details: [SECURITY.md](SECURITY.md).

## Workspace folders and the default folder

Settings > **Workspace folders**: the folder Lutin opens at startup is marked ★ and can be changed with **Open at startup**. **Add a folder…** adds one and **Remove** takes it out of the list (the files are never deleted). Removing the folder in use switches at once to the next one; with no folder left, Lutin works in its default folder (`Lutin`, in your personal folder). The « + » beside the chat's folder selector is gone: adding is done in the settings only.

## Icon in the notification area (Windows)

The **Lutin** shortcut opens Lutin **without a console window**: a Lutin icon in the notification area (bottom right). Left click opens the interface; right click offers **PIN code** (to connect a phone), **Open the interface**, **Restart** and **Quit**. The server runs in the background; if it stops on an error it is restarted, and its output goes to `donnees/serveur.log`. The terminal version stays available as `lutin` (and the « Lutin (terminal) » shortcut). Only one icon runs at a time: starting it again opens the interface.

## Commands in the chat

Type `/` for the list: `/pc`, `/essai`, `/acces`, `/sante`, `/model`, `/compact`… and the commands of a Claude project (`.claude/commands/*.md`, see [CLAUDE-PROJECTS.md](CLAUDE-PROJECTS.md)) are available too, with their arguments.
