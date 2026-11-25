<script lang="ts">
  // What Lutin finds and uses in one work folder (its files, the instructions and skills it reads, the copies of conversations, another assistant's data to
  // take over), and the two changes of place the old page offered: move the folder with its files, or give it the path it was moved to by hand. Parity, 2026-11-22.
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";
  import Takeover from "./Takeover.svelte";

  type Projects = { projects: { id: string; name: string; path: string; usable: boolean; problem: string }[]; current: string };
  type Preview = {
    error: string;
    files: number;
    truncated: boolean;
    reads: string[];
    conversation_copies: number;
    git: boolean;
    previous_assistant: { conversations: number; memory: string[]; skills: number; folder: string; to_take_over: boolean } | null;
  };

  let { id, name, canConfigure, onchanged }: { id: string; name: string; canConfigure: boolean; onchanged: (view: Projects) => void } = $props();

  let preview = $state<Preview | null>(null);
  let parent = $state("");
  let newName = $state("");
  let byHand = $state("");
  let asking = $state(false);
  let busy = $state(false);
  let notice = $state("");
  let taken = $state<string[]>([]); // the report of a takeover: kept here, the takeover block goes once nothing is left to take
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || t("error.generic", cause.code);
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const look = (): Promise<void> => act(async () => void (preview = await api<Preview>("GET", `/projects/${encodeURIComponent(id)}/preview`)));

  const move = (): Promise<void> =>
    act(async () => {
      const view = await api<Projects & { new_path: string; left: string[] }>("POST", `/projects/${encodeURIComponent(id)}/move`, { parent: parent.trim(), name: newName.trim() });
      asking = false;
      notice = t("projects.moved", view.new_path) + (view.left.length ? " " + t("projects.left", view.left.join(", ")) : "");
      onchanged(view);
    });

  const repath = (): Promise<void> =>
    act(async () => {
      const view = await api<Projects>("PATCH", `/projects/${encodeURIComponent(id)}`, { path: byHand.trim() });
      byHand = "";
      notice = t("projects.repathed");
      onchanged(view);
    });
</script>

<details class="details" ontoggle={(event) => (event.currentTarget as HTMLDetailsElement).open && !preview && void look()}>
  <summary>{t("projects.details")}<span class="visually-hidden"> {name}</span></summary>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if notice}<p class="notice" role="status">{notice}</p>{/if}
  {#if taken.length}<ul class="taken notice" role="status">{#each taken as line, index (index)}<li>{line}</li>{/each}</ul>{/if}
  {#if preview}
    {#if preview.error}
      <p class="problem">{preview.error}</p>
    {:else}
      <ul class="facts">
        <li>{t(preview.truncated ? "projects.files_many" : "projects.files", preview.files)}</li>
        {#each preview.reads as read (read)}<li>{t("projects.reads", read)}</li>{/each}
        {#if preview.conversation_copies}<li>{t("projects.copies", preview.conversation_copies)}</li>{/if}
        {#if preview.git}<li>{t("projects.git")}</li>{/if}
      </ul>
      {#if preview.previous_assistant?.to_take_over && canConfigure}
        <p>{t("projects.previous", preview.previous_assistant.conversations, preview.previous_assistant.skills)}</p>
        <Takeover path={preview.previous_assistant.folder} ondone={(summary) => ((taken = summary), void look())} />
      {:else if preview.previous_assistant}
        <p class="muted">{t("projects.previous_done")}</p>
      {/if}
    {/if}
  {:else if !problem}
    <p class="muted" role="status">{t("projects.reading")}</p>
  {/if}
  {#if canConfigure}
    <form class="line" onsubmit={(event) => (event.preventDefault(), (asking = true))}>
      <label class="field">{t("projects.move_to")}<input type="text" bind:value={parent} autocomplete="off" spellcheck="false" placeholder="D:/work" /></label>
      <label class="field">{t("projects.move_name")}<input type="text" bind:value={newName} autocomplete="off" placeholder={name} /></label>
      {#if asking}
        <span class="line" role="group" aria-label={t("projects.move_confirm")}>
          <span>{t("projects.move_confirm")}</span>
          <button type="button" class="button primary" disabled={busy} onclick={move}>{t("projects.move_yes")}</button>
          <button type="button" class="button" onclick={() => (asking = false)}>{t("chat.cancel")}</button>
        </span>
      {:else}
        <button type="submit" class="button" disabled={busy || !parent.trim()}>{t("projects.move")}</button>
      {/if}
    </form>
    <form class="line" onsubmit={(event) => (event.preventDefault(), void repath())}>
      <label class="field">{t("projects.by_hand")}<input type="text" bind:value={byHand} autocomplete="off" spellcheck="false" /></label>
      <button type="submit" class="button" disabled={busy || !byHand.trim()}>{t("projects.repath")}</button>
    </form>
  {/if}
</details>

<style>
  .details {
    flex-basis: 100%;
    font-size: var(--text-sm);
  }

  summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .details > :not(summary) {
    margin-top: var(--space-2);
  }

  .taken {
    margin: 0;
    padding-left: var(--space-4);
  }

  .facts {
    margin: 0;
    padding-left: var(--space-4);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: var(--space-2);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: min(100%, 14rem);
  }

  input {
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  p {
    margin: 0;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }
</style>
