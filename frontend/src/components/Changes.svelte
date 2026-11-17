<script lang="ts">
  // The changes of the last request of a conversation (docs/modernization/PARITY.md, item 1): the files it created, modified or deleted, each with
  // its differences, and the way back, for one file or for all of them (a second click). Read again when `tick` moves (the end of a turn).
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  let { conversation, tick, onundone }: { conversation: string; tick: number; onundone: () => void } = $props();

  type Change = { path: string; state: "created" | "modified" | "deleted"; binary: boolean; diff: string; added: number; removed: number; changed_since: boolean };
  type Changes = { undoable: boolean; files: Change[] };
  let changes = $state<Changes | null>(null);
  let open = $state(false);
  let asking = $state(false);
  let busy = $state(false);
  let problem = $state("");
  let notice = $state("");

  async function load(id: string): Promise<void> {
    changes = await api<Changes>("GET", `/conversations/${encodeURIComponent(id)}/changes`).catch(() => null);
  }

  let seenTick = -1;
  $effect(() => {
    if (tick !== seenTick) {
      seenTick = tick;
      notice = ""; // a new turn: what was said of the last undo is over
    }
    void load(conversation);
  });

  async function undo(path?: string): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    try {
      const done = await api<Changes & { restored: string[]; skipped: string[] }>("POST", `/conversations/${encodeURIComponent(conversation)}/changes/undo`, path ? { path } : {});
      changes = done;
      asking = false;
      notice = done.skipped.length ? t("changes.partly", done.restored.length, done.skipped.join(", ")) : t("changes.undone", done.restored.length);
      onundone();
    } catch (cause) {
      problem = cause instanceof ApiError && cause.message ? cause.message : t("error.generic", String(cause));
    }
    busy = false;
  }
</script>

{#if changes?.undoable || notice}
  <div class="changes" role="region" aria-label={t("changes.title")}>
    {#if changes?.undoable}
      <div class="line">
        <span>{t("changes.summary", changes.files.length)}</span>
        <button type="button" class="link" aria-expanded={open} onclick={() => (open = !open)}>{open ? t("changes.hide") : t("changes.show")}</button>
        {#if asking}
          <span class="confirm">
            <span>{t("changes.confirm")}</span>
            <button type="button" class="button danger" disabled={busy} onclick={() => undo()}>{t("changes.undo_all")}</button>
            <button type="button" class="button" onclick={() => (asking = false)}>{t("chat.cancel")}</button>
          </span>
        {:else}
          <button type="button" class="button quiet" disabled={busy} onclick={() => (asking = true)}>{t("changes.undo_all")}</button>
        {/if}
      </div>
    {/if}
    {#if notice}<p class="notice" role="status">{notice}</p>{/if}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    {#if open && changes?.undoable}
      <ul class="files">
        {#each changes.files as file (file.path)}
          <li>
            <div class="line">
              <strong class="path">{file.path}</strong>
              <span class={"state " + file.state}>{t(("changes.state." + file.state) as "changes.state.created")}</span>
              {#if !file.binary}<span class="counts"><span class="plus">+{file.added}</span> <span class="minus">−{file.removed}</span></span>{/if}
              {#if file.changed_since}<span class="warn">{t("changes.changed_since")}</span>{/if}
              <button type="button" class="button quiet" disabled={busy || file.changed_since} onclick={() => undo(file.path)}>{t("changes.undo_one")}<span class="visually-hidden"> {file.path}</span></button>
            </div>
            {#if file.binary}<p class="muted">{t("changes.binary")}</p>{:else if file.diff}<pre>{file.diff}</pre>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .changes {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--text-sm);
  }

  .line,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .files {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    max-height: 40vh;
    overflow: auto;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .path {
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }

  .state,
  .warn {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--color-surface-raised);
  }

  .warn {
    background: var(--color-warning-soft);
  }

  .plus {
    color: var(--color-accent-text);
  }

  .minus {
    color: var(--color-danger);
  }

  pre {
    margin: var(--space-1) 0 0;
    padding: var(--space-2);
    overflow: auto;
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    font-size: var(--text-xs);
  }

  .notice {
    margin: 0;
    color: var(--color-accent-text);
  }

  .muted {
    margin: 0;
    color: var(--color-text-muted);
  }

  .problem {
    margin: 0;
    color: var(--color-danger);
  }

  .link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--color-accent-text);
    text-decoration: underline;
    cursor: pointer;
    font: inherit;
    min-height: var(--target);
  }
</style>
