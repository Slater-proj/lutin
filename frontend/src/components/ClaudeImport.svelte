<script lang="ts">
  // Take up a project made for Claude (a CLAUDE.md file, a .claude/ folder): look at what it holds first, then work in the folder itself or in a copy (the original is
  // never touched). Importing adds the folder to the list, so it is for the person at this machine, like adding a folder.
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Item = { name: string; description: string; path: string };
  type Found = { is_claude_project: boolean; summary: string; path: string; found: { context: string[]; rules: string[]; skills: Item[]; commands: Item[]; agents: Item[] } };
  type Imported = { projects: unknown[]; current: string; mode: string; path: string; summary: string; selected: boolean };

  let { onimported }: { onimported?: (answer: Imported) => void } = $props();

  let path = $state("");
  let found = $state<Found | null>(null);
  let mode = $state<"in_place" | "copy">("in_place");
  let target = $state("");
  let name = $state("");
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("projects.not_here");
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

  const look = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    if (!path.trim()) return Promise.resolve();
    return act(async () => {
      found = null;
      found = await api<Found>("GET", `/projects/claude?path=${encodeURIComponent(path.trim())}`);
    });
  };

  const take = (): Promise<void> =>
    act(async () => {
      const body: Record<string, string> = { path: path.trim(), mode };
      if (mode === "copy" && target.trim()) body.to = target.trim();
      if (name.trim()) body.name = name.trim();
      const answer = await api<Imported>("POST", "/projects/import-claude", body);
      done = t(answer.selected ? "claude.done_selected" : "claude.done_waiting", answer.summary, answer.path);
      found = null;
      path = "";
      target = "";
      name = "";
      onimported?.(answer);
    });

  const counts = (view: Found): string[] => {
    const out: string[] = [];
    if (view.found.context.length) out.push(view.found.context.join(", "));
    if (view.found.skills.length) out.push(t("claude.skills", view.found.skills.length));
    if (view.found.commands.length) out.push(t("claude.commands", view.found.commands.length));
    if (view.found.agents.length) out.push(t("claude.agents", view.found.agents.length));
    if (view.found.rules.length) out.push(t("claude.rules", view.found.rules.length));
    return out;
  };
</script>

<section class="claude-import" aria-labelledby="claude-title">
  <h2 id="claude-title">{t("claude.title")}</h2>
  <p class="muted">{t("claude.intro")}</p>
  {#if problem}<p class="claude-problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="claude-done" role="status">{done}</p>{/if}

  <form onsubmit={look}>
    <label for="claude-path">{t("claude.path")}</label>
    <input id="claude-path" type="text" bind:value={path} autocomplete="off" spellcheck="false" />
    <div class="actions"><button type="submit" class="button" disabled={busy || !path.trim()}>{t("claude.look")}</button></div>
  </form>

  {#if found}
    {#if found.is_claude_project}
      <div class="result" role="group" aria-label={t("claude.found")}>
        <p><strong>{t("claude.found")}</strong> {counts(found).join(" · ")}</p>
        <fieldset>
          <legend>{t("claude.mode")}</legend>
          <label class="inline"><input type="radio" name="claude-mode" checked={mode === "in_place"} onchange={() => (mode = "in_place")} /> {t("claude.in_place")}</label>
          <label class="inline"><input type="radio" name="claude-mode" checked={mode === "copy"} onchange={() => (mode = "copy")} /> {t("claude.copy")}</label>
        </fieldset>
        {#if mode === "copy"}
          <label for="claude-to">{t("claude.to")}</label>
          <input id="claude-to" type="text" bind:value={target} autocomplete="off" spellcheck="false" aria-describedby="claude-to-help" />
          <p class="muted" id="claude-to-help">{t("claude.to_help")}</p>
        {/if}
        <label for="claude-name">{t("projects.name")}</label>
        <input id="claude-name" type="text" bind:value={name} autocomplete="off" />
        <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={take}>{t("claude.import")}</button></div>
      </div>
    {:else}
      <p class="muted">{t("claude.not_claude")}</p>
    {/if}
  {/if}
</section>

<style>
  .claude-import,
  form,
  .result {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .claude-import {
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  label {
    font-weight: 600;
  }

  label.inline {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    font-weight: 400;
    cursor: pointer;
  }

  fieldset {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }

  legend {
    margin-bottom: var(--space-2);
    padding: 0;
    font-weight: 600;
  }

  input[type="text"] {
    max-width: 32rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  input[type="radio"] {
    accent-color: var(--color-accent);
  }

  .claude-problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .claude-done {
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
