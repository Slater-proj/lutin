<script lang="ts">
  // The connectors (MCP): the tools of another program, or of a server, lent to Lutin. Nothing is started by adding one; "Refresh the tools" starts it and lists what it offers,
  // and a tool reaches the model only once it is allowed here. Starting a program is for the machine itself (the server refuses a paired device and says so).
  // The values of the secrets (variables, headers) are typed once and never shown again: only their names are.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Tool = { name: string; description: string; read_only: boolean; allowed: boolean };
  type Connector = {
    id: string;
    name: string;
    kind: "command" | "http";
    command: string[];
    url: string;
    active: boolean;
    read_only: boolean;
    connected: boolean;
    refreshed_at: number;
    error: string;
    env_names: string[];
    header_names: string[];
    tools: Tool[];
  };
  type View = { connectors: Connector[]; tool_limit: { max: number; exposables: number; ecartes: number } };

  let view = $state<View | null>(null);
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);
  let removing = $state("");
  let name = $state("");
  let remote = $state(false);
  let command = $state("");
  let url = $state("");
  let secrets = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("connectors.only_here");
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

  /** One secret per line, « NAME=value » (a variable of the program, or a header of the server). A line without « = » is ignored. */
  function parseSecrets(text: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const cut = line.indexOf("=");
      if (cut > 0) out[line.slice(0, cut).trim()] = line.slice(cut + 1).trim();
    }
    return out;
  }

  const load = (): Promise<void> =>
    act(async () => {
      view = await api<View>("GET", "/mcp-connectors");
    });

  const add = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      const found = parseSecrets(secrets);
      const body = remote ? { name: name.trim(), url: url.trim(), headers: found } : { name: name.trim(), command: command.trim(), env: found };
      view = await api<View>("POST", "/mcp-connectors", body);
      name = "";
      command = "";
      url = "";
      secrets = "";
    });
  };

  const change = (connector: Connector, body: Record<string, unknown>): Promise<void> =>
    act(async () => {
      view = await api<View>("PATCH", `/mcp-connectors/${encodeURIComponent(connector.id)}`, body);
    });

  const refresh = (connector: Connector): Promise<void> =>
    act(async () => {
      const answer = await api<{ tool_count: number }>("POST", `/mcp-connectors/${encodeURIComponent(connector.id)}/refresh`, {});
      view = await api<View>("GET", "/mcp-connectors");
      done = t("connectors.refreshed", connector.name, answer.tool_count);
    });

  const remove = (connector: Connector): Promise<void> =>
    act(async () => {
      view = await api<View>("DELETE", `/mcp-connectors/${encodeURIComponent(connector.id)}`);
      removing = "";
    });

  onMount(() => {
    void load();
  });
</script>

<section class="connectors" aria-labelledby="connectors-title">
  <h2 id="connectors-title">{t("connectors.title")}</h2>
  <p class="muted">{t("connectors.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}

  {#if view}
    {#if view.tool_limit.ecartes > 0}<p class="warn">{t("connectors.too_many", view.tool_limit.max, view.tool_limit.ecartes)}</p>{/if}
    {#if view.connectors.length === 0}
      <p class="empty">{t("connectors.none")}</p>
    {:else}
      <ul class="list" aria-label={t("connectors.title")}>
        {#each view.connectors as connector (connector.id)}
          <li class="card">
            <div class="line">
              <strong>{connector.name}</strong>
              <span class="badge">{connector.kind === "http" ? t("connectors.kind_http") : t("connectors.kind_command")}</span>
              {#if !connector.active}<span class="badge">{t("connectors.off")}</span>{/if}
            </div>
            <p class="where">{connector.kind === "http" ? connector.url : connector.command.join(" ")}</p>
            {#if connector.env_names.length || connector.header_names.length}
              <p class="muted">{t("connectors.secrets_set", [...connector.env_names, ...connector.header_names].join(", "))}</p>
            {/if}
            {#if connector.error}<p class="warn">{connector.error}</p>{/if}
            <div class="checks">
              <label class="inline"><input type="checkbox" checked={connector.active} disabled={busy} onchange={() => change(connector, { active: !connector.active })} /> {t("connectors.active")}</label>
              <label class="inline"><input type="checkbox" checked={connector.read_only} disabled={busy} onchange={() => change(connector, { read_only: !connector.read_only })} /> {t("connectors.read_only")}</label>
            </div>
            {#if connector.tools.length}
              <details>
                <summary>{t("connectors.tools", connector.tools.length)}</summary>
                <ul class="tools">
                  {#each connector.tools as tool (tool.name)}
                    <li>
                      <label class="inline">
                        <input type="checkbox" checked={tool.allowed} disabled={busy} onchange={() => change(connector, { tool: tool.name, allowed: !tool.allowed })} />
                        <span><strong>{tool.name}</strong>{#if tool.read_only} <span class="muted">({t("connectors.reads_only")})</span>{/if}</span>
                      </label>
                      {#if tool.description}<p class="muted">{tool.description}</p>{/if}
                    </li>
                  {/each}
                </ul>
              </details>
            {:else}
              <p class="muted">{t("connectors.no_tools")}</p>
            {/if}
            <div class="actions">
              <button type="button" class="button" disabled={busy} onclick={() => refresh(connector)}>{t("connectors.refresh")}</button>
              {#if removing === connector.id}
                <span class="confirm" role="group" aria-label={t("connectors.remove_confirm", connector.name)}>
                  <span>{t("connectors.remove_confirm", connector.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(connector)}>{t("connectors.remove_yes")}</button>
                  <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (removing = connector.id)}>{t("connectors.remove")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={add}>
      <h3>{t("connectors.add_title")}</h3>
      <label for="connector-name">{t("connectors.name")}</label>
      <input id="connector-name" type="text" bind:value={name} maxlength="40" autocomplete="off" required />
      <fieldset>
        <legend>{t("connectors.kind")}</legend>
        <label class="inline"><input type="radio" name="connector-kind" checked={!remote} onchange={() => (remote = false)} /> {t("connectors.kind_command")}</label>
        <label class="inline"><input type="radio" name="connector-kind" checked={remote} onchange={() => (remote = true)} /> {t("connectors.kind_http")}</label>
      </fieldset>
      {#if remote}
        <label for="connector-url">{t("connectors.url")}</label>
        <input id="connector-url" type="text" bind:value={url} autocomplete="off" spellcheck="false" required />
      {:else}
        <label for="connector-command">{t("connectors.command")}</label>
        <input id="connector-command" type="text" bind:value={command} autocomplete="off" spellcheck="false" required />
      {/if}
      <label for="connector-secrets">{remote ? t("connectors.headers") : t("connectors.variables")}</label>
      <textarea id="connector-secrets" rows="3" bind:value={secrets} autocomplete="off" spellcheck="false" aria-describedby="connector-secrets-help"></textarea>
      <p class="muted" id="connector-secrets-help">{t("connectors.secrets_help")}</p>
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !name.trim() || !(remote ? url.trim() : command.trim())}>{t("connectors.add")}</button></div>
    </form>
  {:else if !problem}
    <p class="muted">{t("connectors.loading")}</p>
  {/if}
</section>

<style>
  .connectors {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .list,
  .tools {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .line,
  .checks,
  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .where {
    overflow-wrap: anywhere;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .empty {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-lg);
    color: var(--color-text-muted);
  }

  details {
    font-size: var(--text-sm);
  }

  summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
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

  label.inline {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    font-weight: 400;
    cursor: pointer;
  }

  input[type="radio"],
  input[type="checkbox"] {
    accent-color: var(--color-accent);
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
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
