<script lang="ts">
  // The precisions of one Ollama model (q4, q8, fp16…), read on ollama.com and judged for this machine (docs/modernization/PARITY.md, item 10). Each
  // says what it means and how it fits; a download waits for a second click that says its size.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";

  type Fit = { level: string; text: string } | null;
  type Variant = { name: string; precision: string; size_gb: number; default: boolean; installed: boolean; meaning: string; fit: Fit };

  let { model, onstarted }: { model: string; onstarted: () => void } = $props();

  const lang = language();
  let variants = $state<Variant[] | null>(null);
  let asking = $state("");
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const gb = (value: number): string => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function download(variant: Variant): Promise<void> {
    busy = true;
    problem = "";
    try {
      await api("POST", "/models", { name: variant.name });
      asking = "";
      notice = t("models.cat.started", variant.name);
      onstarted();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    api<{ variants: Variant[] }>("GET", "/models/variants?model=" + encodeURIComponent(model)).then((answer) => (variants = answer.variants), (cause) => (problem = explain(cause)));
  });
</script>

<div class="variants">
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if variants === null}
    {#if !problem}<p class="muted">{t("variants.loading")}</p>{/if}
  {:else if variants.length === 0}
    <p class="muted">{t("variants.none")}</p>
  {:else}
    <ul aria-label={t("variants.title", model)}>
      {#each variants as variant (variant.name)}
        <li>
          <p class="line">
            <strong>{variant.precision}</strong>
            <span class="muted">{t("upkeep.size", gb(variant.size_gb))}</span>
            {#if variant.default}<span class="tag">{t("variants.default")}</span>{/if}
            {#if variant.installed}<span class="tag">{t("variants.installed")}</span>{/if}
            {#if variant.fit}<span class={"fit " + variant.fit.level}>{t(("guide.fit." + variant.fit.level) as MessageKey)}</span>{/if}
          </p>
          <p class="muted">{variant.meaning}</p>
          {#if !variant.installed}
            {#if asking === variant.name}
              <p class="line" role="group" aria-label={variant.name}>
                <span>{t("variants.confirm", variant.name, gb(variant.size_gb))}</span>
                <button type="button" class="button primary" disabled={busy} onclick={() => download(variant)}>{t("models.download")}</button>
                <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
              </p>
            {:else}
              <button type="button" class="button" disabled={busy} onclick={() => (asking = variant.name)}>{t("variants.get", variant.precision)}</button>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .variants {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  p {
    margin: 0;
  }

  ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    align-items: flex-start;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem {
    color: var(--color-danger);
  }

  .tag,
  .fit {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--color-surface-raised);
  }

  .fit.comfortable,
  .fit.good {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .fit.tight,
  .fit.too_big {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }
</style>
