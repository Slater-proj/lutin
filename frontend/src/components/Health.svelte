<script lang="ts">
  // The health of this machine for the models (docs/modernization/PARITY.md, item 2), in the section « Health » of Settings: memory, graphics card
  // and disk with their advice, what is loaded and what occupies the machine, unloading, the self-test, what the models and tools did, and what
  // left this machine. Read again every 10 s while it is shown.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t, type MessageKey } from "../lib/messages";

  type Item = { id: string; name: string; level: "ok" | "warning" | "critical"; value: string; advice: string };
  type Loaded = { id: string; kind: string; engine: string; name: string; vram: number | null; ram: number | null; size: number | null; detail: string; unloadable: boolean };
  type Resources = { ram: { total: number | null; free: number | null }; vram: { name: string; total: number | null; used: number | null; free: number | null } | null; loaded: Loaded[];
    programs: { name: string; label: string; count: number; bytes: number; ai: boolean }[] };
  type Health = { level: Item["level"]; items: Item[]; resources: Resources };
  type Check = { name: string; ok: boolean; important: boolean; detail: string; seconds: number };
  type Activity = { models: { model: string; machine: string; turns: number; tokens: number; tokens_per_s: number | null }[]; tools: { tool: string; calls: number; failures: number; duration_ms: number }[] };
  type Outbound = { entries: { at: string; service: string; request: string; removed: string[]; ok: boolean }[] };

  const lang = language();
  let health = $state<Health | null>(null);
  let checks = $state<{ ok: boolean; deep: boolean; checks: Check[] } | null>(null);
  let activity = $state<Activity | null>(null);
  let outbound = $state<Outbound | null>(null);
  let problem = $state("");
  let notice = $state("");
  let busy = $state(false);
  let alive = true;

  const bytes = (value: number | null | undefined): string => (value ? formatBytes(value, lang) : "—");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.code === "configurator" ? t("health.not_here") : cause.message || t("error.generic", cause.code);
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    const [state, done, sent] = await Promise.all([api<Health>("GET", "/health"), api<Activity>("GET", "/health/activity"), api<Outbound>("GET", "/health/outbound")]);
    health = state;
    activity = done;
    outbound = sent;
  }

  async function act(action: () => Promise<string>): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    notice = "";
    try {
      notice = await action();
      await load();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const unload = (entry: Loaded): Promise<void> => act(async () => (await api<{ message: string }>("POST", "/health/unload", { id: entry.id })).message);
  const freeAll = (): Promise<void> => act(async () => (await api<{ message: string }>("POST", "/health/free-graphics-memory")).message);
  const selfTest = (deep: boolean): Promise<void> =>
    act(async () => {
      checks = await api<{ ok: boolean; deep: boolean; checks: Check[] }>("POST", "/health/self-test", { deep });
      return checks.ok ? t("health.selftest_ok") : t("health.selftest_bad");
    });
  const clearLog = (which: "activity" | "outbound"): Promise<void> => act(async () => (await api("DELETE", "/health/" + which), t("health.cleared")));

  onMount(() => {
    void load().catch((cause) => (problem = explain(cause)));
    const timer = setInterval(() => {
      if (alive && !busy) void load().catch(() => undefined);
    }, 10000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

<section class="health" aria-labelledby="health-title">
  <h2 id="health-title">{t("health.title")}</h2>
  <p class="muted">{t("health.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if !health}
    {#if !problem}<p class="muted">{t("health.loading")}</p>{/if}
  {:else}
    <ul class="items">
      {#each health.items as item (item.id)}
        <li class={"item " + item.level}>
          <div class="line"><strong>{item.name}</strong><span class={"level " + item.level}>{t(("health.level." + item.level) as MessageKey)}</span></div>
          <p>{item.value}</p>
          {#if item.advice}<p class="muted">{item.advice}</p>{/if}
        </li>
      {/each}
    </ul>

    <div class="part">
      <h3>{t("health.loaded")}</h3>
      <p class="muted">{t("health.memory", bytes(health.resources.ram.free), bytes(health.resources.ram.total))}{#if health.resources.vram}{" · " + t("health.vram", health.resources.vram.name, bytes(health.resources.vram.free), bytes(health.resources.vram.total))}{/if}</p>
      {#if health.resources.loaded.length === 0}
        <p class="muted">{t("health.nothing_loaded")}</p>
      {:else}
        <ul class="loaded">
          {#each health.resources.loaded as entry (entry.id)}
            <li>
              <span><strong>{entry.name}</strong> <span class="muted">{entry.engine}{entry.size ? " · " + bytes(entry.size) : ""}{entry.detail ? " · " + entry.detail : ""}</span></span>
              {#if entry.unloadable}<button type="button" class="button quiet" disabled={busy} onclick={() => unload(entry)}>{t("health.unload")}<span class="visually-hidden"> {entry.name}</span></button>{/if}
            </li>
          {/each}
        </ul>
      {/if}
      <div class="actions"><button type="button" class="button" disabled={busy} onclick={freeAll}>{t("health.free_all")}</button></div>
      {#if health.resources.programs.length}
        <details>
          <summary>{t("health.programs")}</summary>
          <ul class="programs">{#each health.resources.programs as program (program.name)}<li>{program.label} <span class="muted">{bytes(program.bytes)}{program.count > 1 ? " · ×" + program.count : ""}</span></li>{/each}</ul>
        </details>
      {/if}
    </div>

    <div class="part">
      <h3>{t("health.selftest")}</h3>
      <p class="muted">{t("health.selftest_help")}</p>
      <div class="actions">
        <button type="button" class="button primary" disabled={busy} onclick={() => selfTest(false)}>{t("health.selftest_quick")}</button>
        <button type="button" class="button" disabled={busy} onclick={() => selfTest(true)}>{t("health.selftest_deep")}</button>
      </div>
      {#if checks}
        <ul class="checks">
          {#each checks.checks as check (check.name)}
            <li class:bad={!check.ok}><span aria-hidden="true">{check.ok ? "✓" : "✗"}</span> <strong>{check.name}</strong> <span class="muted">{check.detail} · {check.seconds} s</span></li>
          {/each}
        </ul>
      {/if}
    </div>

    {#if activity}
      <div class="part">
        <h3>{t("health.activity")}</h3>
        {#if activity.models.length === 0 && activity.tools.length === 0}
          <p class="muted">{t("health.no_activity")}</p>
        {:else}
          {#each activity.models as model (model.model + model.machine)}<p>{t("health.model_line", model.model, model.turns, model.tokens)}</p>{/each}
          {#each activity.tools as tool (tool.tool)}<p class="muted">{t("health.tool_line", tool.tool, tool.calls, tool.failures)}</p>{/each}
        {/if}
        <div class="actions"><button type="button" class="button quiet" disabled={busy} onclick={() => clearLog("activity")}>{t("health.clear")}</button></div>
      </div>
    {/if}

    {#if outbound}
      <div class="part">
        <h3>{t("health.outbound")}</h3>
        <p class="muted">{t("health.outbound_help")}</p>
        {#if outbound.entries.length === 0}
          <p class="muted">{t("health.nothing_sent")}</p>
        {:else}
          <ul class="sent">{#each outbound.entries as entry, index (index)}<li><span class="muted">{entry.at} · {entry.service}</span> {entry.request}</li>{/each}</ul>
          <div class="actions"><button type="button" class="button quiet" disabled={busy} onclick={() => clearLog("outbound")}>{t("health.clear")}</button></div>
        {/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  .health {
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
    font-size: var(--text-sm);
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

  .items {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .item {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .item.warning {
    background: var(--color-warning-soft);
  }

  .item.critical {
    border-color: var(--color-danger);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .level {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .level.warning {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }

  .level.critical {
    background: var(--color-danger-soft);
    color: var(--color-text);
  }

  .part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  .loaded,
  .checks,
  .sent,
  .programs {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-sm);
  }

  .loaded li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .checks .bad {
    color: var(--color-danger);
  }

  .sent li {
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
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
</style>
