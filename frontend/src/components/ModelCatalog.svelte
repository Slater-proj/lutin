<script lang="ts">
  // The « Catalogue » tab of the Models screen: every model Lutin knows, with what it is for, how it fits this machine, what it is good and less
  // good at, and a download that waits for a second click saying what it costs. By default only what runs here; « All » shows the rest.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";
  import { shown, strengths, runsHere, type CatalogModel } from "../lib/model_catalog";

  let { onstarted }: { onstarted: () => void } = $props();

  type Catalog = { detected: boolean; disclaimer: string; models: CatalogModel[] };
  const lang = language();
  let catalog = $state<Catalog | null>(null);
  let only = $state<"fits" | "all">("fits");
  let advanced = $state(false);
  let asking = $state("");
  let busy = $state(false);
  let problem = $state("");
  let notice = $state("");

  const list = $derived(catalog ? shown(catalog.models, only) : []);
  const role = (name: string): string => t(("guide.role." + name) as MessageKey);
  const gb = (value: number): string => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    try {
      problem = "";
      catalog = await api<Catalog>("GET", "/models/catalog" + (advanced ? "?advanced=1" : ""));
    } catch (cause) {
      problem = explain(cause);
    }
  }

  async function download(model: CatalogModel): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      await api("POST", "/models", { name: model.id });
      asking = "";
      notice = t("models.cat.started", model.name);
      onstarted();
      await load();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => void load());
</script>

<section class="catalog-models" aria-labelledby="catalog-title">
  <h2 id="catalog-title">{t("models.cat.title")}</h2>
  <p class="muted">{t("models.cat.intro")}</p>
  <div class="filters">
    <label for="catalog-only">{t("models.cat.show")}</label>
    <select id="catalog-only" bind:value={only}>
      <option value="fits">{t("models.cat.only_fits")}</option>
      <option value="all">{t("models.cat.all")}</option>
    </select>
    <label class="inline"><input type="checkbox" bind:checked={advanced} onchange={() => void load()} /> {t("models.cat.advanced")}</label>
  </div>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if !catalog}
    {#if !problem}<p class="muted">{t("models.cat.loading")}</p>{/if}
  {:else}
    {#if !catalog.detected}<p class="muted">{t("models.cat.not_detected")}</p>{/if}
    {#if list.length === 0}
      <p class="empty">{t("models.cat.none")}</p>
    {:else}
      <ul class="cards" aria-label={t("models.cat.title")}>
        {#each list as model (model.id)}
          {@const good = strengths(model.roles)}
          <li class="card" class:installed={model.installed} data-id={model.id}>
            <div class="line">
              <strong>{model.name}</strong>
              {#if model.installed}<span class="tag">{t("models.cat.installed")}</span>{/if}
              {#if model.fit}<span class={"fit " + model.fit.level}>{t(("guide.fit." + model.fit.level) as MessageKey)}</span>{/if}
            </div>
            <p class="summary">{model.summary}</p>
            <p class="meta">{t("models.cat.meta", gb(model.size_gb), gb(model.parameters_b), Math.round(model.context_max / 1024))}{model.licence ? " · " + model.licence : ""}</p>
            {#if model.fit?.text}<p class="muted fit-text">{model.fit.text}</p>{/if}
            {#if good.strong.length}<p class="plus">{t("models.cat.strong", good.strong.map(role).join(", "))}</p>{/if}
            {#if good.weak.length}<p class="minus">{t("models.cat.weak", good.weak.map(role).join(", "))}</p>{/if}
            {#if model.capabilities.length}
              <ul class="chips" aria-label={t("models.cat.capabilities")}>
                {#each model.capabilities as capability (capability)}<li>{t(("models.cat.cap." + capability) as MessageKey)}</li>{/each}
              </ul>
            {/if}
            {#if model.warning}<p class="warn">{model.warning}</p>{/if}
            {#each model.compatibility.reasons as reason (reason)}<p class="warn">{reason}</p>{/each}
            {#if !model.installed && runsHere(model)}
              {#if asking === model.id}
                <div class="confirm" role="group" aria-label={t("models.cat.download")}>
                  <p>{t("models.cat.confirm", model.name, gb(model.size_gb))}</p>
                  <div class="actions">
                    <button type="button" class="button primary" disabled={busy} onclick={() => download(model)}>{t("models.cat.download")}</button>
                    <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
                  </div>
                </div>
              {:else}
                <div class="actions">
                  <button type="button" class="button" disabled={busy} onclick={() => (asking = model.id)}>{t("models.cat.download")}<span class="visually-hidden"> {model.name}</span></button>
                </div>
              {/if}
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
    {#if catalog.disclaimer}<p class="muted disclaimer">{catalog.disclaimer}</p>{/if}
  {/if}
</section>

<style>
  .catalog-models {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  p {
    margin: 0;
  }

  .muted,
  .meta {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .muted,
  .summary {
    max-width: var(--measure);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }

  .filters label {
    font-weight: 600;
  }

  .filters .inline {
    font-weight: 400;
  }

  select {
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 24rem), 1fr));
    align-items: start;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .card.installed {
    border-color: var(--color-accent);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .tag,
  .fit,
  .chips li {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .tag,
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
    background: var(--color-danger-soft);
    color: var(--color-text);
  }

  .plus,
  .minus {
    font-size: var(--text-sm);
  }

  .plus::before {
    content: "+ ";
    color: var(--color-accent-text);
    font-weight: 700;
  }

  .minus::before {
    content: "− ";
    color: var(--color-text-muted);
    font-weight: 700;
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
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .warn {
    font-size: var(--text-sm);
    color: var(--color-text);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
