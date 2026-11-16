# The new interface: state

Plan step 4 ([PLAN.md](PLAN.md), [ADR 0002](../adr/0002-frontend-svelte-typescript-vite.md)). Sources in `frontend/`, served under `/app/`; the present page at `/` stays the default.
This page says what exists, what was verified and how, and what is missing. It is updated with each screen.

## Foundation

| Piece | State |
|---|---|
| Project (Svelte 5, TypeScript, Vite), build into `src/lutin/web/app/` | done |
| Served by Lutin under `/app/`, session required, strict content security policy | done — `tests/test_web_app.py` |
| A shipped build that no longer matches its sources is detected | done — same hash computed by the build and by Python |
| Built by the CI before tests and packaging; wheel checked for the built files | written, **never run**: the branch has not been pushed |
| Design tokens, light and dark themes, theme kept per browser | done |
| Shell with the five areas (Chat, Agents, Projects, Models, Settings), icons, navigation bar at the bottom on a phone | done; all five areas exist (some only in part: see each one) |
| Texts in English and French | done — a unit test fails on a missing French text |
| Base components (button, card, field…) as shared components | not yet: styles are shared classes, components come with the second screen |
| Offline: no font, no CDN, nothing fetched from another origin | done — enforced by the policy |

## First launch

Verified in Chrome against the fake engine and a fictive machine and disk (`tests/test_web_app_chat.py`, tests 5e and 5f), with automatic accessibility checks on every step.
Shown **after the first installation on a new machine** (the maintainer's rule); an installation that already lives is never taken for a new one (see [API_V1.md](API_V1.md), « First launch »).

| Step | State |
|---|---|
| Welcome: what Lutin is, three promises (everything local, it asks before it acts, nothing is installed or downloaded without agreement), « skip, I will set it up myself » | done |
| Engine: found and running; installed and stopped → « Start »; missing → « Install » with a confirmation that says what it does (the reason given by the engine); refused in strict offline mode; failure shown with the way to do it by hand | done on the engines routes; the real installation of Ollama is **not tried** (the tests never install a program) |
| Model: the guide of the Models screen, then the downloads in progress | done |
| End: the chat opens; a download goes on in the background | done |
| Language choice (French, English, like the system) on the first screen | done |
| Correction of the detected machine: the memory models may fill, in the guide (« this is not my machine ») | done — only that figure; the detected hardware itself is not editable |
| The optional speed test (yes/no) at the end, Ollama only | done |
| Pairing a phone: a card at the end of the guide (code, address, QR code); at the level « this machine only » it says why no device can reach Lutin | done |

A real finding on the way: the models folder of the development machine is on a disk with 4.7 GB free, and the guide refused a 5.2 GB download with « not enough free space »: the safeguard works on real hardware.

## Settings

Every setting of `/api/v1/settings` in six groups (answers, safety, web and memory, this machine, tools, sampling), each kept as soon as it is changed: a switch, a choice, a number (checked against its range before it is sent), a list (one line per item). What removes a question (writing or running without asking, commands always allowed) is marked « take care ». Language is chosen here too. Verified in Chrome (`tests/test_web_app_chat.py`, test 5h) and by the automatic accessibility checks in both themes and at 360 px.
Also on this screen: the paired devices (list, remove, pair with a code and a QR code drawn in SVG) and the approval rules for commands (list, add, remove, what always needs an approval). The notification channels (Gotify, ntfy, Telegram, webhook; the secrets are never shown again) are here too. So are the two notes the model always has (context, memory) and the skills (sheets of your own: write, change, delete; test 5s). Not on this screen yet: the access level itself (it needs a restart: present page).

## Agents

The scheduled tasks: the list with when, the next run, the state of the last one and its ten last runs; add a task (a name, what Lutin should do, a time, days of the week or one date); run it now, stop it, pause and resume it, delete it (with a confirmation). The list is read again every five seconds. Managing is for the machine itself. A task can be changed (the form is filled with it) and can name the channel that is told when it ends. Verified in Chrome (test 5j) and by the accessibility checks.
The missions (test 5q): list with state, turns, actions, recent activity and report, start (name, brief, project, longest duration, autonomous or dry run), pause, resume, answer the question of a blocked mission, stop and delete (both with a confirmation); the progress is read again every five seconds. Starting and deleting are for the machine itself; following, pausing, answering and stopping are open to a paired device.
The add-ons (test 5p): their settings drawn from each manifest, secrets kept and never shown, check, turn on and off. The connectors (MCP, test 5o): add, refresh the tools, allow them one by one, remove. The catalogue of ready-made connectors (test 5t, `GET /mcp-catalog`, `POST /mcp-catalog/{id}/install`): set up with the values an entry asks for; a missing program to download waits for a confirmation; the connector is tried at once and only its read-only tools are allowed.
The live panel of an add-on (test 5r) is under it once it is on: Telegram (pairing code, paired phones, replies waiting to be sent or thrown away), mail (replies waiting) and X (write, edit, schedule, publish posts, replies). ComfyUI has no panel here yet.
Missing: the flow editor and the correction proposal of an add-on, the ComfyUI panel, and the third-party skills.

## Projects

The working folders: list with the one in use, « use this folder », add by path, remove from the list (nothing is deleted), with the reason shown for a folder that cannot be used. Adding and removing is for the machine itself. Verified in Chrome (test 5i) with the accessibility checks. The folder browser goes down folder by folder from the home, documents and drives (machine itself only). Missing: moving a folder, the import of a Claude project and the take-over of another assistant's data.

## Models

First version, on the v1 routes that exist (list, install, delete, setting of the model in use), verified in Chrome against the fake engine (`tests/test_web_app_chat.py`, test 5b):
the engine state, the installed models with their size, the one in use, « use » and « delete » (with a confirmation), a download by name with its progress (the list is read again every second while something downloads), a failed download with its reason.

| Present page | New interface |
|---|---|
| Installed models, use, delete | done |
| Download by name, progress | done |
| Recommended models for this machine (catalogue, fit verdict, compatibility with the engine) | **missing**: needs a v1 route and a design (several engines, verdicts from `model_fit` and `model_compat`) |
| Choice and start of an engine, engine installation | done: an « Engines » tab (state, in use, start, stop, install, update, reinstall, uninstall with a confirmation that says what it does, the task in progress with its progress and a cancel); verified in Chrome (test 5k) against the fake engines, nothing is installed by the tests |
| Search a model on Hugging Face, quantisations, models of other machines | missing |
| Onboarding with hardware detection and a recommended configuration (plan step 4) | missing |

A beginner must not have to know the name of a model: the catalogue with its verdicts is the next piece of this screen.

## Chat

Verified end to end in a real Chrome against a fake engine (`tests/test_web_app_chat.py`): page loads without any policy violation; a message is sent and
the answer is written as it arrives; Markdown is drawn and no HTML comes out of an answer; an action waits for an approval given on the page and a refusal leaves the file untouched;
a document and an image are attached, sent, shown in the message and kept when it is edited; a conversation is renamed and pinned; the options are chosen before or after the first message and kept by the server for that conversation only; a message is edited and the conversation goes on from it; a refusal of the server is shown and the message
given back; themes; no overflow at 360 px.

Accessibility: the automatic checks of axe-core (WCAG 2.0, 2.1 and 2.2, levels A and AA, contrast included) run in `tests/test_web_app_chat.py` on the Chat screen, a conversation, the options panel, the Models screen and
a screen not built yet, in the light and the dark theme, and on Chat and Models at 360 px: **no violation**. The checker is proven by planting an image without text and an unreadable button, which it must find.
It found one real defect on the way (the model list had no accessible name at 360 px), now fixed.
What an automatic tool cannot judge is **not verified**: reading order and wording for a screen reader (never tried with one), keyboard-only use end to end (the controls are real buttons and fields, but no test walks the page with the Tab key),
colour use beyond contrast, and the quality of the texts. Not verified either: a real engine, a real phone, other browsers than Chrome.

| Present page | New interface |
|---|---|
| List, open, create, delete a conversation | done |
| Send a message, answer written as it arrives, stop | done |
| Reasoning, tool calls and results, notices, dry runs, errors | done |
| Approval of an action, with its diff | done; a command offers « once », « for this conversation », « always » ([ADR 0009](../adr/0009-approval-rules.md)) |
| « Summary or progress sheet » question of a long conversation | done (the route is tested; the card has no end-to-end test) |
| Choice of the model | done (changes the setting, as the present page does) |
| Context gauge, speed, task list | done, during the turn only |
| Markdown in answers: headings, lists, tables, quotes, links, code blocks with a copy button | done — own parser (`frontend/src/lib/markdown.ts`), no HTML ever interpreted |
| Syntax colouring of code (`frontend/src/lib/highlight.ts`: comments, strings, numbers, keywords of about twenty languages, no dependency) | done |
| Diagrams (Mermaid), formulas | missing |
| Rename, pin a conversation | done |
| Edit a message and answer again from it | done |
| Images and attached documents | done: file dialog, paste of a picture, drop on the field; sent, shown in the message, kept when the message is edited. A sent document is a link that downloads it again; when the model cannot see images, the agent switches to one that can and says so in the thread (a notice). |
| Per-conversation options: mode, reasoning, web, dry run, automatic approvals, mission duration | done — a panel beside the field; an approval that is on stays visible while the panel is shut |
| Conversations led on another machine | missing (not in v1 yet) |
| Reconnecting to a turn still running after a reload | done in a simple way: the page says an answer is still being written, offers Stop, and shows it when it is stored (it does not show the pieces as they are written) |

This list comes from the routes the present page calls for a conversation; it is not yet a complete audit of the present page, which the acceptance of the
screen requires (plan step 4: « functional parity with the old page listed and checked »).
