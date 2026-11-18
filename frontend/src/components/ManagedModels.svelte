<script lang="ts">
  // The models of the server Lutin manages behind its OpenAI-compatible engine, when it is ExLlamaV3, LM Studio or Colibri (docs/modernization/
  // PARITY.md, item 10): what is on disk (use, delete after a second click), a check for newer versions (ExLlamaV3) or new models that fit here, the
  // catalogue to explore and the quantisations of a repository, each judged for this machine. A download waits for a second click that says its size.
  // Nothing is shown when none of the three is the server in use.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";

  type Fit = { level: string; text: string } | null;
  type DiskModel = { name: string; fit: Fit; size_gb: number | null; repo: string | null; revision: string | null; path: string | null; incomplete: boolean; in_use: boolean; deletable: boolean };
  type View = { server: string; name: string; installed: boolean; running: boolean; status: string; folder: string; can_check_updates: boolean; models: DiskModel[] };
  type Entry = { id: string; name: string; author: string; downloads: number; estimated_gb: number | null; fit: Fit; on_disk: string[]; direct: boolean };
  type Quant = { revision: string; size_gb: number | null; fit: Fit; on_disk: boolean };

  let { canConfigure, onchanged }: { canConfigure: boolean; onchanged: () => void } = $props();

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

  onMount(() => {
    void (async () => {
      for (const candidate of KINDS) {
        try {
          view = await api<View>("GET", "/managed-servers/" + candidate + "/models");
          kind = candidate;
          return;
        } catch {
          // not the server in use: the next one
        }
      }
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

{#snippet fitTag(fit: Fit)}
  {#if fit}<span class={"fit " + fit.level} title={fit.text}>{t(("guide.fit." + fit.level) as MessageKey)}</span>{/if}
{/snippet}

{#if view}
  <section class="managed" aria-labelledby="managed-title">
    <h2 id="managed-title">{t("managed.title", view.name)}</h2>
    <p class="muted">{t(("managed.intro." + view.server) as MessageKey)}</p>
    <p>{view.installed ? (view.running ? t("managed.running", view.name) : t("managed.stopped", view.name)) : t("managed.absent", view.name)}{view.status ? " · " + view.status : ""}</p>
    {#if view.folder}<p class="muted">{t("managed.folder", view.folder)}</p>{/if}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>

    <h3>{t("managed.on_disk")}</h3>
    {#if view.models.length === 0}<p class="muted">{t("models.none")}</p>{/if}
    <ul class="cards">
      {#each view.models as model (model.name)}
        <li class="card">
          <p class="line"><strong>{model.name}</strong>{#if model.in_use}<span class="tag">{t("models.in_use")}</span>{/if}{#if model.size_gb}<span class="muted">{t("upkeep.size", gb(model.size_gb))}</span>{/if}{@render fitTag(model.fit)}</p>
          {#if model.repo}<p class="muted">{model.repo}{model.revision ? " @ " + model.revision : ""}</p>{:else if model.path}<p class="muted">{model.path}</p>{/if}
          {#if model.incomplete}<p class="problem">{t("managed.incomplete")}</p>{/if}
          <div class="line">
            {#if !model.in_use && view.server !== "colibri"}<button type="button" class="button" disabled={busy} onclick={() => use(model)}>{t("models.use")}</button>{/if}
            {#if model.deletable && canConfigure}
              {#if asking === "delete:" + model.name}
                <span>{t("upkeep.delete_confirm", model.name)}</span>
                <button type="button" class="button danger" disabled={busy} onclick={() => remove(model)}>{t("upkeep.delete_yes")}</button>
                <button type="button" class="button" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
              {:else}
                <button type="button" class="button quiet danger" disabled={busy} onclick={() => (asking = "delete:" + model.name)}>{t("models.delete")}<span class="visually-hidden"> {model.name}</span></button>
              {/if}
            {/if}
          </div>
        </li>
      {/each}
    </ul>

    <div class="line">
      {#if view.can_check_updates}<button type="button" class="button" disabled={busy} onclick={() => check("updates")}>{t("upkeep.check_updates")}</button>{/if}
      <button type="button" class="button" disabled={busy} onclick={() => check("new")}>{t("upkeep.check_new")}</button>
    </div>
    {#if updates?.length}
      <ul class="cards">
        {#each updates as update (update.repo + update.revision)}
          <li class="card"><p><strong>{t("upkeep.update_of", update.name)}</strong></p><p class="muted">{update.repo}{update.revision ? " @ " + update.revision : ""}</p>{@render confirmDownload("update:" + update.repo, update.repo, update.revision ?? "", null)}</li>
        {/each}
      </ul>
    {/if}
    {#if proposals?.length}
      <ul class="cards">
        {#each proposals as entry (entry.id)}
          <li class="card"><p class="line"><strong>{entry.name}</strong>{@render fitTag(entry.fit)}<span class="muted">{t("olib.about", gb(entry.estimated_gb))}</span></p>
            {#if entry.direct}{@render confirmDownload("new:" + entry.id, entry.id, "", entry.estimated_gb)}{/if}</li>
        {/each}
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
        {#each entries as entry (entry.id)}
          <li class="card">
            <p class="line"><strong>{entry.name}</strong>{@render fitTag(entry.fit)}{#if entry.estimated_gb}<span class="muted">{t("olib.about", gb(entry.estimated_gb))}</span>{/if}{#if entry.on_disk.length}<span class="tag">{t("variants.installed")}</span>{/if}</p>
            {#if entry.author}<p class="muted">{entry.id}</p>{/if}
            {#if entry.direct}
              {#if !entry.on_disk.length}{@render confirmDownload("entry:" + entry.id, entry.id, "", entry.estimated_gb)}{/if}
            {:else if quants[entry.id]}
              <ul class="quants">
                {#each quants[entry.id] as quant (quant.revision)}
                  <li class="line"><span class="size">{quant.revision}</span><span class="muted">{t("upkeep.size", gb(quant.size_gb))}</span>{@render fitTag(quant.fit)}
                    {#if quant.on_disk}<span class="tag">{t("variants.installed")}</span>{:else}{@render confirmDownload(entry.id + "@" + quant.revision, entry.id, quant.revision, quant.size_gb)}{/if}</li>
                {/each}
              </ul>
            {:else}
              <div class="line"><button type="button" class="button" disabled={busy} onclick={() => showQuants(entry)}>{t("managed.quants")}<span class="visually-hidden"> {entry.name}</span></button></div>
            {/if}
          </li>
        {/each}
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
