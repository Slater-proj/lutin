<script lang="ts">
  // The bar at the top of every screen that says what Lutin is downloading or installing, whoever started it and wherever the person is (an engine, a model by Ollama or by the engine
  // in use, the model that searches by meaning). It reads GET /activity; what ended stays a moment, a failure until it is closed: nothing disappears without saying how it ended.
  import { onMount } from "svelte";
  import { closeKey, nextDelay, percent, fraction, visible, type ActivityItem } from "../lib/activity";
  import { api } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  let items = $state<ActivityItem[]>([]);
  let closed = $state<Set<string>>(new Set());
  const shown = $derived(visible(items, closed));

  const ACTIONS = ["install", "reinstall", "update", "uninstall", "start", "download", "prepare", "copy"];

  function title(item: ActivityItem): string {
    return ACTIONS.includes(item.action) ? t(("activity." + item.action) as MessageKey, item.name) : item.name;
  }

  function close(item: ActivityItem): void {
    closed = new Set([...closed, closeKey(item)]);
  }

  onMount(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let running = new Set<string>();

    async function read(): Promise<void> {
      if (!document.hidden) {
        try {
          const answer = await api<{ items: ActivityItem[] }>("GET", "/activity");
          items = answer.items;
          const now = new Set(answer.items.filter((item) => item.state === "running").map((item) => item.id));
          // What ran a moment ago and does not any more: the models and the engines have changed, the rest of the page reads them again.
          if ([...running].some((id) => !now.has(id))) dispatchEvent(new Event("lutin-status"));
          running = now;
        } catch {
          // The server does not answer for an instant (a restart): the bar keeps what it showed and asks again.
        }
      }
      if (!stopped) timer = setTimeout(() => void read(), nextDelay(items));
    }

    void read();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  });
</script>

{#if shown.length}
  <section class="activity" aria-label={t("activity.label")}>
    {#each shown as item (item.id)}
      {@const part = fraction(item)}
      <div class="task" class:failed={item.state === "failed"} class:done={item.state === "done"}>
        <div class="line">
          <strong>{title(item)}</strong>
          {#if item.state === "running"}
            {#if part !== null}<span class="figure">{percent(item)}</span>{/if}
          {:else}
            <span class="badge">{item.state === "failed" ? t("activity.state_failed") : t("activity.state_done")}</span>
          {/if}
          <span class="grow"></span>
          <a href="#/models">{t("activity.details")}</a>
          {#if item.state !== "running"}
            <button type="button" class="close" onclick={() => close(item)} aria-label={t("activity.close")} title={t("activity.close")}>×</button>
          {/if}
        </div>
        {#if item.state === "running"}
          <progress max="1" value={part ?? undefined} aria-label={t("activity.progress", title(item))}></progress>
        {/if}
        {#if item.text}<p class="text" role={item.state === "failed" ? "alert" : undefined}>{item.text}</p>{/if}
      </div>
    {/each}
  </section>
{/if}

<style>
  .activity {
    position: sticky;
    top: 0;
    z-index: 20;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border-strong);
    background: var(--color-surface);
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.12);
  }

  .task {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .grow {
    flex: 1;
  }

  .figure {
    font-variant-numeric: tabular-nums;
    color: var(--color-text-muted);
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }

  .failed .badge {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  progress {
    width: 100%;
    height: 0.5rem;
    accent-color: var(--color-accent);
  }

  .text {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .failed .text {
    color: var(--color-danger);
    white-space: normal;
  }

  .close {
    min-width: 2rem;
    min-height: 2rem;
    border: 0;
    background: transparent;
    color: var(--color-text);
    font-size: var(--text-lg);
    cursor: pointer;
  }
</style>
