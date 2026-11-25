<script lang="ts">
  // « Web search » in the section « Knowledge » of Settings (docs/modernization/PARITY.md, item 8): the engines in the order they are tried, a SearXNG
  // of one's own, the personal keys of Brave, Tavily, Exa and Perplexity (never shown again: only their last four characters), and « Test the
  // search », which asks each engine separately. Changing them is for this machine (`can_configure`); testing is for anyone.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type Key = { provider: string; kept: boolean; ends_with: string };
  type Engine = { id: string; configured: boolean; paused_s: number; at_home: boolean };
  type View = { searxng: string; keys: Key[]; engines: Engine[]; can_configure: boolean; offline: boolean };
  type Tried = { id: string; ok: boolean; count: number; ms: number; error: string; example: string };

  let view = $state<View | null>(null);
  let searxng = $state("");
  let typed = $state<Record<string, string>>({});
  let busy = $state(false);
  let testing = $state(false);
  let tried = $state<Tried[] | null>(null);
  let notice = $state("");
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  function shown(answer: View): void {
    view = answer;
    searxng = answer.searxng;
  }

  async function change(body: { searxng?: string; keys?: Record<string, string> }): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    try {
      shown(await api<View>("PATCH", "/web-search", body));
      typed = {};
      notice = t("web.saved");
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function test(): Promise<void> {
    testing = true;
    problem = "";
    notice = t("web.testing");
    tried = null;
    try {
      tried = (await api<{ results: Tried[] }>("POST", "/web-search/test", {})).results;
      notice = tried.some((one) => one.ok) ? "" : t("web.none_answers");
      shown(await api<View>("GET", "/web-search"));
    } catch (cause) {
      notice = "";
      problem = explain(cause);
    }
    testing = false;
  }

  const minutes = (seconds: number): number => Math.max(1, Math.ceil(seconds / 60));

  onMount(() => {
    api<View>("GET", "/web-search").then(shown, (cause) => (problem = explain(cause)));
  });
</script>

<section class="web-search" aria-labelledby="web-search-title">
  <h2 id="web-search-title">{t("web.title")}</h2>
  <p class="muted">{t("web.help")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if view}
    {#if view.offline}<p class="warn">{t("web.offline")}</p>{/if}
    <h3>{t("web.order")}</h3>
    <ol class="engines">
      {#each view.engines as engine (engine.id)}
        <li>
          <span class="name">{t(("web.engine." + engine.id) as MessageKey)}</span>
          {#if engine.configured}<span class="tag">{t("web.yours")}</span>{/if}
          {#if engine.at_home}<span class="tag">{t("web.at_home")}</span>{/if}
          {#if engine.paused_s > 0}<span class="muted">{t("web.paused", minutes(engine.paused_s))}</span>{/if}
        </li>
      {/each}
    </ol>

    {#if !view.can_configure}<p class="muted">{t("web.locked")}</p>{/if}

    <form class="row" onsubmit={(event) => (event.preventDefault(), void change({ searxng: searxng.trim() }))}>
      <label for="web-searxng">SearXNG<small>{t("web.searxng_help")}</small></label>
      <div class="line">
        <input id="web-searxng" type="text" placeholder="http://127.0.0.1:8080" autocomplete="off" bind:value={searxng} disabled={!view.can_configure || busy} />
        <button type="submit" class="button" disabled={!view.can_configure || busy}>{t("web.save")}</button>
      </div>
    </form>

    <p class="muted">{t("web.keys_help")}</p>
    {#each view.keys as key (key.provider)}
      <form class="row" onsubmit={(event) => (event.preventDefault(), (typed[key.provider] ?? "").trim() && void change({ keys: { [key.provider]: (typed[key.provider] ?? "").trim() } }))}>
        <label for={"web-key-" + key.provider}>{t(("web.engine." + key.provider) as MessageKey)}<small>{t(("web.key_help." + key.provider) as MessageKey)}</small></label>
        <div class="line">
          <input id={"web-key-" + key.provider} type="password" placeholder={t("web.key")} autocomplete="off" bind:value={typed[key.provider]} disabled={!view.can_configure || busy} />
          <button type="submit" class="button" disabled={!view.can_configure || busy}>{t("web.save")}</button>
          {#if key.kept && view.can_configure}
            <button type="button" class="button" disabled={busy} onclick={() => change({ keys: { [key.provider]: "" } })}>{t("web.remove_key")}</button>
          {/if}
          <span class="muted state">{key.kept ? t("web.key_kept", key.ends_with) : t("web.no_key")}</span>
        </div>
      </form>
    {/each}

    <div class="actions">
      <button type="button" class="button primary" disabled={testing || view.offline} onclick={test}>{t("web.test")}</button>
    </div>
    {#if tried}
      <ul class="tried">
        {#each tried as one (one.id)}
          <li class={one.ok ? "ok" : "failed"}>
            <span>{one.ok ? "✔" : "✘"} {t(("web.engine." + one.id) as MessageKey)}</span>
            <span>{one.ok ? t("web.results", one.count) : one.error} · {one.ms} ms</span>
            {#if one.example}<span class="muted">{one.example}</span>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .web-search {
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
    font-size: var(--text-md, 1rem);
  }

  .muted,
  small {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    max-width: var(--measure);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem,
  .failed {
    color: var(--color-danger);
  }

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .engines,
  .tried {
    margin: 0;
    padding-left: var(--space-5, 1.5rem);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .engines li,
  .tried li {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: baseline;
    overflow-wrap: anywhere;
  }

  .tried {
    list-style: none;
    padding-left: 0;
  }

  .name {
    font-weight: 600;
  }

  .tag {
    padding: 0 var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-surface-raised);
    font-size: var(--text-sm);
  }

  .row {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  label {
    display: flex;
    flex-direction: column;
    font-weight: 600;
  }

  label small {
    font-weight: normal;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }

  .line input {
    flex: 1 1 16rem;
    min-width: 0;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
