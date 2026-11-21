<script lang="ts">
  // The guide of the first launch: welcome, the engine (started or installed with a confirmation), the choice of a model (the guide of the Models screen), and the end.
  // Nothing is installed or downloaded without a click that says what it does and how big it is; the guide can be left at any step (the downloads go on without the page).
  import { onMount } from "svelte";
  import Devices from "../components/Devices.svelte";
  import LanguageChoice from "../components/LanguageChoice.svelte";
  import ModelGuide from "../components/ModelGuide.svelte";
  import SpeedTest from "../components/SpeedTest.svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t, type MessageKey } from "../lib/messages";
  import { after, currentEngine, engineStep, STEPS, working, type EngineView, type Step } from "../lib/setup";
  import type { Models, Status } from "../lib/types";
  import { percent } from "../lib/format";

  let { status, onfinished }: { status: Status | null; onfinished: () => void } = $props();

  const lang = language();
  let step = $state<Step>("welcome");
  let engines = $state<EngineView[] | null>(null);
  let models = $state<Models | null>(null);
  let confirming = $state(false);
  let problem = $state("");
  let busy = $state(false);
  let alive = true;

  const engine = $derived(engines ? currentEngine(engines) : undefined);
  const offer = $derived(engineStep(engine));
  const task = $derived(engine?.task ?? null);
  const downloads = $derived(models?.downloads ?? []);
  const downloading = $derived(downloads.some((download) => download.state === "downloading"));
  const hasModel = $derived((models?.models.length ?? 0) > 0);

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

  async function loadEngines(): Promise<void> {
    engines = (await api<{ engines: EngineView[] }>("GET", "/engines")).engines;
  }

  async function loadModels(): Promise<void> {
    models = await api<Models>("GET", "/models");
  }

  // The model of the first launch becomes the one in use, as soon as its download starts (the old default named a model that may never be installed).
  async function choose(model: string): Promise<void> {
    await api("PATCH", "/settings", { model });
    await loadModels();
  }

  async function run(action: "install" | "start"): Promise<void> {
    if (!engine || busy) return;
    busy = true;
    await guarded(async () => {
      await api("POST", `/engines/${encodeURIComponent(engine.id)}/actions/${action}`, action === "install" ? { confirm: true } : {});
      confirming = false;
      await loadEngines();
    });
    busy = false;
  }

  async function finish(skipped: boolean): Promise<void> {
    await guarded(async () => {
      await api("POST", "/setup/complete", { skipped });
      onfinished();
    });
  }

  function go(next: Step): void {
    step = next;
    problem = "";
    confirming = false;
    if (next === "engine") void guarded(loadEngines);
    if (next === "model" || next === "done") void guarded(loadModels);
  }

  onMount(() => {
    // While something installs or downloads, the state is read again every second; otherwise it is left alone.
    const timer = setInterval(() => {
      if (!alive) return;
      if (step === "engine" && working(engine)) void loadEngines().catch(() => undefined);
      if ((step === "model" || step === "done") && downloading) void loadModels().catch(() => undefined);
    }, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

<div class="setup">
  <header>
    <img src="/logo.svg" alt="" width="40" height="40" />
    <p class="brand">Lutin</p>
    <ol class="steps" aria-label={t("setup.steps")}>
      {#each STEPS as name, index (name)}
        <li aria-current={name === step ? "step" : undefined} class:past={STEPS.indexOf(step) > index}>
          <span class="n" aria-hidden="true">{index + 1}</span><span class="label">{t(("setup.step." + name) as MessageKey)}</span>
        </li>
      {/each}
    </ol>
  </header>

  <main id="main" tabindex="-1">
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

    {#if step === "welcome"}
      <section>
        <h1>{t("setup.welcome_title")}</h1>
        <p class="lead">{t("setup.welcome_body")}</p>
        <ul class="promises">
          <li>{t("setup.promise_local")}</li>
          <li>{t("setup.promise_ask")}</li>
          <li>{t("setup.promise_download")}</li>
        </ul>
        <LanguageChoice />
        <div class="actions">
          <button type="button" class="button primary" onclick={() => go("engine")}>{t("setup.start")}</button>
          <button type="button" class="button quiet" onclick={() => finish(true)}>{t("setup.skip")}</button>
        </div>
      </section>
    {:else if step === "engine"}
      <section>
        <h1>{t("setup.engine_title")}</h1>
        <p class="lead">{t("setup.engine_body")}</p>
        {#if !engines}
          <p class="muted" aria-live="polite">{t("setup.engine_looking")}</p>
        {:else if engine}
          <div class="card" aria-live="polite">
            <p class="line"><strong>{engine.name}</strong> <span class={"state " + (engine.running ? "on" : "off")}>{engine.running ? t("setup.engine_running") : engine.installed ? t("setup.engine_stopped") : t("setup.engine_missing")}</span></p>
            {#if task && task.state === "running"}
              {@const share = percent(task.done, task.total)}
              <progress max="100" value={share ?? undefined} aria-label={engine.name}></progress>
              <p class="muted">{task.text}{share !== null ? " · " + share + " %" : ""}{task.total ? " · " + formatBytes(task.done, lang) + " / " + formatBytes(task.total, lang) : ""}</p>
            {:else if task && task.state === "failed"}
              <p class="error">{task.error}</p>
              <p class="muted">{t("setup.engine_by_hand")}</p>
            {/if}
            {#if offer === "start" && !working(engine)}
              <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={() => run("start")}>{t("setup.engine_start", engine.name)}</button></div>
            {:else if offer === "install" && !working(engine)}
              {#if status?.offline}
                <p class="warn">{t("setup.engine_offline")}</p>
              {:else if confirming}
                <div class="confirm" role="group" aria-label={t("setup.engine_confirm_title", engine.name)}>
                  <p><strong>{t("setup.engine_confirm_title", engine.name)}</strong></p>
                  <p>{engine.actions.install.reason}</p>
                  <p class="muted">{t("setup.engine_confirm_note")}</p>
                  <div class="actions">
                    <button type="button" class="button primary" disabled={busy} onclick={() => run("install")}>{t("setup.engine_confirm_yes")}</button>
                    <button type="button" class="button" onclick={() => (confirming = false)}>{t("chat.cancel")}</button>
                  </div>
                </div>
              {:else}
                <p class="muted">{engine.actions.install.reason}</p>
                <div class="actions"><button type="button" class="button primary" onclick={() => (confirming = true)}>{t("setup.engine_install", engine.name)}</button></div>
              {/if}
            {:else if offer === "blocked" && !engine.running}
              <p class="warn">{t("setup.engine_blocked")}</p>
            {/if}
          </div>
        {/if}
        <div class="actions">
          <button type="button" class="button primary" onclick={() => go("model")} disabled={!engine?.running}>{t("setup.next")}</button>
          <button type="button" class="button quiet" onclick={() => go("model")}>{t("setup.engine_later")}</button>
        </div>
      </section>
    {:else if step === "model"}
      <section>
        <h1>{t("setup.model_title")}</h1>
        <p class="lead">{t("setup.model_body")}</p>
        <ModelGuide onstarted={(model) => void guarded(() => choose(model))} onuse={(model) => void guarded(async () => {
          await choose(model);
          go("done");
        })} />
        {#if downloads.length}
          <ul class="downloads" aria-label={t("models.downloads")}>
            {#each downloads as download (download.name)}
              {@const share = percent(download.done_bytes, download.total_bytes)}
              <li>
                <span><strong>{download.name}</strong> <span class="muted">{t(("models.state_" + download.state) as "models.state_done")}{download.state === "downloading" && share !== null ? " · " + share + " %" : ""}</span></span>
                {#if download.state === "downloading"}<progress max="100" value={share ?? undefined} aria-label={download.name}></progress>{/if}
              </li>
            {/each}
          </ul>
        {/if}
        <div class="actions">
          <button type="button" class="button primary" onclick={() => go("done")}>{hasModel ? t("setup.next") : t("setup.model_later")}</button>
        </div>
      </section>
    {:else}
      <section>
        <h1>{t("setup.done_title")}</h1>
        <p class="lead">{hasModel ? t("setup.done_ready") : downloading ? t("setup.done_downloading") : t("setup.done_no_model")}</p>
        {#if downloading}<p class="muted" aria-live="polite">{t("setup.done_goes_on")}</p>{/if}
        {#if hasModel && !downloading && engine?.id === "ollama"}<SpeedTest />{/if}
        <div class="card"><Devices compact /></div>
        <div class="actions"><button type="button" class="button primary" onclick={() => finish(false)}>{t("setup.open_chat")}</button></div>
      </section>
    {/if}
  </main>
</div>

<style>
  .setup {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    min-height: 100%;
    padding: var(--space-5) var(--space-4) var(--space-6);
    position: relative; /* the texts hidden for the eyes inside are placed here and scroll with it, never by <main> (which would scroll too) */
    overflow-y: auto;
    background: var(--color-bg);
  }

  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-5);
    width: 100%;
    max-width: 46rem;
    margin: 0 auto;
  }

  .brand {
    font-size: var(--text-lg);
    font-weight: 700;
  }

  .steps {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    margin: 0 0 0 auto;
    padding: 0;
    list-style: none;
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }

  .steps li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .n {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.6rem;
    height: 1.6rem;
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
  }

  .steps li[aria-current="step"] {
    color: var(--color-text);
    font-weight: 650;
  }

  .steps li[aria-current="step"] .n {
    border-color: var(--color-accent);
    background: var(--color-accent);
    color: var(--color-on-accent);
  }

  .steps li.past .n {
    border-color: var(--color-accent);
    color: var(--color-accent-text);
  }

  main {
    width: 100%;
    max-width: 46rem;
    margin: 0 auto;
    outline: none;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  h1 {
    font-size: var(--text-xl);
    letter-spacing: -0.02em;
    line-height: 1.2;
  }

  .lead {
    font-size: var(--text-lg);
    line-height: 1.5;
  }

  .promises {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding-left: var(--space-5);
    color: var(--color-text-muted);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .problem {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .error {
    color: var(--color-danger);
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }

  .state {
    padding: 0.1rem var(--space-3);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 650;
  }

  .state.on {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .state.off {
    background: var(--color-warning-soft);
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
  }

  progress {
    width: 100%;
    height: 0.6rem;
    accent-color: var(--color-accent);
  }

  .downloads {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .downloads li {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  @media (max-width: 520px) {
    /* The name of a step is hidden from the eyes but kept for screen readers (display: none would leave a bare number). */
    .steps .label {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }
</style>
