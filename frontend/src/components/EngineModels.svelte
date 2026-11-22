<script lang="ts">
  // The models of the engine in use, the same page for every engine (ADR 0020, stage 3), in three parts: « recommended » (what this machine runs well,
  // at most five), « search » (the source of the engine: the catalogue of Lutin then ollama.com or Hugging Face, or the catalogue of the server Lutin
  // manages) and « installed » (use, in memory or not, delete after a second click). Every model is drawn by ModelCard and either has a Download
  // button, which waits for a second click that says its size, or says why it cannot be downloaded. The routes are `/engines/{id}/models*`. What
  // only Ollama and llama.cpp have (the guide, the proposals, the form by name) is around this component on the Models screen; the catalogue of
  // Lutin, grouped by family, is given as `children` and shown in the search until words are searched.
  import { untrack, type Snippet } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { bestVariant, canDownload, checkPath, downloadBody, downloadLabel, downloadPath, entryKey, installedPath, libraryQuery, recommendedPath, removePath, searchPath, sizesShown, variantsPath, type Entry } from "../lib/library";
  import { language, t, type MessageKey } from "../lib/messages";
  import { byUse } from "../lib/model_card";
  import MachineSummary from "./MachineSummary.svelte";
  import ModelCard from "./ModelCard.svelte";
  import ModelHelp from "./ModelHelp.svelte";
  import ModelVariants from "./ModelVariants.svelte";

  type Part = "recommended" | "search" | "installed";
  let {
    engine,
    engineName,
    part,
    canConfigure,
    installedKey = "",
    onchanged,
    onstarted,
    children,
  }: {
    engine: string;
    engineName: string;
    part: Part;
    canConfigure: boolean;
    installedKey?: string; // changes when the Models screen sees another list of models (a download ended): the installed part is read again
    onchanged: () => void;
    onstarted: () => void;
    children?: Snippet;
  } = $props();

  const MANAGED: readonly string[] = ["exllamav3", "lmstudio", "colibri"];
  const managed = $derived(MANAGED.includes(engine));
  const external = $derived(engine === "openai"); // a server reached by its address: its models are its own
  const lang = language();
  const gb = (value: number | null): string => (value === null ? "?" : new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value));

  let installed = $state<Entry[] | null>(null);
  const installedByUse = $derived(installed ? byUse(installed, (entry) => entry.name) : []);
  let loaded = $state(""); // the model in the memory of this machine now, when the engine can say it
  let recommended = $state<Entry[] | null>(null); // null while it is looked for
  let recommendedProblem = $state("");
  let detecting = $state(false); // the machine is being measured: the recommendations come a few seconds later
  let detectTries = 0;
  let found = $state<Entry[] | null>(null); // null until a search is asked
  let more = $state(false);
  let page = $state(1);
  let words = $state("");
  let order = $state<"recent" | "popular">("recent");
  let community = $state(false);
  let capability = $state("");
  let uncensored = $state(false);
  let fitsHere = $state(true);
  let variants = $state<Record<string, Entry[]>>({});
  let proposals = $state<Entry[] | null>(null);
  let updates = $state<Entry[] | null>(null);
  let precisions = $state(""); // Ollama: the installed model whose other precisions are open
  let other = $state({ repo: "", revision: "" });
  let asking = $state(""); // the download or the deletion waiting for its second click
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const shown = $derived(found ? sizesShown(found, fitsHere) : []);
  const hidden = $derived((found?.length ?? 0) - shown.length);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "offline") return t("emodels.offline");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function loadInstalled(): Promise<void> {
    try {
      installed = (await api<{ models: Entry[] }>("GET", installedPath(engine))).models;
    } catch (cause) {
      problem = explain(cause);
      return;
    }
    api<{ model: string; known: boolean; loaded: boolean }>("GET", "/models/loaded")
      .then((answer) => (loaded = answer.known && answer.loaded ? answer.model : ""))
      .catch(() => (loaded = "")); // an engine that cannot say: nothing is shown rather than a « not loaded » that may be wrong
  }

  /** The models this machine runs well: read apart, it can take a few seconds (the exact sizes are asked to the catalogue). */
  async function loadRecommended(): Promise<void> {
    recommendedProblem = "";
    try {
      const answer = await api<{ models: Entry[]; detecting?: boolean }>("GET", recommendedPath(engine));
      detecting = !!answer.detecting && detectTries < 20; // about a minute at most: a machine that cannot be measured then says « nothing fits »
      recommended = detecting ? null : answer.models;
      if (detecting) {
        detectTries += 1;
        setTimeout(() => {
          if (part === "recommended") void loadRecommended();
        }, 3000);
      }
    } catch (cause) {
      recommended = [];
      recommendedProblem = explain(cause);
    }
  }

  $effect(() => {
    void installedKey; // read again when the Models screen sees another list of models
    if (part === "installed") void loadInstalled();
  });

  $effect(() => {
    if (part === "recommended" && !external) void loadRecommended();
  });

  // The search shows what the source offers as soon as it opens, for every engine (the catalogue of Lutin then ollama.com, Hugging Face, the catalogue of
  // the server), instead of an empty page until words are typed.
  $effect(() => {
    if (part === "search" && !external && found === null) untrack(() => void search()); // what is typed meanwhile does not start it again
  });

  // A search is not one of the actions that wait for each other: the one the page starts when it opens must not swallow the one the person asks for.
  // A new search replaces the one running; the answer of a search that was replaced is dropped.
  let searchSeq = 0;
  let searching = $state(false);
  async function search(next = 1): Promise<void> {
    const seq = ++searchSeq;
    searching = true;
    problem = "";
    try {
      const ordered = engine === "ollama" || (managed && engine !== "colibri");
      const path = searchPath(engine, {
        words: engine === "ollama" ? libraryQuery(words, uncensored) : words,
        page: next,
        order: ordered ? order : undefined,
        community: managed && community,
        capability: engine === "ollama" ? capability : "",
      });
      const answer = await api<{ models: Entry[]; more: boolean }>("GET", path);
      if (seq !== searchSeq) return;
      found = next === 1 ? answer.models : [...(found ?? []), ...answer.models];
      more = answer.more;
      page = next;
    } catch (cause) {
      if (seq === searchSeq) problem = explain(cause);
    } finally {
      if (seq === searchSeq) searching = false;
    }
  }

  const showVariants = (entry: Entry): Promise<void> =>
    act(async () => {
      variants = { ...variants, [entryKey(entry)]: (await api<{ variants: Entry[] }>("GET", variantsPath(engine, entry.id))).variants };
    });

  const check = (scope: "updates" | "new"): Promise<void> =>
    act(async () => {
      notice = t("upkeep.checking");
      const answer = await api<{ models: Entry[]; errors: string[] }>("POST", checkPath(engine), { scope });
      if (scope === "updates") {
        updates = answer.models;
        notice = updates.length ? t("upkeep.found", updates.length) : t("upkeep.all_current");
      } else {
        proposals = answer.models;
        notice = proposals.length ? t("upkeep.found", proposals.length) : t("upkeep.nothing_better");
      }
      if (answer.errors.length) problem = answer.errors.join(" ");
    });

  const download = (ref: string, revision: string): Promise<void> =>
    act(async () => {
      await api("POST", downloadPath(engine), downloadBody(ref, revision, true));
      asking = "";
      notice = t("emodels.started", downloadLabel(ref, revision));
      onstarted();
    });

  const use = (entry: Entry): Promise<void> =>
    act(async () => {
      await api("PATCH", "/settings", { model: entry.name });
      await loadInstalled();
      onchanged();
    });

  const remove = (entry: Entry): Promise<void> =>
    act(async () => {
      await api("DELETE", removePath(engine, entry.name));
      asking = "";
      await loadInstalled();
      onchanged();
    });

  const variantsLabel = (): string => t(engine === "ollama" ? "variants.open" : engine === "llamacpp" ? "emodels.files" : "emodels.quants");
  // An Ollama tag can be taken as it is, with its default precision; a repository of Hugging Face needs one of its files or quantisations first.
  const direct = (entry: Entry): boolean => !entry.has_variants || engine === "ollama";
</script>

{#snippet offer(key: string, entry: Entry)}
  {#if !canDownload(entry)}
    <span class="reason">{entry.download.reason}</span>
  {:else if asking === key}
    <span class="line" role="group" aria-label={downloadLabel(entry.id, entry.revision)}>
      <span>{t("variants.confirm", downloadLabel(entry.id, entry.revision), gb(entry.size_gb))}</span>
      <button type="button" class="button primary" disabled={busy} onclick={() => download(entry.id, entry.revision)}>{t("models.download")}</button>
      <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
    </span>
  {:else if canConfigure}
    <button type="button" class="button" disabled={busy} onclick={() => (asking = key)}>{t("models.download")}<span class="visually-hidden"> {downloadLabel(entry.id, entry.revision)}</span></button>
  {/if}
{/snippet}

{#snippet precisionsOf(entry: Entry, prefix: string, primary: boolean)}
  {@const list = variants[entryKey(entry)]}
  {#if list}
    {@const advised = bestVariant(list)}
    {#if list.length === 0}<p class="muted">{t("emodels.no_variants")}</p>{:else}<p class="muted">{t("emodels.choose_precision")}</p>{/if}
    <ul class="precisions" aria-label={t("emodels.variants_of", entry.name)}>
      {#each advised ? [advised, ...list.filter((variant) => variant !== advised)] : list as variant (entryKey(variant))}
        <li class="line" class:advised={variant === advised}>
          <span class="size">{variant.revision || variant.name}</span><span class="muted">{t("upkeep.size", gb(variant.size_gb))}</span>
          {#if variant === advised}<span class="tag advice">{t("emodels.advised")}</span>{/if}
          {#if variant.fit}<span class={"fit " + variant.fit.level} title={variant.fit.text}>{t(("guide.fit." + variant.fit.level) as MessageKey)}</span>{/if}
          {#if variant.installed}<span class="tag">{t("variants.installed")}</span>{:else}{@render offer(prefix + entryKey(variant), variant)}{/if}
        </li>
      {/each}
    </ul>
  {:else if primary}
    <!-- A repository of Hugging Face (ExLlamaV3, LM Studio, llama.cpp) is downloaded in one of its precisions: the same « Download » as everywhere, which first
         shows them, the advised one at the top (maintainer, 2026-11-22: « pas de bouton pour les télécharger, je fais comment ? »). -->
    {#if canConfigure}<button type="button" class="button primary" disabled={busy} onclick={() => showVariants(entry)}>{t("emodels.download_choose")}<span class="visually-hidden"> {entry.name}</span></button>{/if}
  {:else}
    <button type="button" class="button quiet" disabled={busy} onclick={() => showVariants(entry)}>{variantsLabel()}<span class="visually-hidden"> {entry.name}</span></button>
  {/if}
{/snippet}

{#snippet offered(entry: Entry, prefix: string)}
  <ModelCard name={entry.name} reference={entry.id} revision={entry.revision} sizeGb={entry.size_gb} approximate={entry.approximate} fit={entry.fit} installed={entry.installed}
    inUse={entry.in_use} {engine} summary={entry.summary} strengths={entry.strengths ?? []}>
    {#snippet actions()}
      {#if !entry.installed && direct(entry)}{@render offer(prefix + entryKey(entry), entry)}{/if}
      {#if entry.has_variants && !entry.installed && !direct(entry) && !canDownload(entry)}<span class="reason">{entry.download.reason}</span>
      {:else if entry.has_variants}{@render precisionsOf(entry, prefix + entryKey(entry) + ">", !direct(entry) && !entry.installed)}{/if}
    {/snippet}
  </ModelCard>
{/snippet}

<section class="engine-models" data-part={part} data-engine={engine} aria-labelledby="engine-models-title">
  {#if part === "recommended"}
    <h2 id="engine-models-title">{t("emodels.recommended")}</h2>
    {#if external}
      <p class="muted">{t("models.cat.unmanaged")}</p>
    {:else}
      <p class="muted">{t("emodels.recommended_help")}</p>
      <MachineSummary onchanged={() => void loadRecommended()} />
      {#if detecting}
        <p class="muted" role="status">{t("emodels.detecting")}</p>
      {:else if recommended === null}
        <p class="muted" role="status">{t("emodels.recommended_loading")}</p>
      {:else if recommendedProblem}
        <p class="problem" role="alert">{recommendedProblem}</p>
      {:else if recommended.length === 0}
        <p class="muted">{t("emodels.recommended_none")}</p>
      {:else}
        <ul class="cards">
          {#each recommended as entry (entryKey(entry))}{@render offered(entry, "recommended:")}{/each}
        </ul>
      {/if}
      {#if managed}
        <div class="line"><button type="button" class="button" disabled={busy} onclick={() => check("new")}>{t("upkeep.check_new")}</button></div>
        {#if proposals?.length}
          <ul class="cards">
            {#each proposals as entry (entryKey(entry))}{@render offered(entry, "new:")}{/each}
          </ul>
        {/if}
      {/if}
    {/if}
  {:else if part === "search"}
    <h2 id="engine-models-title">{t("emodels.title", engineName)}</h2>
    {#if external}
      <p class="muted">{t("models.cat.unmanaged")}</p>
    {:else}
      <p class="muted">{t(("emodels.intro." + engine) as MessageKey)}</p>
      <ModelHelp {engine} />
      <form class="line search" onsubmit={(event) => (event.preventDefault(), void search())}>
        <label class="field">{t("emodels.words")}<input id="engine-models-words" type="search" autocomplete="off" spellcheck="false" bind:value={words} /></label>
        {#if engine === "ollama" || (managed && engine !== "colibri")}
          <label class="field">{t("emodels.order")}<select bind:value={order}><option value="recent">{t("emodels.newest")}</option><option value="popular">{t("emodels.popular")}</option></select></label>
        {/if}
        {#if engine === "ollama"}
          <label class="field">{t("emodels.capability")}
            <select bind:value={capability}>
              <option value="">{t("emodels.any")}</option>
              <option value="tools">{t("emodels.cap.tools")}</option>
              <option value="vision">{t("emodels.cap.vision")}</option>
              <option value="thinking">{t("emodels.cap.thinking")}</option>
            </select>
          </label>
          <label><input type="checkbox" bind:checked={uncensored} /> {t("emodels.uncensored")}</label>
        {/if}
        {#if managed && engine !== "colibri"}<label><input type="checkbox" bind:checked={community} /> {t("emodels.community")}</label>{/if}
        <button type="submit" class="button">{t("emodels.search")}</button>
      </form>
      {#if searching}<p class="muted" role="status">{t("emodels.searching")}</p>{/if}
      {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
      <p class="notice" role="status">{notice}</p>
      {#if found}
        <div class="line">
          <label><input type="checkbox" bind:checked={fitsHere} /> {t("emodels.fits_here")}</label>
          {#if hidden > 0}<span class="muted">{t("emodels.hidden", hidden)}</span>{/if}
        </div>
        {#if found.length === 0}<p class="muted">{t("emodels.none")}</p>{/if}
        {@const groups = byUse(shown, (entry) => entry.name)}
        <div class="results" aria-label={t("emodels.results")} role="region">
          {#each groups as group (group.use)}
            {#if groups.length > 1}<h3 class="use-title">{t(("card.use." + group.use) as MessageKey)}</h3>{/if}
            <ul class="cards">
              {#each group.names as entry (entryKey(entry))}{@render offered(entry, "found:")}{/each}
            </ul>
          {/each}
        </div>
        {#if more}<div class="line"><button type="button" class="button" disabled={searching} onclick={() => search(page + 1)}>{t("emodels.more")}</button></div>{/if}
      {:else}
        {@render children?.()}
      {/if}
      <!-- A model by its name, for every engine that downloads (it was the « add by name » form of Ollama's Installed tab, and a form of its own for the
           servers Lutin manages): an Ollama tag; a repository and its file for llama.cpp (or an Ollama tag); a repository and its quantisation otherwise. -->
      {#if engine !== "colibri" && canConfigure}
        <h3>{t("emodels.other")}</h3>
        <div class="line">
          {#if engine === "ollama"}
            <label class="field">{t("models.add_expert")}<input type="text" placeholder="qwen3:8b" autocomplete="off" spellcheck="false" bind:value={other.repo} /></label>
          {:else}
            <label class="field">{t("emodels.repo")}<input type="text" autocomplete="off" spellcheck="false" bind:value={other.repo}
              placeholder={engine === "lmstudio" ? "lmstudio-community/Qwen3-8B-GGUF" : engine === "llamacpp" ? "bartowski/Qwen3-8B-GGUF" : "turboderp/Qwen3-8B-exl3"} /></label>
            <label class="field">{t(engine === "llamacpp" ? "emodels.file" : "emodels.revision")}<input type="text" autocomplete="off" spellcheck="false" bind:value={other.revision}
              placeholder={engine === "lmstudio" ? "Q4_K_M" : engine === "llamacpp" ? "Qwen3-8B-Q4_K_M.gguf" : "4.0bpw"} /></label>
          {/if}
          {#if other.repo.trim()}
            {@render offer("other", { id: other.repo.trim(), name: other.repo.trim(), revision: engine === "ollama" ? "" : other.revision.trim(), size_gb: null, approximate: false, fit: null,
                                      installed: false, in_use: false, summary: "", download: { possible: true, reason: "" }, has_variants: false, incomplete: false, removable: false })}
          {/if}
        </div>
        <p class="muted">{t("emodels.other_help." + (engine === "ollama" ? "ollama" : engine === "llamacpp" ? "llamacpp" : "repo") as MessageKey)}</p>
      {/if}
    {/if}
  {:else}
    <h2 id="engine-models-title">{t("emodels.installed_title", engineName)}</h2>
    {#if part === "installed" && problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>
    {#if installed && installed.length === 0}<p class="muted">{t("models.none")} {t("emodels.find_more")}</p>{/if}
    {#if installed?.length}
      <!-- By use (maintainer, 2026-11-22: « tri des modèles par usage »), conversation first; one heading per use when there is more than one. -->
      {#snippet installedCard(entry: Entry)}
          <ModelCard name={entry.name} reference={entry.id} revision={entry.revision} sizeGb={entry.size_gb} fit={entry.fit} installed inUse={entry.in_use} incomplete={entry.incomplete} {engine}>
            {#snippet actions()}
              {#if !entry.in_use && engine !== "colibri"}<button type="button" class="button primary" disabled={busy} onclick={() => use(entry)}>{t("models.use")}</button>{/if}
              {#if loaded && loaded === entry.name}<span class="tag">{t("emodels.loaded")}</span>{/if}
              {#if engine === "ollama" && /^[\w.\-/]+:[\w.]+$/.test(entry.name)}
                <button type="button" class="button quiet" aria-expanded={precisions === entry.name} onclick={() => (precisions = precisions === entry.name ? "" : entry.name)}>{t("variants.open")}<span class="visually-hidden"> {entry.name}</span></button>
              {/if}
              {#if entry.removable && canConfigure}
                {#if asking === "delete:" + entry.name}
                  <span>{t("upkeep.delete_confirm", entry.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(entry)}>{t("upkeep.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
                {:else}
                  <button type="button" class="button quiet danger" disabled={busy} onclick={() => (asking = "delete:" + entry.name)}>{t("models.delete")}<span class="visually-hidden"> {entry.name}</span></button>
                {/if}
              {/if}
              {#if precisions === entry.name}<div class="variants"><ModelVariants model={entry.name} {onstarted} /></div>{/if}
            {/snippet}
          </ModelCard>
      {/snippet}
      {#each installedByUse as group (group.use)}
        {#if installedByUse.length > 1}<h3 class="use-title">{t(("card.use." + group.use) as MessageKey)}</h3>{/if}
        <ul class="cards">
          {#each group.names as entry (entryKey(entry))}{@render installedCard(entry)}{/each}
        </ul>
      {/each}
    {/if}
    {#if engine === "exllamav3"}
      <div class="line"><button type="button" class="button" disabled={busy} onclick={() => check("updates")}>{t("upkeep.check_updates")}</button></div>
      {#if updates?.length}
        <ul class="cards">
          {#each updates as entry (entryKey(entry))}{@render offered(entry, "update:")}{/each}
        </ul>
      {/if}
    {/if}
  {/if}
  {#if part !== "search" && part !== "installed"}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>
  {/if}
</section>

<style>
  .engine-models {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
  }

  .use-title {
    margin-top: var(--space-2);
    font-size: var(--text-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-text-muted);
  }

  h3 {
    font-size: var(--text-md, 1rem);
  }

  .muted,
  .reason {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
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

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .search {
    align-items: end; /* the fields under their labels, the button and the boxes on the line of the fields */
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 28rem), 1fr));
    align-items: start;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .precisions {
    display: flex;
    flex-direction: column;
    flex-basis: 100%;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .precisions li {
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-md);
  }

  .precisions li.advised {
    background: var(--color-accent-soft); /* the advised precision, at the top: the one to take when unsure */
  }

  .tag.advice {
    background: var(--color-accent);
    color: var(--color-on-accent);
  }

  .results {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .variants {
    flex-basis: 100%;
  }

  .size {
    font-weight: 600;
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
