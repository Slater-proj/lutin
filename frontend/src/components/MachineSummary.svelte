<script lang="ts">
  // This machine in plain words, and the memory a model may fill when the detection is wrong. The same block in the guide of the first launch and at the
  // top of « Recommended » for every engine (maintainer, 2026-11-22: one presentation whatever the engine): what the recommendations are judged against.
  // The detection starts programs: the server answers at once and the block asks again, for 30 seconds at most.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import type { Machine } from "../lib/guide";
  import { t } from "../lib/messages";

  let {
    machine = $bindable(null),
    ondetected,
    onchanged,
  }: {
    machine?: Machine | null;
    ondetected?: () => void; // the machine is known: what depends on it can be asked
    onchanged?: () => void; // the memory given to models changed: the verdicts are to be asked again
  } = $props();

  let failed = $state(false);
  let draft = $state<number | null>(null);
  let busy = $state(false);
  let problem = $state("");
  let alive = true;

  const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function detect(): Promise<void> {
    for (let attempt = 0; attempt < 20 && alive; attempt += 1) {
      machine = await api<Machine>("GET", "/machine");
      if (machine.detected) {
        ondetected?.();
        return;
      }
      await wait(1500);
    }
    failed = true;
  }

  /** The memory a model may fill, given by the person (0 gives it back to the detection). */
  async function setBudget(value: number): Promise<void> {
    busy = true;
    try {
      problem = "";
      await api("PATCH", "/settings", { memory_budget_gb: value });
      machine = await api<Machine>("GET", "/machine");
      draft = null;
      onchanged?.();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function save(event: SubmitEvent): void {
    event.preventDefault();
    if (draft) void setBudget(draft);
  }

  onMount(() => {
    detect().catch((cause) => (problem = explain(cause)));
    return () => {
      alive = false;
    };
  });
</script>

<div class="machine" aria-live="polite">
  {#if machine?.detected}
    <p class="muted">{t("guide.machine")}</p>
    <p class="summary">{machine.summary}</p>
    <details class="correct">
      <summary>{t("guide.correct")}</summary>
      <form onsubmit={save}>
        <label for="budget">{t("guide.budget_label")}</label>
        <input id="budget" type="number" min="1" max="4096" step="0.5" inputmode="decimal" bind:value={draft} aria-describedby="budget-help" />
        <p id="budget-help" class="muted">{t("guide.budget_help", machine.budget_gb ?? 0)}</p>
        <div class="actions">
          <button type="submit" class="button primary" disabled={!draft || busy}>{t("guide.budget_save")}</button>
          {#if machine.budget_set_gb}<button type="button" class="button" onclick={() => setBudget(0)} disabled={busy}>{t("guide.budget_reset")}</button>{/if}
        </div>
      </form>
    </details>
  {:else if failed}
    <p class="warn">{t("guide.detect_failed")}</p>
  {:else}
    <p class="muted"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> {t("guide.detecting")}</p>
  {/if}
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
</div>

<style>
  .machine {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  p {
    margin: 0;
  }

  .summary {
    font-weight: 600;
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .warn,
  .problem {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .problem {
    margin-top: var(--space-2);
    border: 1px solid var(--color-danger);
    background: var(--color-danger-soft);
  }

  .correct {
    margin-top: var(--space-2);
    font-size: var(--text-sm);
  }

  .correct summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .correct form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: 20rem;
  }

  .correct input {
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    color: var(--color-text);
    font: inherit;
  }

  .correct .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
