<script lang="ts">
  // The project's Git and the actions log, on the Projects screen (docs/modernization/PARITY.md, item 12): the files changed, a commit message proposed
  // by the model for the ones ticked, a commit of those files only (never a push; for this machine), and the log of what Lutin changed (what, where, with
  // which approval; never a file's content nor a command's output).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type Git = { available: boolean; reason: string; branch: string; files: { path: string; state: string }[]; total: number };
  type Entry = { at: string; tool: string; target: string; outcome: string; approval: string; conversation: string };

  let { canConfigure }: { canConfigure: boolean } = $props();

  let git = $state<Git | null>(null);
  let chosen = $state<string[]>([]);
  let message = $state("");
  let log = $state<Entry[] | null>(null);
  let busy = $state(false);
  let proposing = $state(false);
  let notice = $state("");
  let problem = $state("");

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

  const load = async (): Promise<void> => {
    git = await api<Git>("GET", "/git");
    chosen = chosen.filter((path) => git?.files.some((file) => file.path === path));
  };
  // Writing the message can take a while (the model may have to load first): say so, next to the button.
  const propose = (): Promise<void> =>
    act(async () => {
      proposing = true;
      try {
        message = (await api<{ message: string }>("POST", "/git/message", { files: chosen })).message;
      } finally {
        proposing = false;
      }
    });
  const allChosen = $derived(!!git?.files.length && git.files.every((file) => chosen.includes(file.path)));
  const toggleAll = (): void => void (chosen = allChosen ? [] : (git?.files ?? []).map((file) => file.path));
  const commit = (): Promise<void> =>
    act(async () => {
      notice = (await api<{ output: string }>("POST", "/git/commit", { message, files: chosen })).output || t("git.committed");
      message = "";
      chosen = [];
      await load();
    });
  const showLog = (): Promise<void> => act(async () => void (log = (await api<{ entries: Entry[] }>("GET", "/actions-log?n=100")).entries.reverse()));

  onMount(() => void load().catch((cause) => (problem = explain(cause))));
</script>

<section class="project-git" aria-labelledby="git-title">
  <h2 id="git-title">{t("git.title")}</h2>
  {#if git}
    {#if !git.available}
      <p class="muted">{git.reason}</p>
    {:else}
      <p class="muted">{t("git.branch", git.branch, git.total)}</p>
      {#if git.files.length}
        <fieldset disabled={busy}>
          <legend class="visually-hidden">{t("git.files")}</legend>
          <!-- a bar of its own above the list (maintainer, 2026-11-21: it looked like one more file) -->
          <div class="all-bar">
            <label class="all"><input type="checkbox" checked={allChosen} indeterminate={!!chosen.length && !allChosen} onchange={toggleAll} /> {allChosen ? t("git.none") : t("git.all")}</label>
            <span class="muted count">{t("git.chosen", String(chosen.length), String(git.files.length))}</span>
          </div>
          <div class="files">
            {#each git.files as file (file.path)}
              <label><input type="checkbox" value={file.path} bind:group={chosen} /> <code>{file.path}</code> <span class="muted">{t(("git.state." + file.state) as MessageKey)}</span></label>
            {/each}
          </div>
        </fieldset>
        <div class="actions">
          <button type="button" class="button" disabled={busy || !chosen.length} onclick={propose}>{t("git.propose")}</button>
          {#if proposing}<span class="muted" role="status">{t("git.proposing")}</span>{/if}
        </div>
        {#if !canConfigure && message}
          <label class="field">{t("git.message")}<textarea rows="3" readonly value={message}></textarea></label>
        {/if}
        {#if canConfigure}
          <label class="field">{t("git.message")}<textarea rows="3" bind:value={message}></textarea></label>
          <div class="actions"><button type="button" class="button primary" disabled={busy || !chosen.length || !message.trim()} onclick={commit}>{t("git.commit", chosen.length)}</button></div>
          <p class="muted">{t("git.no_push")}</p>
        {/if}
      {:else}
        <p class="muted">{t("git.clean")}</p>
      {/if}
    {/if}
  {/if}
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>

  <h3>{t("log.title")}</h3>
  <p class="muted">{t("log.help")}</p>
  {#if log === null}
    <div class="actions"><button type="button" class="button" disabled={busy} onclick={showLog}>{t("log.show")}</button></div>
  {:else if log.length === 0}
    <p class="muted">{t("log.empty")}</p>
  {:else}
    <ul class="log">
      {#each log as entry, index (index)}<li><span class="muted">{entry.at.replace("T", " ")}</span> <strong>{entry.tool}</strong> <code>{entry.target}</code> · {entry.outcome} · {entry.approval}</li>{/each}
    </ul>
  {/if}
</section>

<style>
  .project-git,
  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
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
    margin-top: var(--space-3);
    font-size: var(--text-md, 1rem);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
    white-space: pre-wrap;
  }

  .problem {
    color: var(--color-danger);
  }

  label {
    overflow-wrap: anywhere;
  }

  .all-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface-raised);
  }

  .all {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    font-weight: 600;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .count {
    font-size: var(--text-sm);
  }

  .files {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding-left: var(--space-3);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 40rem;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .log {
    margin: 0;
    padding-left: var(--space-4);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }
</style>
