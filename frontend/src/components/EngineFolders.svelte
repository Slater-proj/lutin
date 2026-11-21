<script lang="ts">
  // Two folders of the Engines tab (docs/modernization/PARITY.md, item 11): where every engine installs (it changes once none is installed in the
  // current one: nothing is moved behind the person's back), and where Ollama keeps its models: analysed first (network or local disk, speed, room),
  // the models already downloaded copied in the background (the source is never deleted), then chosen, then Ollama restarted.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes, percent } from "../lib/format";
  import { language, t } from "../lib/messages";

  type EnginesFolder = { current: string; default: string; proposed: string | null; free_gb: number | null; source: string; problem: string; changeable: boolean; installed_here: string[] };
  type ModelsFolder = { current: string; chosen: string | null; free_bytes: number | null; copy: { state: string; done_bytes: number; total_bytes: number; file: string; error: string; target: string } };
  type Analysis = { path: string; network: boolean; warnings: string[]; free_bytes: number | null; exists: boolean; models_here: boolean; source_exists: boolean; source_bytes: number };

  let { canConfigure, ollama }: { canConfigure: boolean; ollama: boolean } = $props();

  const lang = language();
  let engines = $state<EnginesFolder | null>(null);
  let models = $state<ModelsFolder | null>(null);
  let enginesPath = $state("");
  let modelsPath = $state("");
  let analysis = $state<Analysis | null>(null);
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");
  let timer: ReturnType<typeof setInterval> | undefined;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const follow = (): void => {
    clearInterval(timer);
    timer = setInterval(async () => {
      models = await api<ModelsFolder>("GET", "/models/folder").catch(() => models);
      if (models?.copy.state !== "running") clearInterval(timer);
    }, 1500);
  };

  const saveEngines = (): Promise<void> => act(async () => {
      engines = await api<EnginesFolder>("PATCH", "/engines/folder", { path: enginesPath.trim() });
      notice = t("web.saved");
    });
  const analyse = (): Promise<void> => act(async () => void (analysis = await api<Analysis>("POST", "/models/folder/analysis", { path: modelsPath.trim() })));
  const copy = (): Promise<void> => act(async () => ((models = await api<ModelsFolder>("POST", "/models/folder/copy", { path: modelsPath.trim() })), follow()));
  const choose = (): Promise<void> => act(async () => {
      models = await api<ModelsFolder>("PATCH", "/models/folder", { path: modelsPath.trim() });
      notice = t("folders.chosen");
    });
  const restart = (): Promise<void> => act(async () => void (notice = (await api<{ message: string }>("POST", "/models/folder/restart-ollama", {})).message));

  onMount(() => {
    api<EnginesFolder>("GET", "/engines/folder").then((answer) => (engines = answer), (cause) => (problem = explain(cause)));
    if (ollama) api<ModelsFolder>("GET", "/models/folder").then((answer) => ((models = answer), answer.copy.state === "running" && follow()), () => undefined);
    return () => clearInterval(timer);
  });
</script>

<section class="folders" aria-labelledby="folders-title">
  <h2 id="folders-title">{t("folders.title")}</h2>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if engines}
    <h3>{t("folders.engines")}</h3>
    <p class="muted">{t("folders.engines_now", engines.current)}{engines.free_gb !== null ? " · " + t("folders.free_gb", engines.free_gb) : ""}</p>
    {#if engines.problem}<p class="warn">{engines.problem}</p>{/if}
    {#if engines.installed_here.length}<p class="muted">{t("folders.engines_installed", engines.installed_here.join(", "))}</p>{/if}
    {#if canConfigure && engines.changeable}
      <div class="row">
        <label class="field">{t("folders.new_path")}<input type="text" placeholder={engines.proposed ?? engines.default} bind:value={enginesPath} /></label>
        <button type="button" class="button" disabled={busy} onclick={saveEngines}>{t("web.save")}</button>
      </div>
    {/if}
  {/if}

  {#if ollama && models}
    <h3>{t("folders.models")}</h3>
    <p class="muted">{t("folders.models_now", models.current)}{models.free_bytes !== null ? " · " + t("folders.free", formatBytes(models.free_bytes, lang)) : ""}</p>
    {#if models.copy.state === "running"}
      {@const share = percent(models.copy.done_bytes, models.copy.total_bytes)}
      <progress max="100" value={share ?? undefined} aria-label={t("folders.copying")}></progress>
      <p class="muted" role="status">{t("folders.copying")} {models.copy.file}{share !== null ? " · " + share + " %" : ""}</p>
    {:else if models.copy.state === "done"}
      <p class="muted">{t("folders.copied", models.copy.target)}</p>
    {:else if models.copy.state === "failed"}
      <p class="problem">{models.copy.error}</p>
    {/if}
    {#if canConfigure}
      <div class="row">
        <label class="field">{t("folders.new_path")}<input type="text" placeholder="D:/IA/ollama" bind:value={modelsPath} /></label>
        <button type="button" class="button" disabled={busy || !modelsPath.trim()} onclick={analyse}>{t("folders.analyse")}</button>
      </div>
      {#if analysis}
        <div class="card">
          <p>{analysis.network ? t("folders.network") : t("folders.local")}{analysis.free_bytes !== null ? " · " + t("folders.free", formatBytes(analysis.free_bytes, lang)) : ""}</p>
          {#each analysis.warnings as warning, index (index)}<p class="warn">{warning}</p>{/each}
          {#if analysis.source_exists && analysis.source_bytes}<p class="muted">{t("folders.to_copy", formatBytes(analysis.source_bytes, lang))}</p>{/if}
          <div class="row">
            {#if analysis.source_exists && !analysis.models_here}<button type="button" class="button" disabled={busy || models.copy.state === "running"} onclick={copy}>{t("folders.copy")}</button>{/if}
            <button type="button" class="button primary" disabled={busy || models.copy.state === "running"} onclick={choose}>{t("folders.use")}</button>
            <button type="button" class="button" disabled={busy} onclick={restart}>{t("folders.restart")}</button>
          </div>
          <p class="help">{t("folders.use_help")}</p>
        </div>
      {/if}
    {/if}
  {/if}
</section>

<style>
  .folders {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
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
    margin-top: var(--space-2);
    font-size: var(--text-md, 1rem);
  }

  .muted,
  .help {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
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

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-2);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    flex: 1 1 16rem;
    min-width: 0;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }
</style>
