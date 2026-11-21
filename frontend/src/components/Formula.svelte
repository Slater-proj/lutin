<script lang="ts">
  // A formula of an answer, drawn by the browser from real MathML elements (lib/math.ts): no dependency, no HTML read, no inline style.
  // A formula that uses something the reader of lib/math.ts does not know is shown as it was written.
  import { parseMath, type MathNode } from "../lib/math";

  let { source, display = false }: { source: string; display?: boolean } = $props();

  // Given as a value on purpose: Svelte 5.57 creates an element whose `xmlns` is written as plain text in the SVG namespace, whatever the text says.
  // tests/test_web_app_chat.py checks the namespace of every piece in a real browser.
  const MATHML = "http://www.w3.org/1998/Math/MathML";

  const nodes = $derived(parseMath(source));
</script>

{#snippet row(children: MathNode[])}
  <!-- On one line on purpose: MathML has no use for the spaces between its elements. -->
  {#each children as node, index (index)}<svelte:element this={node.tag} xmlns={MATHML} {...node.attributes}>{#if node.children}{@render row(node.children)}{:else}{node.text ?? ""}{/if}</svelte:element>{/each}
{/snippet}

{#if nodes}<math class="formula" display={display ? "block" : "inline"}>{@render row(nodes)}</math>{:else}<code class="formula-source">{source.trim()}</code>{/if}

<style>
  .formula {
    font-size: 1.08em;
  }

  .formula[display="block"] {
    margin: var(--space-1) 0;
  }

  /* Columns of aligned lines and of cases: MathML Core aligns cells with CSS, not with attributes. */
  .formula :global(mtd.left) {
    text-align: left;
  }

  .formula :global(mtd.right) {
    text-align: right;
  }

  .formula :global(mtable.pairs mtd.right) {
    padding-right: 0;
  }

  .formula :global(mtable.pairs mtd.left) {
    padding-left: 0;
  }

  .formula :global(.boxed) {
    padding: 0.2em 0.4em;
    border: 1px solid currentColor;
  }

  .formula-source {
    padding: 0.1em 0.35em;
    border-radius: var(--radius-sm);
    background: var(--color-code-bg);
    font-size: 0.9em;
  }
</style>
