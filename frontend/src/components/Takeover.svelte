<script lang="ts">
  // Taking over the data of another assistant (an earlier Lutin, a folder of the same layout, or its .zip), as the old page did: what it holds is said first,
  // the person chooses what to take, and it is taken after a second click. The present data is kept in a .zip by the server first (POST /takeover).
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Found = { conversations: number; memory: string[]; skills: number; settings: boolean; folder: string; projects: { id: string; name: string }[]; current: string };
  type Choice = "conversations" | "memory" | "skills" | "settings";

  let { path: given = "", ondone }: { path?: string; ondone?: (summary: string[]) => void } = $props(); // ondone gets the report: a parent that hides this block keeps it

  let path = $state("");
  let found = $state<Found | null>(null);
  let chosen = $state<Choice[]>([]);
  let overwrite = $state(false);
  let project = $state("");
  let asking = $state(false);
  let busy = $state(false);
  let problem = $state("");
  let summary = $state<string[]>([]);

  const source = $derived(given || path.trim());

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || t("error.generic", cause.code);
    return t("error.generic", String(cause));
  }

  async function detect(): Promise<void> {
    if (!source || busy) return;
    busy = true;
    problem = "";
    summary = [];
    try {
      found = await api<Found>("POST", "/takeover/detect", { path: source });
      chosen = (["conversations", "memory", "skills", "settings"] as Choice[]).filter((choice) => available(choice));
      project = found.current;
    } catch (cause) {
      found = null;
      problem = explain(cause);
    }
    busy = false;
  }

  function available(choice: Choice): boolean {
    if (!found) return false;
    return choice === "conversations" ? found.conversations > 0 : choice === "memory" ? found.memory.length > 0 : choice === "skills" ? found.skills > 0 : found.settings;
  }

  function label(choice: Choice): string {
    if (!found) return "";
    if (choice === "conversations") return t("takeover.conversations", found.conversations);
    if (choice === "memory") return t("takeover.memory", found.memory.join(", "));
    if (choice === "skills") return t("takeover.skills", found.skills);
    return t("takeover.settings");
  }

  async function take(): Promise<void> {
    busy = true;
    problem = "";
    try {
      summary = (await api<{ summary: string[] }>("POST", "/takeover", { path: source, choices: chosen, overwrite, project, confirm: true })).summary;
      asking = false;
      found = null;
      ondone?.(summary);
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }
</script>

<div class="takeover">
  {#if !given}
    <form class="line" onsubmit={(event) => (event.preventDefault(), void detect())}>
      <label class="field">{t("takeover.path")}<input type="text" bind:value={path} autocomplete="off" spellcheck="false" placeholder="D:/old-assistant" /></label>
      <button type="submit" class="button" disabled={busy || !path.trim()}>{t("takeover.detect")}</button>
    </form>
  {:else if !found && !summary.length}
    <button type="button" class="button primary" disabled={busy} onclick={detect}>{t("takeover.open")}</button>
  {/if}
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if found}
    <fieldset disabled={busy}>
      <legend>{t("takeover.what", found.folder)}</legend>
      {#each ["conversations", "memory", "skills", "settings"] as const as choice (choice)}
        {#if available(choice)}<label><input type="checkbox" value={choice} bind:group={chosen} /> {label(choice)}</label>{/if}
      {/each}
      {#if chosen.includes("memory")}<label><input type="checkbox" bind:checked={overwrite} /> {t("takeover.overwrite")}</label>{/if}
      {#if chosen.includes("skills") && found.projects.length > 1}
        <label class="field">{t("takeover.project")}
          <select bind:value={project}>{#each found.projects as entry (entry.id)}<option value={entry.id}>{entry.name}</option>{/each}</select>
        </label>
      {/if}
      <p class="muted">{t("takeover.backup")}</p>
      {#if asking}
        <span class="line" role="group" aria-label={t("takeover.confirm")}>
          <span>{t("takeover.confirm")}</span>
          <button type="button" class="button primary" onclick={take}>{t("takeover.yes")}</button>
          <button type="button" class="button" onclick={() => (asking = false)}>{t("chat.cancel")}</button>
        </span>
      {:else}
        <button type="button" class="button primary" disabled={!chosen.length} onclick={() => (asking = true)}>{t("takeover.take")}</button>
      {/if}
    </fieldset>
  {/if}
  {#if summary.length}
    <ul class="summary" role="status">{#each summary as line, index (index)}<li>{line}</li>{/each}</ul>
  {/if}
</div>

<style>
  .takeover {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  legend {
    font-weight: 600;
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
    min-width: min(100%, 18rem);
  }

  input[type="text"],
  select {
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .muted {
    margin: 0;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .problem {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
    font-size: var(--text-sm);
  }

  .summary {
    margin: 0;
    padding-left: var(--space-4);
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
