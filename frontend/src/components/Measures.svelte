<script lang="ts">
  // The « Measures » tab of the Models screen (docs/modernization/PARITY.md, item 10): the quick speed test, the bench of the installed models side by
  // side (speed, then tools, code, French and instructions, each question kept with its result) with the regressions it noticed, and the comparison
  // of the engines on the model in use. One measure at a time; the page follows a measure running (also one started before a reload).
  import { onMount } from "svelte";
  import SpeedTest from "./SpeedTest.svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t, type MessageKey } from "../lib/messages";

  type Test = { points: number; out_of: number; details: { test: string; ok: boolean }[] };
  type Result = { model: string; date: string; complete: boolean; engine: string | null; error: string; speed: { tokens_per_s: number | null; load_s: number | null } | null; tests: Record<string, Test>; grades: Record<string, number> };
  type Regression = { model: string; kind: string; before: number; after: number; engine_changed: boolean };
  type Bench = { running: string; step: string; queue: string[]; error: string; results: Result[]; regressions: Regression[] };
  type EngineRun = { id: string; name: string; model: string; ok: boolean; errors: string[]; load_s: number | null; first_token_s: number | null; tokens_per_s: number | null; vram_bytes: number | null; ram_bytes: number | null };
  type Comparison = {
    model: string;
    outdated: boolean;
    comparable: number;
    availability: { name: string; reason: string }[];
    running: boolean;
    step: string;
    error: string;
    recommendation: { engine: string; name: string; reason: string; limits: string[] } | null;
    result: { date: string; mode: string; engines: EngineRun[]; skipped: { name: string; reason: string }[] } | null;
  };

  let { installed, canConfigure }: { installed: string[]; canConfigure: boolean } = $props();

  const TESTS = ["tools", "code", "french", "instructions"] as const;
  const lang = language();
  let bench = $state<Bench | null>(null);
  let comparison = $state<Comparison | null>(null);
  let chosen = $state<string[]>([]);
  let quick = $state(false);
  let busy = $state(false);
  let problem = $state("");
  let alive = true;

  const number = (value: number | null | undefined, digits = 1): string => (value === null || value === undefined ? "—" : new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(value));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function follow(): Promise<void> {
    while (alive) {
      bench = await api<Bench>("GET", "/bench");
      comparison = await api<Comparison>("GET", "/engines/comparison");
      if (!bench.running && !comparison.running) break;
      await new Promise((done) => setTimeout(done, 1500));
    }
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    problem = "";
    try {
      await action();
      await follow();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const measure = (): Promise<void> => act(() => api("POST", "/bench", { models: chosen, quick }));
  const compare = (mode: "quick" | "deep"): Promise<void> => act(() => api("POST", "/engines/comparison", { mode }));

  onMount(() => {
    void follow().catch((cause) => (problem = explain(cause)));
    return () => {
      alive = false;
    };
  });
</script>

<div class="measures">
  <SpeedTest />
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  <section class="bench" aria-labelledby="bench-title">
    <h2 id="bench-title">{t("bench.title")}</h2>
    <p class="muted">{t("bench.intro")}</p>
    {#if installed.length}
      <fieldset disabled={busy || !!bench?.running}>
        <legend>{t("bench.which")}</legend>
        <div class="choices">
          {#each installed as name (name)}<label><input type="checkbox" value={name} bind:group={chosen} /> {name}</label>{/each}
        </div>
        <label><input type="checkbox" bind:checked={quick} /> {t("bench.quick")}</label>
        <div class="actions"><button type="button" class="button primary" disabled={!chosen.length || chosen.length > 8} onclick={measure}>{t("bench.start")}</button></div>
      </fieldset>
    {:else}
      <p class="muted">{t("models.none")}</p>
    {/if}
    {#if bench}
      <p class="notice" role="status">{bench.running ? t("bench.running", bench.running, bench.step) + (bench.queue.length ? " " + t("bench.queue", bench.queue.join(", ")) : "") : ""}</p>
      {#if bench.error}<p class="problem">{bench.error}</p>{/if}
      {#each bench.regressions as regression (regression.model + regression.kind)}
        <p class="warn">{t("bench.regression", regression.model, t(("bench.kind." + regression.kind) as MessageKey), number(regression.before, 2), number(regression.after, 2))}{regression.engine_changed ? " " + t("bench.engine_changed") : ""}</p>
      {/each}
      {#if bench.results.length}
        <div class="table">
          <table>
            <caption class="visually-hidden">{t("bench.title")}</caption>
            <thead>
              <tr><th scope="col">{t("bench.model")}</th><th scope="col">{t("bench.speed")}</th><th scope="col">{t("bench.load")}</th>{#each TESTS as test (test)}<th scope="col">{t(("bench.kind." + test) as MessageKey)}</th>{/each}</tr>
            </thead>
            <tbody>
              {#each bench.results as result (result.model)}
                <tr>
                  <th scope="row">{result.model}<small>{result.date.replace("T", " ")}</small></th>
                  <td>{number(result.speed?.tokens_per_s)}</td>
                  <td>{number(result.speed?.load_s)}</td>
                  {#each TESTS as test (test)}<td>{result.tests[test] ? result.tests[test].points + "/" + result.tests[test].out_of : "—"}</td>{/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#each bench.results.filter((result) => Object.keys(result.tests).length) as result (result.model)}
          <details>
            <summary>{t("bench.details", result.model)}</summary>
            {#if result.error}<p class="problem">{result.error}</p>{/if}
            <ul>
              {#each Object.entries(result.tests) as [name, test] (name)}
                {#each test.details as detail, index (index)}<li class={detail.ok ? "ok" : "failed"}>{detail.ok ? "✔" : "✘"} {t(("bench.kind." + name) as MessageKey)} · {detail.test}</li>{/each}
              {/each}
            </ul>
          </details>
        {/each}
      {/if}
    {/if}
  </section>

  <section class="comparison" aria-labelledby="comparison-title">
    <h2 id="comparison-title">{t("compare.title")}</h2>
    {#if comparison}
      <p class="muted">{t("compare.intro", comparison.model || "—")}</p>
      {#if comparison.recommendation}<p><strong>{t("compare.advice", comparison.recommendation.name)}</strong> {comparison.recommendation.reason}</p>{/if}
      {#each comparison.recommendation?.limits ?? [] as limit, index (index)}<p class="muted">{limit}</p>{/each}
      <p class="notice" role="status">{comparison.running ? t("compare.running", comparison.step) : ""}</p>
      {#if comparison.error}<p class="problem">{comparison.error}</p>{/if}
      {#if comparison.result}
        {#if comparison.outdated}<p class="warn">{t("compare.outdated")}</p>{/if}
        <div class="table">
          <table>
            <caption class="visually-hidden">{t("compare.title")}</caption>
            <thead><tr><th scope="col">{t("compare.engine")}</th><th scope="col">{t("bench.speed")}</th><th scope="col">{t("compare.first")}</th><th scope="col">{t("bench.load")}</th><th scope="col">{t("compare.memory")}</th></tr></thead>
            <tbody>
              {#each comparison.result.engines as run (run.id)}
                <tr>
                  <th scope="row">{run.name}<small>{run.model}</small></th>
                  {#if run.ok}
                    <td>{number(run.tokens_per_s)}</td><td>{number(run.first_token_s, 2)}</td><td>{number(run.load_s)}</td>
                    <td>{run.vram_bytes ? formatBytes(run.vram_bytes, lang) : run.ram_bytes ? formatBytes(run.ram_bytes, lang) : "—"}</td>
                  {:else}
                    <td colspan="4" class="failed">{run.errors.join(" ; ") || t("compare.failed")}</td>
                  {/if}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#each comparison.result.skipped as skipped (skipped.name)}<p class="muted">{skipped.name} : {skipped.reason}</p>{/each}
      {/if}
      {#if comparison.comparable < 2}
        <p class="muted">{t("compare.not_enough")}</p>
        <ul class="muted">{#each comparison.availability.filter((a) => a.reason) as entry (entry.name)}<li>{entry.name} : {entry.reason}</li>{/each}</ul>
      {:else if canConfigure}
        <div class="actions">
          <button type="button" class="button primary" disabled={busy || comparison.running} onclick={() => compare("quick")}>{t("compare.quick")}</button>
          <button type="button" class="button" disabled={busy || comparison.running} onclick={() => compare("deep")}>{t("compare.deep")}</button>
        </div>
      {:else}
        <p class="muted">{t("compare.only_here")}</p>
      {/if}
    {/if}
  </section>
</div>

<style>
  .measures,
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .measures {
    gap: var(--space-5);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
  }

  .muted,
  small {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  small {
    display: block;
    font-weight: normal;
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

  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    min-width: 0;
  }

  .choices,
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
  }

  .table {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    min-width: 100%;
  }

  th,
  td {
    padding: var(--space-1) var(--space-2);
    border-bottom: 1px solid var(--color-border);
    text-align: left;
    white-space: nowrap;
  }

  ul {
    margin: var(--space-2) 0 0;
    padding-left: var(--space-4);
  }
</style>
