<script lang="ts">
  // The Models screen: what is installed, which one Lutin uses, a download with its progress, and deleting a model.
  import { onMount } from "svelte";
  import ModelGuide from "../components/ModelGuide.svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes, percent } from "../lib/format";
  import { language, t } from "../lib/messages";
  import type { Models, Status } from "../lib/types";

  let { status, onchanged }: { status: Status | null; onchanged: () => void } = $props();

  let models = $state<Models | null>(null);
  let problem = $state("");
  let name = $state("");
  let asking = $state(false);
  let tab = $state<"recommended" | "installed" | "unset">("unset"); // chosen once the list is known: the guide when nothing is installed, the list otherwise

  const lang = language();
  const downloading = $derived(models?.downloads.some((download) => download.state === "downloading") ?? false);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function guarded(action: () => Promise<void>): Promise<void> {
    try {
      problem = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
  }

  async function load(): Promise<void> {
    models = await api<Models>("GET", "/models");
    if (tab === "unset") tab = models.models.length === 0 ? "recommended" : "installed";
  }

  async function install(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const wanted = name.trim();
    if (!wanted || asking) return;
    asking = true;
    await guarded(async () => {
      await api("POST", "/models", { name: wanted });
      name = "";
      await load();
    });
    asking = false;
  }

  async function use(model: string): Promise<void> {
    await guarded(async () => {
      await api("PATCH", "/settings", { model });
      await load();
      onchanged();
    });
  }

  async function remove(model: string): Promise<void> {
    if (!confirm(t("models.delete_confirm", model))) return;
    await guarded(async () => {
      await api("DELETE", `/models/${encodeURIComponent(model)}`);
      await load();
      onchanged();
    });
  }

  onMount(() => {
    void guarded(load);
    // While something downloads, the list is read again every second; otherwise it is left alone.
    const timer = setInterval(() => {
      if (downloading) void load().catch(() => undefined);
    }, 1000);
    return () => clearInterval(timer);
  });
</script>

<section class="models">
  <header>
    <h1>{t("models.title")}</h1>
    {#if models}
      <p class="engine" class:down={!models.running}>
        <span class="dot" aria-hidden="true"></span>
        {models.running ? t("models.engine_running", status?.engine.name ?? models.engine) : t("models.engine_stopped", status?.engine.name ?? models.engine)}
      </p>
    {/if}
  </header>

  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if models && !models.running}<p class="hint">{t("models.engine_hint")} <a href="/">{t("legacy.link")}</a></p>{/if}

  {#if models && models.downloads.length}
    <h2>{t("models.downloads")}</h2>
    <ul class="cards downloads">
      {#each models.downloads as download (download.name)}
        {@const share = percent(download.done_bytes, download.total_bytes)}
        <li class="card" data-state={download.state}>
          <div class="line">
            <strong>{download.name}</strong>
            <span class="tag" class:bad={download.state === "failed"}>{t(("models.state_" + download.state) as "models.state_done")}</span>
          </div>
          {#if download.state === "downloading"}
            <progress max="100" value={share ?? undefined} aria-label={download.name}></progress>
            <p class="muted">{download.text}{share !== null ? " · " + share + " %" : ""}{download.total_bytes ? " · " + formatBytes(download.done_bytes, lang) + " / " + formatBytes(download.total_bytes, lang) : ""}</p>
          {:else if download.state === "failed"}
            <p class="error">{download.text}</p>
            {#if download.restart_engine_advised}<p class="muted">{t("models.restart_advised")}</p>{/if}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <div class="tabs" role="group" aria-label={t("models.tabs")}>
    <button type="button" class:on={tab === "recommended"} aria-pressed={tab === "recommended"} onclick={() => (tab = "recommended")}>{t("models.tab_recommended")}</button>
    <button type="button" class:on={tab === "installed"} aria-pressed={tab === "installed"} onclick={() => (tab = "installed")}>{t("models.tab_installed")}</button>
  </div>

  {#if tab === "recommended"}
    <ModelGuide onstarted={() => void guarded(load)} onuse={use} />
  {:else if tab === "installed"}
  <form class="add" onsubmit={install}>
    <label for="model-name">{t("models.add_expert")}</label>
    <div class="row">
      <input id="model-name" type="text" placeholder="qwen3:8b" autocomplete="off" spellcheck="false" bind:value={name} />
      <button type="submit" class="button primary" disabled={!name.trim() || asking}>{t("models.download")}</button>
    </div>
    <p class="help">{t("models.add_help")}</p>
  </form>

  <h2>{t("models.installed")}</h2>
  {#if models && models.models.length === 0}
    <p class="empty">{t("models.none")}</p>
  {:else if models}
    <ul class="cards">
      {#each models.models as model (model.name)}
        <li class="card" class:current={model.name === models.current}>
          <div class="line">
            <strong>{model.name}</strong>
            {#if model.name === models.current}<span class="tag">{t("models.in_use")}</span>{/if}
            {#if model.size_bytes}<span class="muted">{formatBytes(model.size_bytes, lang)}</span>{/if}
          </div>
          <div class="actions">
            {#if model.name !== models.current}<button type="button" class="button" onclick={() => use(model.name)}>{t("models.use")}</button>{/if}
            <button type="button" class="button quiet danger" onclick={() => remove(model.name)}>{t("models.delete")}<span class="visually-hidden"> {model.name}</span></button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
  {/if}
</section>

<style>
  .models {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    width: 100%;
    max-width: var(--measure);
    margin: 0 auto;
    padding: var(--space-5) var(--space-4);
    overflow-y: auto;
  }

  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  h1 {
    font-size: var(--text-xl);
    letter-spacing: -0.02em;
  }

  h2 {
    font-size: var(--text-md);
    font-weight: 650;
  }

  .engine {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0.25rem var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    font-size: var(--text-sm);
  }

  .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: var(--radius-pill);
    background: var(--color-accent);
  }

  .engine.down .dot {
    background: var(--color-danger);
  }

  .tabs {
    display: flex;
    gap: var(--space-1);
    padding: var(--space-1);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    align-self: flex-start;
  }

  .tabs button {
    min-height: 2.5rem;
    padding: 0 var(--space-4);
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--color-text-muted);
    font-weight: 600;
    cursor: pointer;
  }

  .tabs button.on {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .problem {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }

  .hint {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
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

  .add label {
    font-weight: 650;
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  input[type="text"] {
    flex: 1;
    min-width: 10rem;
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }

  .help,
  .muted,
  .empty {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .cards {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .card.current {
    border-color: var(--color-accent);
    background: var(--color-accent-soft);
  }

  .downloads .card {
    flex-direction: column;
    align-items: stretch;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .tag {
    padding: 0.1rem var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-size: var(--text-xs);
    font-weight: 650;
  }

  .tag.bad {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  progress {
    width: 100%;
    height: 0.6rem;
    accent-color: var(--color-accent);
  }

  .error {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .actions {
    display: flex;
    gap: var(--space-2);
  }
</style>
