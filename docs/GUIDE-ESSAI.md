**English** · [Français](GUIDE-ESSAI.fr.md)

# Trying Lutin 0.8 step by step

A walk-through of about 45 minutes to check, on your machine, what is new. Each step says **what to do**, **what you should see**, and **what to do if you do not**. Everything can be undone: nothing is written outside the trial folder you pick in step 0.

The following features have only been tested against fake services (fake Telegram API, fake Ollama…): this walk-through is the first real contact. If a step fails, paste the output of `lutin doctor` (no personal content) in a problem report.

## 0. Prepare a trial folder

1. Create an **empty** folder, for example `C:\lutin-trial`.
2. In Lutin: *Settings > Working folders > Add*, pick it, then press *Use* to make it the active one.

*You should see* its name in the sidebar. *Otherwise*: the folder must exist and be readable by your Windows account; Lutin says so in one sentence.

## 1. The extensions menu is fast

**Automation** tab: the *Optional extensions* section must appear in **under a second**, even when ComfyUI is off (it was 5 to 12 s before 0.8.0).

*If it is slow*: note whether ComfyUI is enabled, then open `donnees/serveur.log`; a service that does not answer is tried once, not six times.

## 2. A PDF and a Word document

In a conversation (*General* mode), write:

> Write a short meeting summary as a PDF, then the same as a Word document. Title, three points, a list of actions. In the trial folder.

*You should see*: Lutin asks for your approval for each file (a window with the name and size), then **one card per file under the message**: name, size, path, and the **Open**, **Download**, **Delete** buttons.

- **Open**: your PDF reader and Word open as after a double-click. Check the accents (é, à, œ, « »).
- **Download**: the file lands in your downloads folder under its real name.
- **Delete**: confirm; the card disappears and so does the file from the disk.

*Known limits*: no images or formatted tables in the PDF; an emoji becomes “?”.

## 3. An image with ComfyUI

1. *Automation > Optional extensions > ComfyUI*: tick the box. Lutin looks for ComfyUI by itself. If the panel says “✔”, carry on; otherwise *Choose the folder…* (the one that contains `main.py`).
2. Ask: *Generate an image of a lighthouse in the fog.*

*You should see*: the approval, then ComfyUI starting **by itself** (the language model hands over the memory), then **the image right in the conversation**, with its path below, **Download** and **Delete**. A click on the image opens it full size in a tab. ComfyUI then closes.

*If it fails*: the message must now name the **faulty node** (“Node 4 (CheckpointLoaderSimple): Value not in list…”) and the exception. Paste it in the conversation: the model knows what to fix. A `diffusion_models` model (Flux, Qwen-Image, Z-Image) uses its family's workflow; “unknown family” means you must set the model in the addon's settings.

## 4. Check how a page renders

In the trial folder, ask: *Create a page `trial.html` with a title and a button that shows the time, then check it with a preview.*

*You should see*: the approval, then the **screenshot** in the conversation, and the model quoting the displayed text. To test errors, then ask: *Add a call to a function that does not exist and preview again*: it must report “Uncaught ReferenceError … is not defined”.

*If “No browser…”*: install Chrome or Edge, or put the executable's path in the `LUTIN_NAVIGATEUR` environment variable.

## 5. A first, short mission

*Automation > Optional extensions > Long missions*: tick the addon, then *New mission*.

- **Name**: `Trial`
- **Folder**: the trial folder
- **Maximum duration**: `1` hour
- **Specification**: *Build a small “rock-paper-scissors” game in a single HTML file, with a Python test file that checks the rules. Run the tests. When everything passes, finish the mission with a summary.*
- **Autonomous**: **unticked** the first time (dry run: Lutin shows what it would do, nothing is written).

*You should see*, turn after turn (the panel updates by itself): the state, the number of turns and actions, then a **summary**. The “🎯 Trial” conversation tells everything, step by step.

Then start again with **Autonomous ticked**: this time Lutin writes the files and runs the tests by itself, in that folder only. At the end, look at the folder: the game and its tests must be there.

While it runs, try:
- **Add an instruction** (“put the score at the top”): taken into account on the next turn.
- **Pause**, then **Resume**.
- **Quit Lutin** (notification-area icon > Quit), start it again: the mission resumes where it was.

*If the mission stops with “I am stuck…”*: the model answered three times without doing anything. Answer its question, or make the specification more precise. *If it pauses after three errors*: the message says which (model stopped, disk full…).

**For a real overnight mission**: a precise specification (what is expected, how to test it, what makes the work “done”), a folder of your own, a duration of 8 to 12 h, a model that can use tools (see *Models*), and the PC's sleep mode turned off.

## 6. Find a passage by meaning

1. *Settings > Memory of long conversations*: tick **Search by meaning**, then **Install** (about 270 MB, with a progress indicator).
2. In a long conversation (or the one from step 5), talk about a subject with one word, then later ask a question with a **synonym** (“prison” then “detention”).

*You should see*: the passage found in the automatic recall of the thread. *Without the model installed*, or if Ollama is off, Lutin falls back to word search, with no error.

## 7. Long-conversation safeguards

- **Pin**: under a message, *📌 Pin*; it stays in front of the model even when the context is trimmed.
- **Loop detector**: if the model repeats the same call five times, the answer stops with “The model is going round in circles”.
- **Tracking sheet**: at the first summary, Lutin asks *tracking sheet or summary*. The sheet is readable and editable.

## 8. Telegram, mail, X (if you use them)

Each addon has its steps in its card and a **Check** button: it really tests the service and says what is missing. Enable them one by one. These three addons had never talked to the real services before your trial: report anything unexpected.

## Starting over

- Delete a created file or image: the **Delete** button on its card.
- Delete a mission: *Delete* on its card (the conversation stays in the list).
- Disable an extension: untick its box; its settings are kept.
- Wipe everything: delete the trial folder and its conversations; nothing else was touched.
