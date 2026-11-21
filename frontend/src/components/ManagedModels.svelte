<script lang="ts">
  // The models of the server Lutin manages behind its OpenAI-compatible engine, when it is ExLlamaV3, LM Studio or Colibri (docs/modernization/
  // PARITY.md, item 10): what is on disk (use, delete after a second click), a check for newer versions (ExLlamaV3) or new models that fit here, the
  // catalogue to explore and the quantisations of a repository, each judged for this machine. A download waits for a second click that says its size.
  // Nothing is shown when none of the three is the server in use. Every model is drawn by the same card (ModelCard), whatever list it is in; the
  // Catalogue tab shows what can be downloaded (`mode` « catalog »), the Installed tab only what is on this machine (« installed »).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";
  import ModelCard from "./ModelCard.svelte";
  import ModelHelp from "./ModelHelp.svelte";

  type Fit = { level: string; text: string } | null;
  type DiskModel = { name: string; fit: Fit; size_gb: number | null; repo: string | null; revision: string | null; path: string | null; incomplete: boolean; in_use: boolean; deletable: boolean };
  type View = { server: string; name: string; installed: boolean; running: boolean; status: string; folder: string; can_check_updates: boolean; models: DiskModel[] };
  type Entry = { id: string; name: string; author: string; downloads: number; estimated_gb: number | null; fit: Fit; on_disk: string[]; direct: boolean };
  type Quant = { revision: string; size_gb: number | null; fit: Fit; on_disk: boolean };
  type Recommended = { id: string; name: string; revision: string; size_gb: number | null; fit: Fit; on_disk: boolean };

  let { canConfigure, onchanged, onabsent, mode = "catalog" }: { canConfigure: boolean; onchanged: () => void; onabsent?: () => void; mode?: "catalog" | "installed" } = $props();

  const KINDS = ["exllamav3", "lmstudio", "colibri"] as const;
  const lang = language();
  let kind = $state("");
  let view = $state<View | null>(null);
  let entries = $state<Entry[] | null>(null);
  let more = $state(false);
  let page = $state(1);
  let words = $state("");
  let order = $state<"recent" | "popular">("recent");
  let community = $state(false);
  let quants = $state<Record<string, Quant[]>>({});
  let proposals = $state<Entry[] | null>(null);
  let recommended = $state<Recommended[] | null>(null); // null while it is looked for, [] when nothing fits or the catalogue cannot be read
  let recommendedProblem = $state("");
  let updates = $state<{ name: string; repo: string; revision: string | null }[] | null>(null);
  let other = $state({ repo: "", revision: "" });
  let asking = $state(""); // the download or the deletion waiting for its second click
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const base = $derived("/managed-servers/" + kind);
  const gb = (value: number | null): string => (value === null ? "?" : new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "offline") return t("library.offline");
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

  const reload = async (): Promise<void> => void (view = await api<View>("GET", base + "/models"));

  const explore = (next = 1): Promise<void> =>
    act(async () => {
      const query = new URLSearchParams({ q: words.trim(), order, page: String(next) });
      if (community) query.set("community", "1");
      const answer = await api<{ models: Entry[]; more: boolean }>("GET", base + "/catalog?" + query.toString());
      entries = next === 1 ? answer.models : [...(entries ?? []), ...answer.models];
      more = answer.more;
      page = next;
    });

  const showQuants = (entry: Entry): Promise<void> =>
    act(async () => {
      quants = { ...quants, [entry.id]: (await api<{ quantizations: Quant[] }>("GET", base + "/quantizations?repo=" + encodeURIComponent(entry.id))).quantizations };
    });

  const check = (scope: "updates" | "new"): Promise<void> =>
    act(async () => {
      notice = t("upkeep.checking");
      const answer = await api<{ updates?: typeof updates; proposals?: Entry[] }>("POST", base + "/check", { scope });
      if (scope === "updates") {
        updates = answer.updates ?? [];
        notice = updates.length ? t("upkeep.found", updates.length) : t("upkeep.all_current");
      } else {
        proposals = answer.proposals ?? [];
        notice = proposals.length ? t("upkeep.found", proposals.length) : t("upkeep.nothing_better");
      }
    });

  const download = (repo: string, revision: string): Promise<void> =>
    act(async () => {
      await api("POST", base + "/downloads", { repo, revision, confirm: true });
      asking = "";
      notice = t("managed.started", repo + (revision ? " @ " + revision : ""));
      onchanged();
    });

  const use = (model: DiskModel): Promise<void> =>
    act(async () => {
      await api("PATCH", "/settings", { model: model.name });
      await reload();
      onchanged();
    });

  const remove = (model: DiskModel): Promise<void> =>
    act(async () => {
      await api("DELETE", "/models/" + encodeURIComponent(model.name));
      asking = "";
      await reload();
      onchanged();
    });

  /** The models this machine runs well, with the quantisation to take: read apart from the rest, it asks the catalogue for exact sizes and can take a few seconds. */
  async function loadRecommended(): Promise<void> {
    recommendedProblem = "";
    try {
      recommended = (await api<{ models: Recommended[] }>("GET", base + "/recommended")).models;
    } catch (cause) {
      recommended = [];
      recommendedProblem = explain(cause);
    }
  }

  onMount(() => {
    void (async () => {
      for (const candidate of KINDS) {
        try {
          view = await api<View>("GET", "/managed-servers/" + candidate + "/models");
          kind = candidate;
          if (mode === "catalog") void loadRecommended();
          return;
        } catch {
          // not the server in use: the next one
        }
      }
      onabsent?.(); // none of the three is the server in use
    })();
  });
</script>

{#snippet confirmDownload(key: string, repo: string, revision: string, size: number | null)}
  {#if asking === key}
    <span class="line" role="group" aria-label={repo}>
      <span>{t("variants.confirm", repo + (revision ? " @ " + revision : ""), gb(size))}</span>
      <button type="button" class="button primary" disabled={busy} onclick={() => download(repo, revision)}>{t("models.download")}</button>
      <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
    </span>
  {:else if canConfigure}
    <button type="button" class="button" disabled={busy} onclick={() => (asking = key)}>{t("models.download")}<span class="visually-hidden"> {repo} {revision}</span></button>
  {/if}
{/snippet}

{#snippet precisions(entry: Entry)}
  {#if quants[entry.id]}
    <ul class="quants" aria-label={t("managed.quants")}>
      {#each quants[entry.id] as quant (quant.revision)}
        <li class="line"><span class="size">{quant.revision}</span><span class="muted">{t("upkeep.size", gb(quant.size_gb))}</span>
          {#if quant.fit}<span class={"fit " + quant.fit.level} title={quant.fit.text}>{t(("guide.fit." + quant.fit.level) as MessageKey)}</span>{/if}
          {#if quant.on_disk}<span class="tag">{t("variants.installed")}</span>{:else}{@render confirmDownload(entry.id + "@" + quant.revision, entry.id, quant.revision, quant.size_gb)}{/if}</li>
      {/each}
    </ul>
  {:else}
    <button type="button" class="button" disabled={busy} onclick={() => showQuants(entry)}>{t("managed.quants")}<span class="visually-hidden"> {entry.name}</span></button>
  {/if}
{/snippet}

{#snippet entryCard(entry: Entry, key: string)}
  <ModelCard name={entry.name} reference={entry.id} sizeGb={entry.estimated_gb} approximate fit={entry.fit} installed={entry.on_disk.length > 0} engine={kind}>
    {#snippet actions()}
      {#if entry.direct}
        {#if !entry.on_disk.length}{@render confirmDownload(key + entry.id, entry.id, "", entry.estimated_gb)}{/if}
      {:else}
        {@render precisions(entry)}
      {/if}
    {/snippet}
  </ModelCard>
{/snippet}

{#if view}
  <section class="managed" aria-labelledby="managed-title">
    <h2 id="managed-title">{mode === "installed" ? t("managed.installed_title", view.name) : t("managed.title", view.name)}</h2>
    <p class="muted">{t(("managed.intro." + view.server) as MessageKey)}</p>
    <p>{view.installed ? (view.running ? t("managed.running", view.name) : t("managed.stopped", view.name)) : t("managed.absent", view.name)}{view.status ? " · " + view.status : ""}</p>
    {#if view.folder}<p class="muted">{t("managed.folder", view.folder)}</p>{/if}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>

    {#if mode === "installed"}
      {#if view.models.length === 0}<p class="muted">{t("models.none")} {t("managed.find_more")}</p>{/if}
      <ul class="cards">
        {#each view.models as model (model.name)}
          <ModelCard name={model.name} reference={model.repo ?? model.name} revision={model.revision ?? ""} sizeGb={model.size_gb} fit={model.fit} installed inUse={model.in_use} incomplete={model.incomplete} engine={kind}>
            {#snippet actions()}
              {#if !model.in_use && view?.server !== "colibri"}<button type="button" class="button primary" disabled={busy} onclick={() => use(model)}>{t("models.use")}</button>{/if}
              {#if model.deletable && canConfigure}
                {#if asking === "delete:" + model.name}
                  <span>{t("upkeep.delete_confirm", model.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(model)}>{t("upkeep.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
                {:else}
                  <button type="button" class="button quiet danger" disabled={busy} onclick={() => (asking = "delete:" + model.name)}>{t("models.delete")}<span class="visually-hidden"> {model.name}</span></button>
                {/if}
              {/if}
            {/snippet}
          </ModelCard>
        {/each}
      </ul>
      {#if view.can_check_updates}
        <div class="line"><button type="button" class="button" disabled={busy} onclick={() => check("updates")}>{t("upkeep.check_updates")}</button></div>
        {#if updates?.length}
          <ul class="cards">
            {#each updates as update (update.repo + update.revision)}
              <ModelCard name={t("upkeep.update_of", update.name)} reference={update.repo} revision={update.revision ?? ""} engine={kind}>
                {#snippet actions()}{@render confirmDownload("update:" + update.repo, update.repo, update.revision ?? "", null)}{/snippet}
              </ModelCard>
            {/each}
          </ul>
        {/if}
      {/if}
    {:else}
      <ModelHelp engine={kind} />

      <h3>{t("managed.recommended")}</h3>
      <p class="muted">{t("managed.recommended_help")}</p>
      {#if recommended === null}
        <p class="muted" role="status">{t("managed.recommended_loading")}</p>
      {:else if recommendedProblem}
        <p class="problem" role="alert">{recommendedProblem}</p>
      {:else if recommended.length === 0}
        <p class="muted">{t("managed.recommended_none")}</p>
      {:else}
        <ul class="cards">
          {#each recommended as entry (entry.id)}
            <ModelCard name={entry.name} reference={entry.id} revision={entry.revision} sizeGb={entry.size_gb} fit={entry.fit} installed={entry.on_disk} engine={kind}>
              {#snippet actions()}
                {#if !entry.on_disk}{@render confirmDownload("recommended:" + entry.id, entry.id, entry.revision, entry.size_gb)}{/if}
              {/snippet}
            </ModelCard>
          {/each}
        </ul>
      {/if}

      <div class="line">
        <button type="button" class="button" disabled={busy} onclick={() => check("new")}>{t("upkeep.check_new")}</button>
      </div>
      {#if proposals?.length}
        <ul class="cards">
          {#each proposals as entry (entry.id)}{@render entryCard(entry, "new:")}{/each}
        </ul>
      {/if}

      <h3>{t("managed.explore")}</h3>
      <form class="line" onsubmit={(event) => (event.preventDefault(), void explore())}>
        <label class="field">{t("olib.words")}<input type="search" bind:value={words} /></label>
        {#if view.server !== "colibri"}
          <label class="field">{t("olib.order")}<select bind:value={order}><option value="recent">{t("olib.newest")}</option><option value="popular">{t("olib.popular")}</option></select></label>
          <label><input type="checkbox" bind:checked={community} /> {t("managed.community")}</label>
        {/if}
        <button type="submit" class="button" disabled={busy}>{t("olib.search")}</button>
      </form>
      {#if entries}
        {#if entries.length === 0}<p class="muted">{t("olib.none")}</p>{/if}
        <ul class="cards">
          {#each entries as entry (entry.id)}{@render entryCard(entry, "entry:")}{/each}
        </ul>
        {#if more}<div class="line"><button type="button" class="button" disabled={busy} onclick={() => explore(page + 1)}>{t("olib.more")}</button></div>{/if}
      {/if}

      {#if view.server !== "colibri" && canConfigure}
        <h3>{t("managed.other")}</h3>
        <div class="line">
          <label class="field">{t("managed.repo")}<input type="text" placeholder={view.server === "lmstudio" ? "lmstudio-community/Qwen3-8B-GGUF" : "turboderp/Qwen3-8B-exl3"} bind:value={other.repo} /></label>
          <label class="field">{t("managed.revision")}<input type="text" placeholder={view.server === "lmstudio" ? "Q4_K_M" : "4.0bpw"} bind:value={other.revision} /></label>
          {#if other.repo.trim()}{@render confirmDownload("other", other.repo.trim(), other.revision.trim(), null)}{/if}
        </div>
      {/if}
    {/if}
  </section>
{/if}

<style>
  .managed {
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

  h3 {
    font-size: var(--text-md, 1rem);
  }

  .muted {
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

  .cards,
  .quants {
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
