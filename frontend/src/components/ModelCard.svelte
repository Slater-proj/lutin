<script lang="ts">
  // One card for a model, the same wherever it is shown and whatever the engine (maintainer, 2026-11-21): its name and the name to download, whether
  // it fits this machine, whether its refusals were removed, what its name says (size, experts, quantisation, format, use), its size, a short
  // description, and the same buttons. The buttons that act (download after a confirmation, delete, use, precisions) come from the page that shows the
  // card, which knows how its engine does them; « Details » leads to the page of the model where it comes from.
  import type { Snippet } from "svelte";
  import { language, t, type MessageKey } from "../lib/messages";
  import { detailsLink, readName, type Use } from "../lib/model_card";

  type Fit = { level: string; text: string } | null;
  let {
    name,
    reference,
    revision = "",
    sizeGb = null,
    approximate = false,
    fit = null,
    installed = false,
    inUse = false,
    incomplete = false,
    engine,
    summary = "",
    actions,
  }: {
    name: string;
    reference: string;
    revision?: string;
    sizeGb?: number | null;
    approximate?: boolean;
    fit?: Fit;
    installed?: boolean;
    inUse?: boolean;
    incomplete?: boolean;
    engine: string;
    summary?: string;
    actions?: Snippet;
  } = $props();

  const lang = language();
  const facts = $derived(readName(name + " " + reference, revision));
  const link = $derived(detailsLink(reference, engine));
  const number = (value: number): string => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);

  function describe(): string {
    if (summary) return summary;
    const parts: string[] = [];
    if (facts.paramsB !== null) parts.push(facts.family ? t("card.desc.family", facts.family, number(facts.paramsB)) : t("card.desc.size", number(facts.paramsB)));
    if (facts.activeB !== null) parts.push(t("card.desc.experts", number(facts.activeB)));
    parts.push(t(("card.desc.use." + facts.uses[0]) as MessageKey));
    if (facts.bpw !== null) parts.push(t("card.desc.bpw", number(facts.bpw)));
    else if (facts.quant) parts.push(t("card.desc.quant", facts.quant));
    if (facts.uncensored) parts.push(t("card.desc.uncensored"));
    return parts.join(" ");
  }

  const useLabel = (use: Use): string => t(("card.use." + use) as MessageKey);
</script>

<li class="card model-card" class:installed class:current={inUse} data-model={reference}>
  <div class="head">
    <strong>{name}</strong>
    {#if inUse}<span class="tag">{t("models.in_use")}</span>{:else if installed}<span class="tag">{t("variants.installed")}</span>{/if}
    {#if fit}<span class={"fit " + fit.level} title={fit.text}>{t(("guide.fit." + fit.level) as MessageKey)}</span>{/if}
    {#if facts.uncensored}<span class="uncensored" title={t("card.uncensored_help")}>{t("card.uncensored")}</span>{/if}
  </div>
  <p class="download-name">{t("card.download_name")} <code>{reference}{revision ? "@" + revision : ""}</code></p>
  <ul class="chips" aria-label={t("card.facts")}>
    {#if sizeGb}<li class="size">{approximate ? t("card.about_gb", number(sizeGb)) : t("card.gb", number(sizeGb))}</li>{/if}
    {#if facts.paramsB !== null}<li title={t("help.params")}>{t("card.params", number(facts.paramsB))}</li>{/if}
    {#if facts.activeB !== null}<li title={t("help.experts")}>{t("card.active", number(facts.activeB))}</li>{/if}
    {#if facts.bpw !== null}<li title={t("help.quant")}>{t("card.bpw", number(facts.bpw))}</li>{:else if facts.quant}<li title={t("help.quant")}>{facts.quant}</li>{/if}
    {#if facts.format}<li title={t(("help.format_" + facts.format) as MessageKey)}>{facts.format.toUpperCase()}</li>{/if}
    {#each facts.uses as use (use)}<li>{useLabel(use)}</li>{/each}
  </ul>
  <p class="summary">{describe()}</p>
  {#if fit?.text}<p class="muted">{fit.text}</p>{/if}
  {#if incomplete}<p class="problem">{t("managed.incomplete")}</p>{/if}
  <div class="actions">
    {@render actions?.()}
    {#if link}<a class="button quiet" href={link} target="_blank" rel="noopener noreferrer">{t("card.details")}<span class="visually-hidden"> {name}</span></a>{/if}
  </div>
</li>

<style>
  .model-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    list-style: none;
  }

  .model-card.installed,
  .model-card.current {
    border-color: var(--color-accent-soft);
  }

  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .head strong {
    overflow-wrap: anywhere;
  }

  p {
    margin: 0;
  }

  .download-name,
  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .summary {
    max-width: var(--measure);
  }

  .problem {
    color: var(--color-danger);
  }

  .tag,
  .fit,
  .uncensored {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .tag {
    background: var(--color-surface-raised);
  }

  .fit.comfortable,
  .fit.good {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .fit.tight {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }

  .fit.too_big {
    background: var(--color-danger);
    color: var(--color-on-accent);
  }

  .uncensored {
    border: 1px solid var(--color-warning, #c58b00);
    color: var(--color-text);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .chips li {
    padding: 0 var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
  }

  .chips .size {
    font-weight: 600;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
</style>
