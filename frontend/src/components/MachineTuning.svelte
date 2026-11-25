<script lang="ts">
  // « Tuning to this machine » in Settings › Machine (docs/modernization/PARITY.md, item 11): the calibration of the processor cores (the speed with a
  // third, half, two thirds and all of them; the smallest number within a few percent of the best is advised), and, on a small machine, the
  // settings worth changing, applied with one click or dismissed for good.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t } from "../lib/messages";

  type Calibration = { running: boolean; step: string; error: string; model: string; date: string; advised_threads: number | null; results: { threads: number; tokens_per_s: number | null }[]; current_threads: number | null };
  type Advice = { advice: { setting: string; current: unknown; advised: unknown; text: string }[]; dismissed: boolean };

  const lang = language();
  let calibration = $state<Calibration | null>(null);
  let advice = $state<Advice | null>(null);
  let canConfigure = $state(false);
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");
  let alive = true;

  const number = (value: number | null): string => (value === null ? "—" : new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function follow(): Promise<void> {
    while (alive) {
      calibration = await api<Calibration>("GET", "/calibration");
      if (!calibration.running) break;
      await new Promise((done) => setTimeout(done, 2000));
    }
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

  const start = (): Promise<void> => act(async () => (await api("POST", "/calibration", {}), await follow()));
  const cancel = (): Promise<void> => act(async () => void (calibration = await api<Calibration>("DELETE", "/calibration")));
  const use = (): Promise<void> => act(async () => {
      calibration = await api<Calibration>("POST", "/calibration/apply", {});
      notice = t("tune.applied");
    });
  const applyAdvice = (): Promise<void> => act(async () => {
      await api("POST", "/machine/advice/apply", {});
      advice = await api<Advice>("GET", "/machine/advice");
      notice = t("tune.applied");
    });
  const dismiss = (): Promise<void> => act(async () => (await api("POST", "/machine/advice/dismiss", {}), void (advice = await api<Advice>("GET", "/machine/advice"))));

  onMount(() => {
    void follow().catch((cause) => (problem = explain(cause)));
    api<Advice>("GET", "/machine/advice").then((answer) => (advice = answer), () => undefined);
    api<{ access: { can_configure: boolean } }>("GET", "/status").then((answer) => (canConfigure = answer.access.can_configure), () => undefined);
    return () => {
      alive = false;
    };
  });
</script>

<section class="tuning" aria-labelledby="tuning-title">
  <h2 id="tuning-title">{t("tune.title")}</h2>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>

  {#if advice && advice.advice.length && !advice.dismissed}
    <div class="card">
      <h3>{t("tune.small_machine")}</h3>
      <ul>{#each advice.advice as item (item.setting)}<li>{item.text}</li>{/each}</ul>
      {#if canConfigure}
        <div class="actions">
          <button type="button" class="button primary" disabled={busy} onclick={applyAdvice}>{t("tune.apply_advice")}</button>
          <button type="button" class="button" disabled={busy} onclick={dismiss}>{t("tune.dismiss")}</button>
        </div>
      {/if}
    </div>
  {/if}

  <h3>{t("tune.cores")}</h3>
  <p class="muted">{t("tune.cores_help")}</p>
  {#if calibration}
    <p>{t("tune.cores_now", calibration.current_threads === null ? t("tune.engine_chooses") : String(calibration.current_threads))}</p>
    {#if calibration.running}<p class="notice" role="status">{t("bench.running", calibration.model, calibration.step)}</p>{/if}
    {#if calibration.error}<p class="problem">{calibration.error}</p>{/if}
    {#if calibration.results.length}
      <ul class="results">
        {#each calibration.results as result (result.threads)}<li>{t("tune.result", result.threads, number(result.tokens_per_s))}</li>{/each}
      </ul>
      {#if calibration.advised_threads !== null}<p><strong>{t("tune.advised", calibration.advised_threads)}</strong></p>{/if}
    {/if}
    {#if canConfigure}
      <div class="actions">
        {#if calibration.running}
          <button type="button" class="button" disabled={busy} onclick={cancel}>{t("chat.cancel")}</button>
        {:else}
          <button type="button" class="button" disabled={busy} onclick={start}>{t("tune.start")}</button>
          {#if calibration.advised_threads !== null && calibration.advised_threads !== calibration.current_threads}
            <button type="button" class="button primary" disabled={busy} onclick={use}>{t("tune.use", calibration.advised_threads)}</button>
          {/if}
        {/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  .tuning,
  .card {
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
    font-size: var(--text-md, 1rem);
  }

  .muted {
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

  .problem {
    color: var(--color-danger);
  }

  .card {
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  ul {
    margin: 0;
    padding-left: var(--space-5, 1.5rem);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
