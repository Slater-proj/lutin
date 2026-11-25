<script lang="ts">
  // What the names and the badges of the models mean, said simply and the same for every engine, then what the engine in use allows and which engine
  // to take for what (maintainer, 2026-11-21: « I know nothing about it, I am lost with the names, Exl3, 4.00bpw, 30b »). Folded by default once read.
  import { t, type MessageKey } from "../lib/messages";

  let { engine }: { engine: string } = $props();
  const TERMS = ["params", "experts", "quant", "size", "format_gguf", "format_exl3", "uncensored", "fit"] as const;
  const known = $derived(["ollama", "llamacpp", "exllamav3", "lmstudio", "colibri", "openai"].includes(engine) ? engine : "openai");
</script>

<details class="model-help">
  <summary>{t("help.title")}</summary>
  <dl>
    {#each TERMS as term (term)}
      <dt>{t(("help.term." + term) as MessageKey)}</dt>
      <dd>{t(("help." + term) as MessageKey)}</dd>
    {/each}
  </dl>
  <h3>{t("help.engine_title")}</h3>
  <p>{t(("help.engine." + known) as MessageKey)}</p>
  <p class="muted">{t("help.which_engine")}</p>
</details>

<style>
  .model-help {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface-raised);
    font-size: var(--text-sm);
  }

  summary {
    min-height: var(--target);
    display: flex;
    align-items: center;
    color: var(--color-accent-text);
    font-weight: 600;
    cursor: pointer;
  }

  dl {
    display: grid;
    grid-template-columns: minmax(8rem, max-content) 1fr;
    gap: var(--space-1) var(--space-3);
    margin: var(--space-2) 0;
  }

  dt {
    font-weight: 600;
  }

  dd {
    margin: 0;
    max-width: var(--measure);
  }

  @media (max-width: 40rem) {
    dl {
      grid-template-columns: 1fr;
    }

    dd {
      margin-bottom: var(--space-2);
    }
  }

  h3 {
    margin: var(--space-2) 0 var(--space-1);
    font-size: var(--text-sm);
  }

  p {
    margin: 0 0 var(--space-1);
    max-width: var(--measure);
  }

  .muted {
    color: var(--color-text-muted);
  }
</style>
