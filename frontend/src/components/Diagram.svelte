<script lang="ts">
  // A diagram of an answer: its drawing when Mermaid could make one (lib/diagram.ts, ADR 0011), its code otherwise and on request.
  // The drawing is an image: nothing in it can run, and nothing of it is read as markup by this page.
  import { onMount, type Snippet } from "svelte";
  import { t } from "../lib/messages";
  import { drawDiagram, forgetDiagram, type Drawing } from "../lib/diagram";
  import { isDark, watchDark } from "../lib/theme";

  let { source, children }: { source: string; children: Snippet } = $props();

  let dark = $state(isDark());
  let drawing = $state<Drawing | null>(null);
  let failed = $state(false);
  let asCode = $state(false);

  onMount(() => watchDark((now) => (dark = now)));

  $effect(() => {
    const [text, theme] = [source, dark];
    let current = true; // an answer to an older text or theme is dropped
    failed = false;
    drawDiagram(text, theme).then(
      (done) => {
        if (current) drawing = done;
      },
      () => {
        if (current) [drawing, failed] = [null, true];
      },
    );
    return () => {
      current = false;
    };
  });

  function broken(): void {
    forgetDiagram(source, dark);
    [drawing, failed] = [null, true];
  }
</script>

{#if drawing && !asCode}
  <figure class="diagram">
    <figcaption>
      <span>{t("md.diagram")}</span>
      <button type="button" onclick={() => (asCode = true)}>{t("md.diagram.code")}</button>
    </figcaption>
    <div class="drawing"><img src={drawing.url} width={drawing.width} height={drawing.height} alt={t("md.diagram.alt")} onerror={broken} /></div>
  </figure>
{:else}
  {@render children()}
  {#if drawing}
    <p class="note"><button type="button" onclick={() => (asCode = false)}>{t("md.diagram.show")}</button></p>
  {:else if failed}
    <p class="note">{t("md.diagram.failed")}</p>
  {/if}
{/if}

<style>
  .diagram {
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

  button {
    min-height: 2rem;
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    cursor: pointer;
  }

  button:hover {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .drawing {
    padding: var(--space-3);
    text-align: center;
  }

  img {
    max-width: 100%;
    height: auto;
    vertical-align: middle;
  }

  .note {
    margin: calc(-1 * var(--space-2)) 0 0;
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }
</style>
