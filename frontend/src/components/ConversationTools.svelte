<script lang="ts">
  // The panel « This conversation » of the Chat (docs/modernization/PARITY.md, item 12; the « ⋯ » menu of the old page): the files it created
  // (download, open their folder, delete after a second click), its folders on this machine, its progress sheet read, edited or deleted, the
  // conversation saved as Markdown, and a handover document written by the model. Each part says what it is for (maintainer, 2026-11-22: « je ne
  // sais pas à quoi sert le bouton »).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { copyText } from "../lib/clipboard";
  import { exportName, toMarkdown, type ExportedMessage } from "../lib/export";
  import { formatBytes } from "../lib/format";
  import { language, t } from "../lib/messages";
  import { imageUrl, producedFileUrl } from "../lib/place";

  type Memory = { mode: string; own_mode: string | null; general_mode: string; text: string; measure: { lines: number; tokens: number; level: string; warning: string }; first_request: string | null };

  type Created = { id: string; kind: string; name: string; path: string; size_bytes: number; date: number };

  let { conversation, title, messages, canConfigure, onchanged }: { conversation: string; title: string; messages: ExportedMessage[]; canConfigure: boolean; onchanged?: () => void } = $props();

  const lang = language();
  let files = $state<Created[] | null>(null);
  let deletingFile = $state("");
  let where = $state(""); // the part where the last notice or problem belongs, so that it is shown next to the button that was pressed

  let memory = $state<Memory | null>(null);
  let sheet = $state("");
  let editing = $state(false);
  let deleting = $state(false);
  let handover = $state("");
  let folders = $state<{ path: string; role: string }[] | null>(null);
  let canOpen = $state(false);
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const base = $derived("/conversations/" + encodeURIComponent(conversation));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>, part = ""): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    where = part;
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function shown(answer: Memory): void {
    memory = answer;
    sheet = answer.text;
  }

  function save(name: string, text: string): void {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  const saveSheet = (): Promise<void> =>
    act(async () => {
      shown(await api<Memory>("PATCH", base + "/memory", { sheet }));
      editing = false;
      notice = t("web.saved");
    });
  const deleteSheet = (): Promise<void> =>
    act(async () => {
      shown(await api<Memory>("DELETE", base + "/memory/sheet"));
      deleting = false;
    });
  const writeHandover = (): Promise<void> =>
    act(async () => {
      notice = t("tools.handover_writing");
      handover = (await api<{ text: string }>("POST", base + "/handover", {})).text;
      notice = "";
    });
  const openFolder = (path: string): Promise<void> =>
    act(async () => {
      await api("POST", base + "/folders/open", { path });
      notice = t("tools.folder_opened");
    }, "folders");
  const openFileFolder = (id: string): Promise<void> =>
    act(async () => {
      await api("POST", "/created-files/" + encodeURIComponent(id) + "/open-folder", {});
      notice = t("tools.folder_opened");
    }, "files");
  const loadFiles = async (): Promise<void> => {
    files = (await api<{ files: Created[] }>("GET", "/created-files?conversation=" + encodeURIComponent(conversation))).files;
  };
  const deleteFile = (id: string): Promise<void> =>
    act(async () => {
      const done = await api<{ deleted: number; skipped: string[] }>("POST", "/created-files/delete", { ids: [id] });
      deletingFile = "";
      notice = done.skipped.length ? done.skipped.join(" ; ") : t("tools.file_deleted");
      await loadFiles();
      onchanged?.();
    }, "files");

  onMount(() => {
    api<Memory>("GET", base + "/memory").then(shown, (cause) => (problem = explain(cause)));
    if (canConfigure) {
      api<{ folders: { path: string; role: string }[]; can_open: boolean }>("GET", base + "/folders").then((answer) => ((folders = answer.folders), (canOpen = answer.can_open)), () => (folders = []));
      loadFiles().catch(() => (files = []));
    }
  });
</script>

{#snippet said(part: string)}
  {#if where === part}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>
  {/if}
{/snippet}

<section class="conversation-tools" aria-labelledby="tools-title">
  <h2 id="tools-title">{t("tools.title")}</h2>
  <p class="intro">{t("tools.intro")}</p>
  {@render said("")}

  {#if canConfigure}
    <div class="part">
      <h3>{t("tools.files")}</h3>
      {#if files && files.length}
        <ul class="files">
          {#each files as file (file.id)}
            <li>
              <span class="name">{file.name}</span> <span class="muted">{formatBytes(file.size_bytes, lang)} · {new Date(file.date * 1000).toLocaleDateString(lang)}</span>
              <span class="actions">
                <a class="button quiet" href={file.kind === "image" ? imageUrl("", file.id) : producedFileUrl("", conversation, file.id, file.name)} download={file.name}>{t("produced.download")}<span class="visually-hidden"> {file.name}</span></a>
                {#if canOpen}<button type="button" class="button quiet" disabled={busy} onclick={() => openFileFolder(file.id)}>{t("tools.file_folder")}<span class="visually-hidden"> {file.name}</span></button>{/if}
                {#if deletingFile === file.id}
                  <span>{t("tools.file_delete_confirm", file.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => deleteFile(file.id)}>{t("upkeep.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (deletingFile = "")}>{t("chat.cancel")}</button>
                {:else}
                  <button type="button" class="button quiet danger" disabled={busy} onclick={() => (deletingFile = file.id)}>{t("tools.file_delete")}<span class="visually-hidden"> {file.name}</span></button>
                {/if}
              </span>
            </li>
          {/each}
        </ul>
      {:else if files}
        <p class="muted">{t("tools.files_none")}</p>
      {/if}
      <p class="muted"><a href="#/settings/storage">{t("tools.files_everywhere")}</a></p>
      {@render said("files")}
    </div>

    <div class="part">
      <h3>{t("tools.folders")}</h3>
      <p class="muted">{t("tools.folders_help")}</p>
      {#if folders?.length}
        <ul>
          {#each folders as folder (folder.path)}
            <li><span class="muted">{t(("tools.folder." + folder.role) as "tools.folder.work")}</span> <code>{folder.path}</code>
              {#if canOpen}<button type="button" class="button quiet" disabled={busy} onclick={() => openFolder(folder.path)}>{t("tools.folder_open")}</button>{/if}</li>
          {/each}
        </ul>
      {:else if folders}
        <p class="muted">{t("tools.folders_none")}</p>
      {/if}
      {@render said("folders")}
    </div>
  {:else}
    <p class="muted">{t("tools.only_here")}</p>
  {/if}

  {#if memory}
    <div class="modes">
      <h3>{t("tools.memory")}</h3>
      <p class="muted">{t("tools.memory_help")}</p>
    </div>
    {#if memory.first_request}<p class="muted">{t("tools.first_request", memory.first_request)}</p>{/if}

    <div class="part">
      <h3>{t("tools.sheet")}</h3>
      <p class="muted">{t("tools.sheet_help")}</p>
      {#if memory.measure.warning}<p class="warn">{memory.measure.warning}</p>{/if}
      {#if editing}
        <label class="visually-hidden" for="sheet-text">{t("tools.sheet")}</label>
        <textarea id="sheet-text" rows="14" bind:value={sheet}></textarea>
        <div class="actions">
          <button type="button" class="button primary" disabled={busy} onclick={saveSheet}>{t("web.save")}</button>
          <button type="button" class="button" onclick={() => ((editing = false), (sheet = memory?.text ?? ""))}>{t("chat.cancel")}</button>
        </div>
      {:else}
        {#if memory.measure.lines}<pre class="sheet">{memory.text}</pre>{:else}<p class="muted">{t("tools.sheet_empty")}</p>{/if}
        <div class="actions">
          <button type="button" class="button" disabled={busy} onclick={() => (editing = true)}>{t("tools.sheet_edit")}</button>
          {#if memory.measure.lines}
            {#if deleting}
              <span>{t("tools.sheet_delete_confirm")}</span>
              <button type="button" class="button danger" disabled={busy} onclick={deleteSheet}>{t("upkeep.delete_yes")}</button>
              <button type="button" class="button" onclick={() => (deleting = false)}>{t("chat.cancel")}</button>
            {:else}
              <button type="button" class="button quiet danger" disabled={busy} onclick={() => (deleting = true)}>{t("tools.sheet_delete")}</button>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  {/if}

  <div class="part">
    <h3>{t("tools.export")}</h3>
    <p class="muted">{t("tools.export_help")}</p>
    <div class="actions">
      <button type="button" class="button" disabled={!messages.length} onclick={() => save(exportName(title, new Date()), toMarkdown(title, messages, { you: t("tools.you"), lutin: "Lutin", tool: t("tools.tool") }))}>{t("tools.export_md")}</button>
    </div>
  </div>

  <div class="part">
    <h3>{t("tools.handover")}</h3>
    <p class="muted">{t("tools.handover_help")}</p>
    <div class="actions">
      <button type="button" class="button" disabled={busy} onclick={writeHandover}>{t("tools.handover_write")}</button>
      {#if handover}
        <button type="button" class="button" onclick={() => copyText(handover).then(() => (notice = t("lutin.copied")))}>{t("tools.copy")}</button>
        <button type="button" class="button" onclick={() => save(exportName("reprise-" + title, new Date()), handover)}>{t("tools.save_md")}</button>
      {/if}
    </div>
    {#if handover}<pre class="sheet">{handover}</pre>{/if}
  </div>

</section>

<style>
  .intro {
    margin: 0;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    max-width: var(--measure);
  }

  .conversation-tools,
  .part,
  .modes {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .conversation-tools {
    padding: var(--space-3);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
    max-height: 60vh;
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow-y: auto;
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
  }

  h3 {
    font-size: var(--text-md, 1rem);
  }

  .part {
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }


  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem {
    color: var(--color-danger);
  }

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .sheet {
    margin: 0;
    padding: var(--space-2);
    max-height: 18rem;
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow: auto;
    border-radius: var(--radius-md);
    background: var(--color-code-bg);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  textarea {
    width: 100%;
    font-family: var(--font-mono);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  ul {
    margin: 0;
    padding-left: var(--space-4);
  }

  .files {
    padding-left: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .files li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }

  .files .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  code {
    overflow-wrap: anywhere;
  }
</style>
