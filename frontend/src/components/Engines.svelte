<script lang="ts">
  // The engines: the programs that run the models, one card each (ADR 0020). Which one is in use, what each one allows right now (start, stop, install, update…), and the task it is
  // carrying out. An engine that cannot run on this machine is folded under « Other engines », with the reason on its card.
  // What changes the machine (install, uninstall, reinstall, update) says what it does and waits for a click before it is sent with `confirm`; the server refuses it otherwise.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes, percent } from "../lib/format";
  import { language, t, type MessageKey } from "../lib/messages";
  import EngineFolders from "./EngineFolders.svelte";
  import EngineSettings from "./EngineSettings.svelte";
  import { working, type EngineView } from "../lib/setup";

  let { onchanged, canConfigure = false }: { onchanged: () => void; canConfigure?: boolean } = $props();
  let settingsOf = $state(""); // the engine whose settings are open

  type Action = keyof EngineView["actions"];
  const ACTIONS: readonly Action[] = ["start", "stop", "install", "update", "reinstall", "uninstall"];
  const CONFIRMED = new Set<Action>(["install", "uninstall", "reinstall", "update"]);

  const lang = language();
  let engines = $state<EngineView[] | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let asking = $state<{ id: string; action: Action } | null>(null);
  let alive = true;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("engines.not_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    engines = (await api<{ engines: EngineView[] }>("GET", "/engines")).engines;
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      await action();
      await load();
      onchanged();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const send = (engine: EngineView, action: Action): Promise<void> =>
    act(async () => {
      await api("POST", `/engines/${encodeURIComponent(engine.id)}/actions/${action}`, CONFIRMED.has(action) ? { confirm: true } : {});
      asking = null;
    });

  const use = (engine: EngineView): Promise<void> => act(() => api("PATCH", "/settings", { engine: engine.id }));

  const cancel = (engine: EngineView): Promise<void> => act(() => api("DELETE", `/engines/${encodeURIComponent(engine.id)}/task`));

  function click(engine: EngineView, action: Action): void {
    if (CONFIRMED.has(action)) asking = { id: engine.id, action };
    else void send(engine, action);
  }

  const runnable = $derived((engines ?? []).filter((engine) => engine.runs_here.possible || engine.current));
  const others = $derived((engines ?? []).filter((engine) => !engine.runs_here.possible && !engine.current));

  onMount(() => {
    void load().catch((cause) => (problem = explain(cause)));
    const timer = setInterval(() => {
      if (alive && !busy && engines?.some((engine) => working(engine))) void load().catch(() => undefined);
    }, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

{#snippet card(engine: EngineView)}
  {@const task = engine.task}
  <li class="card" class:current={engine.current} data-engine={engine.id}>
    <div class="line">
      <strong>{engine.name}</strong>
      <span class={"state " + (engine.running ? "on" : "off")}>{engine.running ? t("engines.running") : engine.installed ? t("engines.stopped") : t("engines.missing")}</span>
      {#if engine.current}<span class="badge">{t("engines.in_use")}</span>{/if}
      {#if engine.version}<span class="muted version">{engine.version}</span>{/if}
      {#if engine.update?.available}<span class="badge update">{t("engines.update_available", engine.update.latest)}</span>{/if}
    </div>
    <p>{engine.description}</p>
    {#if !engine.runs_here.possible}<p class="error" data-cannot-run>{engine.runs_here.reason}</p>{/if}
    {#if engine.detail}<p class="muted">{engine.detail}</p>{/if}
    {#if engine.strengths.length || engine.weaknesses.length}
      <details>
        <summary>{t("engines.more")}</summary>
        {#if engine.strengths.length}<ul class="plus">{#each engine.strengths as item, index (index)}<li>{item}</li>{/each}</ul>{/if}
        {#if engine.weaknesses.length}<ul class="minus">{#each engine.weaknesses as item, index (index)}<li>{item}</li>{/each}</ul>{/if}
      </details>
    {/if}

    <button type="button" class="button quiet" aria-expanded={settingsOf === engine.id} onclick={() => (settingsOf = settingsOf === engine.id ? "" : engine.id)}>{t("eset.open")}<span class="visually-hidden"> {engine.name}</span></button>
    {#if settingsOf === engine.id}<EngineSettings engine={engine.id} {canConfigure} />{/if}

    {#if task && task.state === "running"}
      {@const share = percent(task.done, task.total)}
      <progress max="100" value={share ?? undefined} aria-label={engine.name}></progress>
      <p class="muted" role="status">{task.text}{share !== null ? " · " + share + " %" : ""}{task.total ? " · " + formatBytes(task.done, lang) + " / " + formatBytes(task.total, lang) : ""}</p>
      <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => cancel(engine)}>{t("engines.cancel_task")}</button></div>
    {:else}
      {#if task && task.state === "failed"}<p class="error" role="status">{task.error}</p>{/if}
      {#if asking && asking.id === engine.id}
        <div class="confirm" role="group" aria-label={t(("engines.action." + asking.action) as MessageKey)}>
          <p><strong>{t(("engines.action." + asking.action) as MessageKey)}</strong></p>
          <p>{engine.actions[asking.action].reason}</p>
          <div class="actions">
            <button type="button" class="button primary" disabled={busy} onclick={() => send(engine, asking!.action)}>{t("engines.confirm_yes")}</button>
            <button type="button" class="button" onclick={() => (asking = null)}>{t("chat.cancel")}</button>
          </div>
        </div>
      {:else}
        <div class="actions">
          {#if !engine.current && engine.runs_here.possible}<button type="button" class="button primary" disabled={busy} onclick={() => use(engine)}>{t("engines.use")}</button>{/if}
          {#each ACTIONS.filter((action) => engine.actions[action].possible) as action (action)}
            <button type="button" class="button" disabled={busy} onclick={() => click(engine, action)}>{t(("engines.action." + action) as MessageKey)}</button>
          {/each}
        </div>
      {/if}
    {/if}
  </li>
{/snippet}

<section class="engines" aria-labelledby="engines-title">
  <h2 id="engines-title">{t("engines.title")}</h2>
  <p class="muted">{t("engines.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if !engines}
    {#if !problem}<p class="muted">{t("engines.loading")}</p>{/if}
  {:else}
    <ul class="list">
      {#each runnable as engine (engine.id)}{@render card(engine)}{/each}
    </ul>
    {#if others.length}
      <details class="others">
        <summary>{t("engines.others", String(others.length))}</summary>
        <p class="muted">{t("engines.others_help")}</p>
        <ul class="list">
          {#each others as engine (engine.id)}{@render card(engine)}{/each}
        </ul>
      </details>
    {/if}
    <EngineFolders {canConfigure} ollama={engines.some((engine) => engine.id === "ollama" && engine.installed)} />
  {/if}
</section>

<style>
  .engines {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  p {
    margin: 0;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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

  .card.current {
    border-color: var(--color-accent);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .state,
  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .state.on,
  .badge {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .state.off {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  details {
    font-size: var(--text-sm);
  }

  details.others {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    font-size: inherit;
  }

  summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  details ul {
    margin: 0 0 var(--space-2);
    padding-left: var(--space-5);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .error,
  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
