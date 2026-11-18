# Parity of the new interface with the old page

Audit of 2026-11-17 (on `98ebd28`): every user-visible feature of the old page (`src/lutin/web/index.html`, 189 French routes) checked against the
new interface (`frontend/src`) and `/api/v1`, by reading the code. Decided by the maintainer the same day: at 1.0 the new interface becomes the
default at `/`, the old page stays reachable at `/ancienne/` during 1.x, and goes in 2.0. This list is what the new interface needs before that
switch; each line is ticked here when it is done, with its test.

## Missing or partial, by importance to the person

1. ~~**Undo the file changes of the last request**, and the file-by-file review with an undo per file~~ — done: `GET /conversations/{id}/changes`,
   `POST /conversations/{id}/changes/undo` (`tests/test_api_v1_changes.py`), `components/Changes.svelte` in the Chat (test 3k).
2. ~~**Health**: memory, graphics card and disk, what is loaded, unload the models, free the graphics memory, « check that everything works » and
   the full self-test, what left this machine (outbound web searches) and clearing that log~~ — done: `/api/v1/health…` (`tests/test_api_v1_health.py`),
   the section « Health » of Settings (`components/Health.svelte`, test 3l). Left: the health light on Settings in the navigation.
3. ~~**Back up and restore** the data as a `.zip`, and the path of the data folder~~ — done: `/api/v1/backup…` (`tests/test_api_v1_backup.py`; downloading
   now needs `configurator`, a paired phone could before), the section « Data » of Settings (`components/Backup.svelte`, test 3m). Left: the take-over of
   another assistant's data; moving a work folder.
4. ~~**Search the conversations** (with extracts), and the markers in the list (working, waiting for you, finished and unread)~~ — done:
   `GET /conversations?q=` on the full-text index (`tests/test_api_v1_search.py`), the search field and the marks of the Chat (`lib/marks.ts`, test 3n).
   Left: the tab badge.
5. ~~**Answer actions**: copy a whole answer, regenerate, the generated images and the produced files in the thread (open, download, delete)~~ — done:
   « Copy » and « Answer again » under the answers (test 3o); `GET /conversations/{id}/files/{file}`, `POST …/files/{file}/open`,
   `DELETE …/files/{file}`, `DELETE /conversations/{id}/media/{image}` and the relayed download for a conversation held by another machine
   (`tests/test_api_v1_produced.py`), `components/Produced.svelte` under each tool result (test 3p).
6. ~~**Lutin's own version**: check and update, the new-version and restart banners, « Restart Lutin »~~ — done: `new_version` and `restart` in
   `GET /status`, `/api/v1/lutin/check`, `…/ignored-version`, `…/update`, `…/restart` (`tests/test_api_v1_lutin.py`), the banners of the shell
   (`components/LutinBanners.svelte`) and « Lutin's version » in Settings › General (`components/LutinVersion.svelte`, test 3q). The restart is now
   also asked after a backup is put back and after an update installed with nothing to restart Lutin, on the old page as well.
7. ~~**The strict offline switch.**~~ — done: `GET`, `POST` (session) and `DELETE` (configurator, as on the old page) `/api/v1/offline`
   (`tests/test_api_v1_offline.py`), « Strict offline mode » in Settings › Safety (`components/Offline.svelte`), its mark in the navigation and the
   « Web » option of the Chat greyed while it is on (test 3r).
8. ~~**Web search setup**: engine order, SearXNG, keys, « test the search »~~ — done: `GET`, `PATCH` (configurator) `/api/v1/web-search` and
   `POST /api/v1/web-search/test` (`tests/test_api_v1_web_search.py`), « Web search » in Settings › Knowledge (`components/WebSearch.svelte`, test 3s).
9. ~~**Access**: the access level, remote administration, disconnect every device~~ — done: `GET /api/v1/access`, `PATCH /api/v1/access` and
   `PATCH /api/v1/access/remote-admin` (right `local`: this machine only, never a paired device nor the remote administration itself;
   `tests/test_api_v1_access.py`), « Access » in Settings › Devices (`components/Access.svelte`) and « Disconnect every device » on the existing
   `DELETE /api/v1/devices` (test 3t).
10. ~~**Model upkeep**: update checks and proposals (including removing obsolete models), precision variants, benches and their comparison,
    the Ollama library, the speed test outside the first launch, the model pages of Colibri, LM Studio and ExLlamaV3~~ — done:
    `GET /api/v1/models/proposals`, `POST /api/v1/models/check`, `POST …/proposals/{key}/applied`, `DELETE …/proposals/{key}`,
    `GET /api/v1/models/variants`, `GET /api/v1/models/library` (`tests/test_api_v1_model_upkeep.py`), `components/ModelProposals.svelte`,
    `ModelVariants.svelte` and `OllamaLibrary.svelte` (test 3u); `GET`/`POST /api/v1/bench` and `/api/v1/engines/comparison`
    (`tests/test_api_v1_bench.py`), the « Measures » tab with the speed test (`components/Measures.svelte`, test 3v);
    `/api/v1/managed-servers/{id}/models|catalog|quantizations|check|downloads` on `lutin.managed_models`, shared with the old page
    (`tests/test_api_v1_managed_servers.py`), `components/ManagedModels.svelte` (test 3w).
11. ~~**Engine settings** (pinned version, ports, address and key of an OpenAI-compatible server, llama.cpp advanced and router, folders), engine
    measures, moving the models folder, calibration and load profile~~ — done: `GET`/`PATCH /api/v1/engines/{id}/settings` (on
    `llamacpp_engine.apply_settings`, shared with the old page), `/api/v1/engines/folder`, `/api/v1/engines/measures` and `POST …/{id}/measure`,
    `/api/v1/models/folder` (analysis, copy, choice, restart of Ollama), `/api/v1/calibration`, `/api/v1/machine/advice`
    (`tests/test_api_v1_engine_settings.py`); `components/EngineSettings.svelte` in each engine's card, `EngineFolders.svelte`, the measure of an
    engine in the « Measures » tab and `MachineTuning.svelte` in Settings › Machine (test 3z).
12. ~~**Conversation tools**: export as Markdown, AI summary, the progress sheet (view, edit, delete) and the memory mode of one conversation, open
    its folders, Git (diff, proposed message, commit), the action log, the mission banner inside the conversation~~ — done:
    `/api/v1/conversations/{id}/memory` (GET, PATCH; `DELETE …/memory/sheet`), `POST …/handover` (on `agent.document_de_reprise`, shared with the
    old page, which now uses the engine in use and not only Ollama), `…/folders` and `…/folders/open`, `/api/v1/git`, `/git/message`, `/git/commit`
    (configurator, stricter than the old page), `/api/v1/actions-log` (`tests/test_api_v1_conversation_tools.py`); « Tools » in the Chat
    (`components/ConversationTools.svelte`, the export in `lib/export.ts`), the mission banner, and `ProjectGit.svelte` on the Projects screen
    (test 3za).
13. ~~**Document processing in the background.**~~ — done: `/api/v1/background-jobs` (GET; POST, `POST …/{id}/{pause|resume|restart|validate}`
    and DELETE for this machine; `GET …/{id}/report`; `tests/test_api_v1_background_jobs.py`), the « Background work » tab of the Agents screen
    (`components/BackgroundJobs.svelte`, test 3zb).
14. ~~**Documents** of the workspace (list, search), notes one by one, the button that installs the embeddings model~~ — done: `GET
    /api/v1/documents`, `/documents/search`, `/notes` (GET, POST, DELETE), `/search-by-meaning` and `…/install`
    (`tests/test_api_v1_documents_notes.py`), « Documents and notes » in Settings › Knowledge (`components/Documents.svelte`, test 3zc). Found on
    the way: a note added while MEMOIRE.md had no notes section was never listed nor re-read; `storage.noter` now creates the section.
15. ~~**Slash commands** (and the commands of a Claude project), the **Ctrl+K palette**, the queue of messages sent while an answer runs~~ — done:
    `POST /api/v1/conversations/{id}/compact`, `/api/v1/project-commands` and `…/{name}` (`tests/test_api_v1_slash.py`); the commands in
    `lib/slash.ts` (the old French names kept as aliases, `//` sends a slash), suggested and carried out in the Chat, `/help`; the queue of messages
    typed during an answer; `components/Palette.svelte` (test 3zd).
16. ~~**Settings without a control** though v1 has them: `auxiliary_model`, `progress_sheet_share`, `progress_sheet_scribe`; the maximum length of
    one conversation's answers~~ — done: the three fields in `lib/settings.ts` (General and Knowledge, test 5h) and « Longest answer » in the options
    of a conversation (test 3d).
17. ~~**Files created by Lutin**, the locations used and their sizes~~ — done: `/api/v1/created-files`, `…/delete`, `…/{id}/open-folder` and
    `/api/v1/locations` (configurator: paths of this machine; `tests/test_api_v1_created_files.py`), « Files and locations » in Settings › Data
    (`components/Storage.svelte`, test 3ze).
18. ~~Small gaps: MCP demo server, changing a connector's keys, uninstalling helper programs; a scheduled task's work folder and « see the result »;
    pinning one message, « Verify » (web sources), timestamps; the « accept and re-enable the automatic approval » choice after a web read; the
    « start Ollama » button and the diagnostic actions on the stopped-engine banner; recalling earlier inputs~~ — done: `POST
    /api/v1/mcp-connectors/demo`, `/api/v1/helper-programs` (GET, install, DELETE), `PATCH /api/v1/conversations/{id}/messages/{index}` (pin),
    `POST /api/v1/web-search/preview` (`tests/test_api_v1_small_gaps.py`); in the page: the demonstration connector and « Change its keys »,
    `HelperPrograms.svelte` in Settings › Tools, a task's work folder and « See the result », « Pin », the time and « Verify » in the thread,
    « Accept and allow again without asking », « Start <engine> » and « Check the machine » on the stopped-engine banner, ↑/↓ in an empty box
    (test 3zf; the engine banner and the task's result link are not covered by a browser test).

## The switch

Done on 2026-11-18, every item above being ticked: `/` serves the new interface when it is built (a copy without a build keeps the old page there),
the old page is at `/ancienne/` (its libraries by absolute paths, its link « Back to the new interface »), `/app/` keeps working, and the old page's
direct links (`/#conv=<id>`, `/#modeles`…) lead to the same place in the new one (`lib/address.ts`, `fromLegacy`). Tests: `tests/test_web_app.py`
(the switch), the old page's browser tests now open `/ancienne/`.

## Present

Conversations (list, open, new, delete, rename, pin, edit a message and go on, options, approvals, memory choice, images and documents,
conversations held by another machine), the model selector with other machines' models, the first launch and the model guide, the catalogue,
installed models and downloads, engines, the Machines tab and lending this machine, Settings in sections, work folders, the Claude project import,
scheduled tasks, missions, add-ons and their panels, MCP connectors and their catalogue, notification channels, the two notes, skills and
third-party skills, paired devices and the pairing code, direct links.

## Superseded, not to redo

The resizable sidebar (the new layout), the hand-kept model list (« remove from the list », « restore the original list »: the catalogue replaces
it). These are inferences of the audit; the maintainer may say otherwise.
