<script lang="ts">
  // The « Ollama library » tab of the Models screen (docs/modernization/PARITY.md, item 10): what ollama.com offers, newest or most downloaded first,
  // filtered by a word or a capability. Each size says the space it takes (an estimate) and how it fits this machine; a download waits for a second
  // click. Reading the site needs the network: in strict offline mode the server says so.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";
  import { libraryQuery, sizesShown } from "../lib/library";

  type Size = { size: string; name: string; installed: boolean; estimated_gb: number | null; fit: { level: string; text: string } | null };
  type Model = { name: string; description: string; capabilities: string[]; updated: string; downloads: number; sizes: Size[]; installed_plain: boolean };

  let { onstarted }: { onstarted: () => void } = $props();

  const lang = language();
  let words = $state("");
  let order = $state<"newest" | "popular">("popular");
  let capability = $state("");
  let fitsHere = $state(true); // only the sizes this machine can run; the tight ones stay, marked « limit »
  let uncensored = $state(false); // models without the refusals of the original (uncensored, abliterated…)
  let page = $state(1);
  let models = $state<Model[] | null>(null);
  let more = $state(false);
  let loading = $state(false);
  let asking = $state("");
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const gb = (value: number): string => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);
  const count = (value: number): string => new Intl.NumberFormat(lang, { notation: "compact" }).format(value);
  const visible = $derived((models ?? []).map((model) => ({ model, sizes: sizesShown(model.sizes, fitsHere) })).filter((entry) => entry.sizes.length > 0));
  const hidden = $derived((models ?? []).length - visible.length);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "offline") return t("library.offline");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function search(next = 1): Promise<void> {
    loading = true;
    problem = "";
    try {
      const query = new URLSearchParams({ q: libraryQuery(words, uncensored), order, page: String(next) });
      if (capability) query.set("capability", capability);
      const answer = await api<{ models: Model[]; more: boolean }>("GET", "/models/library?" + query.toString());
      models = next === 1 ? answer.models : [...(models ?? []), ...answer.models];
      more = answer.more;
      page = next;
    } catch (cause) {
      problem = explain(cause);
    }
    loading = false;
  }

  async function download(size: Size): Promise<void> {
    busy = true;
    problem = "";
    try {
      await api("POST", "/models", { name: size.name });
      asking = "";
      notice = t("models.cat.started", size.name);
      onstarted();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => void search());
</script>

<section class="ollama-library" aria-labelledby="ollama-library-title">
  <h2 id="ollama-library-title">{t("olib.title")}</h2>
  <p class="muted">{t("olib.intro")}</p>
  <form class="filters" onsubmit={(event) => (event.preventDefault(), void search())}>
    <label class="field">{t("olib.words")}<input type="search" placeholder="qwen, gemma…" bind:value={words} /></label>
    <label class="field">{t("olib.order")}
      <select bind:value={order} onchange={() => void search()}>
        <option value="popular">{t("olib.popular")}</option>
        <option value="newest">{t("olib.newest")}</option>
      </select>
    </label>
    <label class="field">{t("olib.capability")}
      <select bind:value={capability} onchange={() => void search()}>
        <option value="">{t("olib.any")}</option>
        <option value="tools">{t("olib.cap.tools")}</option>
        <option value="vision">{t("olib.cap.vision")}</option>
        <option value="thinking">{t("olib.cap.thinking")}</option>
      </select>
    </label>
    <button type="submit" class="button" disabled={loading}>{t("olib.search")}</button>
    <div class="boxes">
      <label class="inline"><input type="checkbox" bind:checked={fitsHere} /> {t("olib.fits_here")}</label>
      <label class="inline"><input type="checkbox" bind:checked={uncensored} onchange={() => void search()} /> {t("olib.uncensored")}</label>
    </div>
  </form>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{loading ? t("olib.loading") : notice}</p>
  {#if models}
    {#if visible.length === 0}<p class="muted">{t("olib.none")}</p>{/if}
    {#if hidden > 0}<p class="muted">{t("olib.hidden", String(hidden))}</p>{/if}
    <ul class="cards">
      {#each visible as { model, sizes } (model.name)}
        <li class="card">
          <p class="line"><strong>{model.name}</strong><span class="muted">{t("olib.downloads", count(model.downloads))}{model.updated ? " · " + model.updated : ""}</span></p>
          {#if model.description}<p>{model.description}</p>{/if}
          {#if model.capabilities.length}<p class="line">{#each model.capabilities as name (name)}<span class="tag">{t(("olib.cap." + name) as MessageKey)}</span>{/each}</p>{/if}
          <ul class="sizes">
            {#each sizes as size (size.name)}
              <li class="line">
                <span class="size">{size.size}</span>
                {#if size.estimated_gb}<span class="muted">{t("olib.about", gb(size.estimated_gb))}</span>{/if}
                {#if size.fit}<span class={"fit " + size.fit.level}>{t(("guide.fit." + size.fit.level) as MessageKey)}</span>{/if}
                {#if size.fit?.level === "tight"}<span class="limit" title={size.fit.text}>{t("olib.limit")}</span>{/if}
                {#if size.installed}
                  <span class="tag">{t("variants.installed")}</span>
                {:else if asking === size.name}
                  <span>{t("variants.confirm", size.name, size.estimated_gb ? gb(size.estimated_gb) : "?")}</span>
                  <button type="button" class="button primary" disabled={busy} onclick={() => download(size)}>{t("models.download")}</button>
                  <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
                {:else}
                  <button type="button" class="button" disabled={busy} onclick={() => (asking = size.name)}>{t("olib.get", size.name)}</button>
                {/if}
              </li>
            {/each}
          </ul>
        </li>
      {/each}
    </ul>
    {#if more}<div class="actions"><button type="button" class="button" disabled={loading} onclick={() => search(page + 1)}>{t("olib.more")}</button></div>{/if}
  {/if}
</section>

<style>
  .ollama-library {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
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

  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-3);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .cards,
  .sizes {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    overflow-wrap: anywhere;
  }

  .line,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .size {
    font-weight: 600;
    min-width: 3rem;
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

  .boxes {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    align-self: center;
  }

  .limit {
    font-size: var(--text-xs);
    color: var(--color-text-muted);
    font-style: italic;
  }

  .fit.tight,
  .fit.too_big {
    background: var(--color-warning-soft);
    color: var(--color-text);
  }
</style>
