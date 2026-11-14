<script lang="ts">
  // The messages of a conversation: what is stored, then the message just sent and the answer being written.
  import { t } from "../lib/messages";
  import type { Block, Item, LiveTurn } from "../lib/turn";

  let { items, pending, live }: { items: Item[]; pending: string; live: LiveTurn | null } = $props();

  function shown(value: unknown): string {
    if (value === null || value === undefined) return "";
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
</script>

{#snippet blocksView(blocks: Block[])}
  {#each blocks as block, index (index)}
    {#if block.kind === "text"}
      <p class="text">{block.text}</p>
    {:else if block.kind === "thinking"}
      <details class="aside">
        <summary>{t("chat.thinking")}</summary>
        <p class="text muted">{block.text}</p>
      </details>
    {:else if block.kind === "tool"}
      <details class="aside">
        <summary>{t("chat.tool", block.name)}{#if block.result === null}<span class="muted">{" · " + t("chat.tool_running")}</span>{/if}</summary>
        {#if shown(block.arguments)}
          <p class="label">{t("chat.tool_arguments")}</p>
          <pre>{shown(block.arguments)}</pre>
        {/if}
        {#if block.result !== null}
          <p class="label">{t("chat.tool_result")}</p>
          <pre>{block.result}</pre>
        {/if}
      </details>
    {:else if block.kind === "notice"}
      <p class="notice">{block.text}</p>
    {:else if block.kind === "dry_run"}
      <details class="aside" open>
        <summary>{t("chat.dry_run", block.title)}</summary>
        {#if block.detail}<p class="text">{block.detail}</p>{/if}
        {#if block.diff}<pre>{block.diff}</pre>{/if}
      </details>
    {:else if block.kind === "error"}
      <p class="error" role="alert">{block.message}</p>
    {/if}
  {/each}
{/snippet}

<ol class="thread">
  {#each items as item, index (index)}
    {#if item.role === "user"}
      <li class="user">
        <h2 class="visually-hidden">{t("chat.you")}</h2>
        <p class="text">{item.text}</p>
      </li>
    {:else}
      <li class="assistant">
        <h2 class="who">{t("chat.assistant")}</h2>
        {@render blocksView(item.blocks)}
      </li>
    {/if}
  {/each}
  {#if pending}
    <li class="user">
      <h2 class="visually-hidden">{t("chat.you")}</h2>
      <p class="text">{pending}</p>
    </li>
  {/if}
  {#if live}
    <li class="assistant">
      <h2 class="who">{t("chat.assistant")}</h2>
      {@render blocksView(live.blocks)}
      {#if live.tasks.length}
        <div class="tasks">
          <p class="label">{t("chat.tasks")}</p>
          <ul>
            {#each live.tasks as task, index (index)}
              <li class={task.state}>
                {task.text}
                <span class="muted">{" · " + t(task.state === "done" ? "chat.task_done" : task.state === "in_progress" ? "chat.task_in_progress" : "chat.task_todo")}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      <p class="status" aria-live="polite">{live.done ? "" : live.status || t("chat.working")}</p>
    </li>
  {/if}
</ol>

<style>
  .thread {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    width: 100%;
    max-width: var(--measure);
    margin: 0 auto;
    padding: var(--space-4);
    list-style: none;
  }

  .thread > li {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }

  .user {
    align-self: flex-end;
    max-width: 85%;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-lg);
    background: var(--color-accent-soft);
  }

  .who {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--color-text-muted);
  }

  .text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .label {
    margin-top: var(--space-2);
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--color-text-muted);
  }

  .aside {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: var(--text-sm);
  }

  .aside summary {
    cursor: pointer;
    font-weight: 600;
  }

  pre {
    max-height: 20rem;
    margin: var(--space-1) 0 0;
    padding: var(--space-2) var(--space-3);
    overflow: auto;
    border-radius: var(--radius-sm);
    background: var(--color-code-bg);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .notice {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .error {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }

  .tasks ul {
    margin: var(--space-1) 0 0;
    padding-left: var(--space-5);
    font-size: var(--text-sm);
  }

  .tasks li.done {
    color: var(--color-text-muted);
    text-decoration: line-through;
  }

  .status {
    min-height: 1.5em;
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }
</style>
