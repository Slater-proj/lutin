<script lang="ts">
  // The tools of the conversation open in the Chat (docs/modernization/PARITY.md, item 12): how it keeps its thread (summary, progress sheet, or the
  // general setting) and its sheet read, edited or deleted after a second click; a handover document written by the model, to copy or save; the
  // conversation saved as Markdown; and its folders on this machine.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { copyText } from "../lib/clipboard";
  import { exportName, toMarkdown, type ExportedMessage } from "../lib/export";
  import { t } from "../lib/messages";

  type Memory = { mode: string; own_mode: string | null; general_mode: string; text: string; measure: { lines: number; tokens: number; level: string; warning: string }; first_request: string | null };

  let { conversation, title, messages, canConfigure }: { conversation: string; title: string; messages: ExportedMessage[]; canConfigure: boolean } = $props();

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

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
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
  const openFolder = (path: string): Promise<void> => act(async () => void (await api("POST", base + "/folders/open", { path })));

  onMount(() => {
    api<Memory>("GET", base + "/memory").then(shown, (cause) => (problem = explain(cause)));
    if (canConfigure) api<{ folders: { path: string; role: string }[]; can_open: boolean }>("GET", base + "/folders").then((answer) => ((folders = answer.folders), (canOpen = answer.can_open)), () => undefined);
  });
</script>

<section class="conversation-tools" aria-labelledby="tools-title">
  <h2 id="tools-title">{t("tools.title")}</h2>
  <p class="intro">{t("tools.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>

  {#if memory}
    <div class="modes">
      <h3>{t("tools.memory")}</h3>
      <p class="muted">{t("tools.memory_help")}</p>
    </div>
    {#if memory.first_request}<p class="muted">{t("tools.first_request", memory.first_request)}</p>{/if}

    <div class="part">
      <h3>{t("tools.sheet")}</h3>
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

  <div class="part">
    <h3>{t("tools.export")}</h3>
    <div class="actions">
      <button type="button" class="button" disabled={!messages.length} onclick={() => save(exportName(title, new Date()), toMarkdown(title, messages, { you: t("tools.you"), lutin: "Lutin", tool: t("tools.tool") }))}>{t("tools.export_md")}</button>
    </div>
  </div>

  {#if folders?.length}
    <div class="part">
      <h3>{t("tools.folders")}</h3>
      <ul>
        {#each folders as folder (folder.path)}
          <li><span class="muted">{t(("tools.folder." + folder.role) as "tools.folder.work")}</span> <code>{folder.path}</code>
            {#if canOpen}<button type="button" class="button quiet" disabled={busy} onclick={() => openFolder(folder.path)}>{t("tools.open")}</button>{/if}</li>
        {/each}
      </ul>
    </div>
  {/if}
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

  code {
    overflow-wrap: anywhere;
  }
</style>
