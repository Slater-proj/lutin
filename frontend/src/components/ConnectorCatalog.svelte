<script lang="ts">
  // The connectors shipped with Lutin: known servers pinned to an exact version, plugged in with a few values. Installing one starts a program, so it is for the machine itself.
  // If the program that runs the server is missing, Lutin downloads it first: the page says so and waits for a click before it does.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { installInput, readyToInstall, type CatalogEntry } from "../lib/catalog";
  import { t } from "../lib/messages";

  let { onchange }: { onchange?: () => void } = $props();

  let entries = $state<CatalogEntry[] | null>(null);
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);
  let opened = $state("");
  let confirming = $state(false);
  let typed = $state<Record<string, string>>({});

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("connectors.only_here");
      if (cause.code === "offline") return t("catalog.offline");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      done = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const load = (): Promise<void> =>
    act(async () => {
      entries = (await api<{ entries: CatalogEntry[] }>("GET", "/mcp-catalog")).entries;
    });

  function open(entry: CatalogEntry): void {
    opened = opened === entry.id ? "" : entry.id;
    confirming = false;
    typed = {};
    problem = "";
    done = "";
  }

  const install = (entry: CatalogEntry, event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    if (entry.prerequisite && !confirming) {
      confirming = true;
      return Promise.resolve();
    }
    return act(async () => {
      const answer = await api<{ connector: string; tool_count: number; allowed_count: number }>("POST", `/mcp-catalog/${encodeURIComponent(entry.id)}/install`, {
        input: installInput(entry.fields, typed),
        confirm: confirming,
      });
      opened = "";
      confirming = false;
      typed = {};
      entries = (await api<{ entries: CatalogEntry[] }>("GET", "/mcp-catalog")).entries;
      onchange?.();
      done = t("catalog.installed", entry.name, answer.tool_count, answer.allowed_count);
    });
  };

  onMount(() => {
    void load();
  });
</script>

<section class="catalog" aria-labelledby="catalog-title">
  <h3 id="catalog-title">{t("catalog.title")}</h3>
  <p class="muted">{t("catalog.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}

  {#if entries}
    <ul class="list" aria-label={t("catalog.title")}>
      {#each entries as entry (entry.id)}
        <li class="entry-card">
          <div class="line">
            <strong>{entry.name}</strong>
            <span class="badge">{entry.version}</span>
            {#if entry.installed}<span class="badge ok">{t("catalog.installed_badge")}</span>{/if}
          </div>
          <p class="muted">{entry.description}</p>
          {#if !entry.installed}
            {#if opened === entry.id}
              <form onsubmit={(event) => install(entry, event)}>
                {#each entry.fields as field (field.key)}
                  <label for={`catalog-${entry.id}-${field.key}`}>{field.label}</label>
                  {#if field.multiple}
                    <textarea id={`catalog-${entry.id}-${field.key}`} rows="3" placeholder={field.example} bind:value={typed[field.key]} autocomplete="off" spellcheck="false"></textarea>
                  {:else}
                    <input id={`catalog-${entry.id}-${field.key}`} type={field.type === "secret" ? "password" : "text"} placeholder={field.example} bind:value={typed[field.key]} autocomplete="off" spellcheck="false" />
                  {/if}
                {/each}
                {#if confirming}<p class="warn" role="status">{entry.prerequisite}</p>{/if}
                <div class="actions">
                  <button type="submit" class="button primary" disabled={busy || !readyToInstall(entry.fields, typed)}>{confirming ? t("catalog.confirm_yes") : t("catalog.install")}</button>
                  <button type="button" class="button" onclick={() => open(entry)}>{t("chat.cancel")}</button>
                </div>
              </form>
            {:else}
              <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => open(entry)}>{t("catalog.set_up")}</button></div>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>
  {:else if !problem}
    <p class="muted">{t("catalog.loading")}</p>
  {/if}
</section>

<style>
  .catalog {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .entry-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .line,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .badge.ok {
    color: var(--color-accent-text);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  input[type="password"],
  textarea {
    max-width: 32rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .problem,
  .warn {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .done {
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
