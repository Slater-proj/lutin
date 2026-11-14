<script lang="ts">
  // An answer written in Markdown, drawn with real elements from the tree of lib/markdown.ts. Nothing here interprets HTML.
  import { t } from "../lib/messages";
  import { parseMarkdown, type Block, type Inline } from "../lib/markdown";

  let { source }: { source: string } = $props();

  const blocks = $derived(parseMarkdown(source));
  const canCopy = typeof navigator !== "undefined" && !!navigator.clipboard; // absent on a page served over plain HTTP from another machine
  let copied = $state("");

  async function copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      copied = text;
      setTimeout(() => {
        if (copied === text) copied = "";
      }, 1500);
    } catch {
      copied = "";
    }
  }
</script>

{#snippet inline(nodes: Inline[])}
  <!-- On one line on purpose: a line break between two pieces would become a space inside a word. -->
  {#each nodes as node, index (index)}{#if node.kind === "text"}{node.text}{:else if node.kind === "code"}<code>{node.text}</code>{:else if node.kind === "strong"}<strong>{@render inline(node.children)}</strong>{:else if node.kind === "em"}<em>{@render inline(node.children)}</em>{:else if node.kind === "link"}<a href={node.href} target="_blank" rel="noopener noreferrer">{@render inline(node.children)}</a>{/if}{/each}
{/snippet}

{#snippet block(nodes: Block[])}
  {#each nodes as node, index (index)}
    {#if node.kind === "paragraph"}
      <p>{@render inline(node.children)}</p>
    {:else if node.kind === "heading"}
      <!-- An answer never owns the outline of the page: its headings start at level 3, under the name of who speaks. -->
      {#if node.level === 1}<h3 class="h1">{@render inline(node.children)}</h3>
      {:else if node.level === 2}<h4 class="h2">{@render inline(node.children)}</h4>
      {:else}<h5 class="h3">{@render inline(node.children)}</h5>{/if}
    {:else if node.kind === "code"}
      <figure class="code">
        <figcaption>
          <span>{node.language || t("md.code")}</span>
          {#if canCopy}<button type="button" onclick={() => copy(node.text)}>{copied === node.text ? t("md.copied") : t("md.copy")}</button>{/if}
        </figcaption>
        <pre><code>{node.text}</code></pre>
      </figure>
    {:else if node.kind === "list"}
      {#if node.ordered}
        <ol start={node.start}>
          {#each node.items as item, at (at)}<li>{@render block(item)}</li>{/each}
        </ol>
      {:else}
        <ul>
          {#each node.items as item, at (at)}<li>{@render block(item)}</li>{/each}
        </ul>
      {/if}
    {:else if node.kind === "quote"}
      <blockquote>{@render block(node.children)}</blockquote>
    {:else if node.kind === "table"}
      <div class="table">
        <table>
          <thead>
            <tr>{#each node.head as cell, at (at)}<th scope="col">{@render inline(cell)}</th>{/each}</tr>
          </thead>
          <tbody>
            {#each node.rows as row, at (at)}
              <tr>{#each row as cell, column (column)}<td>{@render inline(cell)}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else if node.kind === "rule"}
      <hr />
    {/if}
  {/each}
{/snippet}

<div class="markdown">{@render block(blocks)}</div>

<style>
  .markdown {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
    overflow-wrap: anywhere;
  }

  p {
    white-space: pre-line;
  }

  .h1,
  .h2,
  .h3 {
    margin: var(--space-2) 0 0;
    font-weight: 650;
    line-height: 1.3;
  }

  .h1 {
    font-size: var(--text-lg);
  }

  .h2 {
    font-size: 1.1rem;
  }

  .h3 {
    font-size: var(--text-md);
  }

  ul,
  ol {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding-left: var(--space-5);
  }

  ul {
    list-style-type: disc;
  }

  ul ul {
    list-style-type: circle;
  }

  li > :global(* + *) {
    margin-top: var(--space-1);
  }

  li::marker {
    color: var(--color-text-muted);
  }

  :not(pre) > code {
    padding: 0.1em 0.35em;
    border-radius: var(--radius-sm);
    background: var(--color-code-bg);
    font-size: 0.9em;
  }

  .code {
    margin: 0;
    overflow: hidden;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-code-bg);
  }

  figcaption {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
    border-bottom: 1px solid var(--color-border);
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  figcaption button {
    min-height: 2rem;
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  figcaption button:hover {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  pre {
    margin: 0;
    padding: var(--space-3);
    overflow-x: auto;
    line-height: 1.45;
    tab-size: 4;
  }

  blockquote {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-1) 0 var(--space-1) var(--space-4);
    border-left: 3px solid var(--color-border-strong);
    color: var(--color-text-muted);
  }

  .table {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    font-size: var(--text-sm);
  }

  th,
  td {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    text-align: left;
    vertical-align: top;
  }

  th {
    background: var(--color-surface-raised);
    font-weight: 600;
  }

  hr {
    width: 100%;
    margin: var(--space-1) 0;
    border: 0;
    border-top: 1px solid var(--color-border);
  }
</style>
