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
3. **Back up and restore** the data as a `.zip`, and the path of the data folder; the take-over of another assistant's data; moving a work folder.
4. **Search the conversations** (with extracts), and the markers in the list (working, waiting for you, finished and unread), the tab badge.
5. **Answer actions**: copy a whole answer, regenerate, the generated images and the produced files in the thread (open, download, delete).
6. **Lutin's own version**: check and update, the new-version and restart banners, « Restart Lutin ».
7. **The strict offline switch.**
8. **Web search setup**: engine order, SearXNG, keys, « test the search ».
9. **Access**: the access level, remote administration, disconnect every device.
10. **Model upkeep**: update checks and proposals (including removing obsolete models), precision variants, benches and their comparison, the
    Ollama library, the speed test outside the first launch, the model pages of Colibri, LM Studio and ExLlamaV3.
11. **Engine settings** (pinned version, ports, address and key of an OpenAI-compatible server, llama.cpp advanced and router, folders), engine
    measures, moving the models folder, calibration and load profile.
12. **Conversation tools**: export as Markdown, AI summary, the progress sheet (view, edit, delete) and the memory mode of one conversation, open
    its folders, Git (diff, proposed message, commit), the action log, the mission banner inside the conversation.
13. **Document processing in the background.**
14. **Documents** of the workspace (list, search), notes one by one, the button that installs the embeddings model.
15. **Slash commands** (and the commands of a Claude project), the **Ctrl+K palette**, the queue of messages sent while an answer runs.
16. **Settings without a control** though v1 has them: `auxiliary_model`, `progress_sheet_share`, `progress_sheet_scribe`; the maximum length of
    one conversation's answers.
17. **Files created by Lutin**, the locations used and their sizes.
18. Small gaps: MCP demo server, changing a connector's keys, uninstalling helper programs; a scheduled task's work folder and « see the result »;
    pinning one message, « Verify » (web sources), timestamps; the « accept and re-enable the automatic approval » choice after a web read; the
    « start Ollama » button and the diagnostic actions on the stopped-engine banner; recalling earlier inputs.

## Present

Conversations (list, open, new, delete, rename, pin, edit a message and go on, options, approvals, memory choice, images and documents,
conversations held by another machine), the model selector with other machines' models, the first launch and the model guide, the catalogue,
installed models and downloads, engines, the Machines tab and lending this machine, Settings in sections, work folders, the Claude project import,
scheduled tasks, missions, add-ons and their panels, MCP connectors and their catalogue, notification channels, the two notes, skills and
third-party skills, paired devices and the pairing code, direct links.

## Superseded, not to redo

The resizable sidebar (the new layout), the hand-kept model list (« remove from the list », « restore the original list »: the catalogue replaces
it). These are inferences of the audit; the maintainer may say otherwise.
