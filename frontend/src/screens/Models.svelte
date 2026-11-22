<script lang="ts">
  // The Models screen: the models of the engine in use in three parts, the same for every engine (ADR 0020: Recommended, Search, Installed, drawn by
  // EngineModels), the downloads of Ollama with their progress, the measures, the engines and the other machines. One presentation whatever the engine
  // (maintainer, 2026-11-22: « je veux quelque chose d'unifié en front, pareil peu importe le moteur et la source »): the guide by roles and the catalogue by
  // family that only Ollama and llama.cpp had here are gone from this screen (the guide stays in the first launch); a model by its name is in Search.
  import { onMount } from "svelte";
  import Engines from "../components/Engines.svelte";
  import EngineModels from "../components/EngineModels.svelte";
  import Machines from "../components/Machines.svelte";
  import ModelProposals from "../components/ModelProposals.svelte";
  import Measures from "../components/Measures.svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes, percent } from "../lib/format";
  import { language, t } from "../lib/messages";
  import type { Models, Status } from "../lib/types";

  let { status, onchanged }: { status: Status | null; onchanged: () => void } = $props();
  // Ollama and llama.cpp share the catalogue of Lutin (Ollama tags, which llama.cpp downloads without Ollama) and its proposals of the daily check.
  const CATALOGUE: readonly string[] = ["ollama", "llamacpp"];

  let models = $state<Models | null>(null);
  let problem = $state("");
  let refresh = $state(0); // bumped when a download starts: the engine cards are read again and show its progress
  let tab = $state<"recommended" | "search" | "installed" | "measures" | "engines" | "machines" | "unset">("unset"); // chosen once the list is known: the recommended models when nothing is installed, the list otherwise

  const lang = language();
  const engine = $derived(status?.engine.id ?? "");
  const engineName = $derived(status?.engine.name ?? engine);
  const catalogue = $derived(CATALOGUE.includes(engine));
  const canConfigure = $derived(!!status?.access.can_configure);
  // the installed part is read again when the list of the engine changes (a download ended, a model was deleted elsewhere)
  const installedKey = $derived(models ? models.current + "|" + models.models.map((model) => model.name).join(",") : "");
  const downloading = $derived(models?.downloads.some((download) => download.state === "downloading") ?? false);
  const changed = (): void => {
    void guarded(load);
    onchanged();
  };

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
  {#if models && !models.running}<p class="hint">{t("models.engine_hint")} <button type="button" class="link" onclick={() => (tab = "engines")}>{t("models.tab_engines")}</button></p>{/if}

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
    <button type="button" class:on={tab === "search"} aria-pressed={tab === "search"} onclick={() => (tab = "search")}>{t("models.tab_search")}</button>
    <button type="button" class:on={tab === "installed"} aria-pressed={tab === "installed"} onclick={() => (tab = "installed")}>{t("models.tab_installed")}</button>
    <button type="button" class:on={tab === "measures"} aria-pressed={tab === "measures"} onclick={() => (tab = "measures")}>{t("models.tab_measures")}</button>
    <button type="button" class:on={tab === "engines"} aria-pressed={tab === "engines"} onclick={() => (tab = "engines")}>{t("models.tab_engines")}</button>
    <button type="button" class:on={tab === "machines"} aria-pressed={tab === "machines"} onclick={() => (tab = "machines")}>{t("models.tab_machines")}</button>
  </div>

  {#if tab === "recommended"}
    <EngineModels {engine} {engineName} part="recommended" {canConfigure} onchanged={changed} onstarted={() => void guarded(load)} />
  {:else if tab === "engines"}
    {#key refresh}
      <Engines {canConfigure} onchanged={changed} />
    {/key}
  {:else if tab === "search"}
    <EngineModels {engine} {engineName} part="search" {canConfigure} onchanged={changed} onstarted={() => { refresh += 1; void guarded(load); }} />
  {:else if tab === "measures"}
    <Measures {engine} {engineName} installed={models?.models.map((model) => model.name) ?? []} {canConfigure} />
  {:else if tab === "machines"}
    <Machines onchanged={changed} />
  {:else if tab === "installed"}
    {#if catalogue}
      <ModelProposals onchanged={changed} />
    {/if}
    <EngineModels {engine} {engineName} part="installed" {canConfigure} {installedKey} onchanged={changed} onstarted={() => void guarded(load)} />
  {/if}
</section>

<style>
  .models {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    width: 100%;
    max-width: var(--page-max);
    margin: 0 auto;
    padding: var(--space-5) var(--space-4);
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
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
    flex-wrap: wrap; /* four tabs: on a phone they go on two lines rather than out of the screen */
    gap: var(--space-1);
    max-width: 100%;
    padding: var(--space-1);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
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

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 28rem), 1fr));
    align-items: start;
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

</style>
