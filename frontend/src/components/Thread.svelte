<script lang="ts">
  import LutinFace from "./LutinFace.svelte";
  import { answerMood } from "../lib/lutin_mood";
  // The messages of a conversation: what is stored, then the message just sent and the answer being written.
  import { t } from "../lib/messages";
  import Icon from "./Icon.svelte";
  import Markdown from "./Markdown.svelte";
  import Produced from "./Produced.svelte";
  import { attachmentUrl, imageUrl } from "../lib/place";
  import type { Block, Item, LiveTurn, Sent } from "../lib/turn";
  import { copyText } from "../lib/clipboard";

  // `machine`: the paired machine that holds the conversation ("" for this one): its images and documents are read from it.
  // `onregenerate`: answer again from the last request (shown on the last answer only, when nothing runs).
  // `conversation`, `canOpen`, `canDelete`, `onproduced`: what a tool produced, opened or deleted from the thread (components/Produced.svelte).
  let { items, pending, live, onedit, onregenerate, onpin, onverify, machine = "", conversation = "", canOpen = false, canDelete = false, onproduced, modelLoaded = null }: {
    items: Item[];
    pending: ({ text: string } & Sent) | null;
    live: LiveTurn | null;
    modelLoaded?: boolean | null; // the model of the answer being written is in memory (null: not known): its face sleeps while it is loaded
    onedit?: (item: Extract<Item, { role: "user" }>) => void;
    onregenerate?: () => void;
    onpin?: (index: number, pinned: boolean) => void; // a request pinned: always in front of the model
    onverify?: (question: string) => void; // « Verify »: the raw web results for the question that this answer answers
    machine?: string;
    conversation?: string;
    canOpen?: boolean;
    canDelete?: boolean;
    onproduced?: (kind: "media" | "files", id: string) => void;
  } = $props();
  let copied = $state(-1);

  /** The text of an answer, without its thinking and its tools: what « Copy » puts on the clipboard. */
  function answerText(blocks: Block[]): string {
    return blocks.filter((block) => block.kind === "text").map((block) => (block as { text: string }).text).join("\n\n").trim();
  }

  async function copy(blocks: Block[], index: number): Promise<void> {
    await copyText(answerText(blocks));
    copied = index;
    setTimeout(() => (copied = copied === index ? -1 : copied), 2000);
  }

  const lastAnswer = $derived(items.map((item) => item.role).lastIndexOf("assistant"));
  const when = (at: string | undefined): string => (at ? new Date(at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "");

  /** The request an answer answers: the user item just before it. */
  function questionOf(index: number): string {
    for (let i = index - 1; i >= 0; i -= 1) {
      const item = items[i];
      if (item.role === "user") return item.text;
    }
    return "";
  }

  function shown(value: unknown): string {
    if (value === null || value === undefined) return "";
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
</script>

{#snippet sentView(sent: Sent)}
  {#if sent.images.length}
    <div class="sent">
      {#each sent.images as id (id)}<img src={imageUrl(machine, id)} alt={t("chat.image_sent")} loading="lazy" />{/each}
    </div>
  {/if}
  {#if sent.files.length}
    <ul class="files">
      {#each sent.files as file, index (index)}<li><Icon name="file" size={16} /><a href={attachmentUrl(machine, file.id, file.name)} download={file.name}>{t("chat.file_sent", file.name)}</a></li>{/each}
    </ul>
  {/if}
{/snippet}

{#snippet blocksView(blocks: Block[], settled: boolean)}
  {#each blocks as block, index (index)}
    {#if block.kind === "text"}
      <Markdown source={block.text} />
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
      {#if conversation}<Produced produced={block.produced} {conversation} {machine} {canOpen} canDelete={canDelete && settled} ondeleted={onproduced} />{/if}
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
      <li class="mine">
        {#if onedit}
          <button type="button" class="edit" onclick={() => onedit(item)}><Icon name="pencil" size={16} /><span class="visually-hidden">{t("chat.edit")}</span></button>
        {/if}
        <div class="user">
          <h2 class="visually-hidden">{t("chat.you")}</h2>
          {@render sentView(item)}
          <p class="text">{item.text}</p>
          <p class="meta">
            {#if item.at}<time datetime={item.at}>{when(item.at)}</time>{/if}
            {#if onpin}<button type="button" class="quiet-action pin" aria-pressed={!!item.pinned} onclick={() => onpin(item.index, !item.pinned)}>{item.pinned ? t("thread.unpin") : t("thread.pin")}</button>{:else if item.pinned}<span>{t("thread.pinned")}</span>{/if}
          </p>
        </div>
      </li>
    {:else}
      <li class="assistant">
        <h2 class="who"><img src="/logo.svg" alt="" width="22" height="22" />{t("chat.assistant")}</h2>
        {@render blocksView(item.blocks, !live)}
        {#if answerText(item.blocks)}
          <div class="answer-actions">
            <button type="button" class="quiet-action copy" onclick={() => copy(item.blocks, index)}>{copied === index ? t("chat.copied") : t("chat.copy")}</button>
            {#if onregenerate && index === lastAnswer && !pending && !live}<button type="button" class="quiet-action regenerate" onclick={onregenerate}>{t("chat.regenerate")}</button>{/if}
            {#if onverify && questionOf(index)}<button type="button" class="quiet-action verify" onclick={() => onverify(questionOf(index))}>{t("thread.verify")}</button>{/if}
            {#if item.at}<time class="when" datetime={item.at}>{when(item.at)}</time>{/if}
          </div>
        {/if}
      </li>
    {/if}
  {/each}
  {#if pending}
    <li class="mine">
      <div class="user">
        <h2 class="visually-hidden">{t("chat.you")}</h2>
        {@render sentView(pending)}
        <p class="text">{pending.text}</p>
      </div>
    </li>
  {/if}
  {#if live}
    <li class="assistant">
      <h2 class="who"><LutinFace mood={answerMood(true, live.blocks.length === 0, modelLoaded) === "sleep" ? "sleep" : "thinking"} size={22} />{t("chat.assistant")}</h2>
      {@render blocksView(live.blocks, false)}
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
      <p class="status" aria-live="polite">{#if !live.done}<span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>{live.status || t("chat.working")}{/if}</p>
    </li>
  {/if}
</ol>

<style>
  .thread {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
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

  .thread > li.mine {
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-1);
  }

  .edit {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: var(--target);
    height: var(--target);
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  .edit:hover {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  /* With a mouse, the button shows when the message is pointed at or reached with the keyboard; on a touch screen it is always there. */
  @media (hover: hover) {
    .edit {
      opacity: 0;
    }

    .mine:hover .edit,
    .edit:focus-visible {
      opacity: 1;
    }
  }

  .user {
    min-width: 0;
    max-width: 85%;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg);
    background: var(--color-accent-soft);
  }

  .who {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    font-weight: 650;
  }

  .sent {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  .sent img {
    max-width: 100%;
    max-height: 14rem;
    border-radius: var(--radius-md);
    object-fit: contain;
  }

  .files {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0 0 var(--space-2);
    padding: 0;
    list-style: none;
    font-size: var(--text-sm);
  }

  .files a {
    color: var(--color-accent-text);
    overflow-wrap: anywhere;
  }

  .files li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
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
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
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
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 1.5em;
    font-size: var(--text-sm);
    color: var(--color-text-muted);
  }

  /* Three dots that breathe while Lutin works; still when the system asks for less motion (styles/base.css). */
  .dots {
    display: inline-flex;
    gap: 4px;
  }

  .dots i {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-pill);
    background: var(--color-accent);
    animation: breathe 1.2s ease-in-out infinite;
  }

  .dots i:nth-child(2) {
    animation-delay: 0.15s;
  }

  .dots i:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes breathe {
    0%,
    80%,
    100% {
      opacity: 0.25;
      transform: scale(0.8);
    }

    40% {
      opacity: 1;
      transform: scale(1);
    }
  }

  .answer-actions {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }

  .quiet-action {
    min-height: 2rem;
    padding: 0 var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: none;
    color: var(--color-text-muted);
    font: inherit;
    font-size: var(--text-xs);
    cursor: pointer;
  }

  .quiet-action:hover {
    color: var(--color-text);
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
    margin: var(--space-1) 0 0;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
  }

  .when {
    align-self: center;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
  }
</style>
