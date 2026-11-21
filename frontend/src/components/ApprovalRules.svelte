<script lang="ts">
  // The approval rules for commands: what is refused, asked or run without asking. Refuse wins over ask, ask over allow; the commands of the hardline list
  // are always asked, whatever is written here. Rules are written from the machine itself.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type Rule = { id: string; effect: "deny" | "ask" | "allow"; command: string };
  type View = { rules: Rule[]; project_rules: { effect: string; command: string }[]; hardline: string[] };

  let view = $state<View | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let effect = $state<Rule["effect"]>("ask");
  let command = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("rules.not_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<View>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      view = await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function add(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!command.trim()) return;
    await act(async () => {
      const answer = await api<View>("POST", "/approval-rules", { effect, command: command.trim() });
      command = "";
      return answer;
    });
  }

  const remove = (rule: Rule): Promise<void> => act(() => api<View>("DELETE", `/approval-rules/${encodeURIComponent(rule.id)}`));

  onMount(() => {
    void act(() => api<View>("GET", "/approval-rules"));
  });
</script>

<section class="rules" aria-labelledby="rules-title">
  <h2 id="rules-title">{t("rules.title")}</h2>
  <p class="muted">{t("rules.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if view}
    {#if view.rules.length === 0}
      <p class="muted">{t("rules.none")}</p>
    {:else}
      <ul class="list">
        {#each view.rules as rule (rule.id)}
          <li>
            <span class={"effect " + rule.effect}>{t(("rules.effect." + rule.effect) as MessageKey)}</span>
            <code>{rule.command}</code>
            <button type="button" class="button" disabled={busy} onclick={() => remove(rule)}>{t("rules.remove")}<span class="visually-hidden"> {rule.command}</span></button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if view.project_rules.length}
      <p class="muted">{t("rules.project")}</p>
      <ul class="list">
        {#each view.project_rules as rule, index (index)}
          <li><span class={"effect " + rule.effect}>{t(("rules.effect." + rule.effect) as MessageKey)}</span><code>{rule.command}</code></li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={add}>
      <label for="rule-effect">{t("rules.add_effect")}</label>
      <select id="rule-effect" bind:value={effect}>
        <option value="deny">{t("rules.effect.deny")}</option>
        <option value="ask">{t("rules.effect.ask")}</option>
        <option value="allow">{t("rules.effect.allow")}</option>
      </select>
      <label for="rule-command">{t("rules.add_command")}</label>
      <input id="rule-command" type="text" bind:value={command} maxlength="300" autocomplete="off" spellcheck="false" aria-describedby="rule-help" />
      <p class="muted" id="rule-help">{t("rules.help")}</p>
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !command.trim()}>{t("rules.add")}</button></div>
    </form>

    <details>
      <summary>{t("rules.hardline_title")}</summary>
      <p class="muted">{t("rules.hardline_intro")}</p>
      <ul class="plain">{#each view.hardline as item (item)}<li>{item}</li>{/each}</ul>
    </details>
  {/if}
</section>

<style>
  .rules {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
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

  .list li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  code {
    flex: 1 1 10rem;
    overflow-wrap: anywhere;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }

  .effect {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .effect.deny {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .effect.ask {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }

  .effect.allow {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  label {
    font-weight: 600;
  }

  select,
  input {
    max-width: 24rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .plain {
    margin: 0;
    padding-left: var(--space-5);
    font-size: var(--text-sm);
  }

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
