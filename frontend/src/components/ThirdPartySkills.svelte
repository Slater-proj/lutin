<script lang="ts">
  // Skills published on GitHub: find them, look inside, copy one into a project, update it, remove it. A skill is text the model follows, so the page shows what the server found in it
  // (hidden orders, downloads, scripts) before anything is copied, asks for each risk to be accepted on its own, and asks once more before copying. Nothing is ever run.
  // Everything that reads GitHub is for the machine itself; in strict offline mode the page says so and does not try.
  import { onDestroy, onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t } from "../lib/messages";
  import { canInstall, indexingProgress, installBody, lacksLicense, searchPath, type Indexing, type SkillCard } from "../lib/thirdskills";

  type Source = { repo: string; name: string; default: boolean };
  type Page = { sources: Source[]; github: { configured: boolean; source: string }; projects: { id: string; name: string }[]; current: string; indexing: Record<string, Indexing>; offline: boolean };
  type Hit = { repo: string; dir: string; name: string; files: number; bytes: number; scripts: boolean; description: string; license: string; tokens: number };
  type Found = { skills: Hit[]; total: number; page: number; more: boolean };
  type Installed = { project: string; name: string; repo: string; dir: string; installed_at: string; license: string; severity: string; description: string; update?: boolean; gone?: boolean; error?: string };
  type RepoHit = { repo: string; stars?: number; description?: string; citations?: number };

  const lang = language();

  let page = $state<Page | null>(null);
  let installed = $state<Installed[]>([]);
  let checked = $state(false);
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);

  let query = $state("");
  let found = $state<Found | null>(null);
  let repoQuery = $state("");
  let repos = $state<RepoHit[] | null>(null);
  let newSource = $state("");
  let removingSource = $state("");
  let removing = $state("");

  // The card being looked at, and what to do with it: install it, or replace the copy named `updating`.
  let card = $state<SkillCard | null>(null);
  let updating = $state("");
  let project = $state("");
  let acceptDanger = $state(false);
  let acceptNoLicense = $state(false);
  let confirming = $state(false);

  let timer: ReturnType<typeof setInterval> | undefined;
  const progress = $derived(indexingProgress(page?.indexing ?? {}));
  const projectName = (id: string): string => page?.projects.find((entry) => entry.id === id)?.name ?? id;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("tps.only_here");
      if (cause.code === "offline") return t("tps.offline");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      done = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const base = "/third-party-skills";
  const refreshPage = async (): Promise<void> => {
    page = await api<Page>("GET", base);
    if (!project || !page.projects.some((entry) => entry.id === project)) project = page.current || page.projects[0]?.id || "";
  };
  const refreshInstalled = async (): Promise<void> => {
    installed = (await api<{ installed: Installed[] }>("GET", base + "/installed")).installed;
    checked = false;
  };

  const search = (more = false): Promise<void> =>
    act(async () => {
      const next = more && found ? found.page + 1 : 1;
      const answer = await api<Found>("GET", searchPath(query, [], next));
      found = more && found ? { ...answer, skills: [...found.skills, ...answer.skills] } : answer;
    });

  const addSource = (repo: string, event?: SubmitEvent): Promise<void> => {
    event?.preventDefault();
    return act(async () => {
      await api("POST", base + "/sources", { repo });
      newSource = "";
      await refreshPage();
    });
  };

  const removeSource = (source: Source): Promise<void> =>
    act(async () => {
      await api("DELETE", base + "/sources?repo=" + encodeURIComponent(source.repo));
      removingSource = "";
      await refreshPage();
    });

  const findRepos = (listed: boolean): Promise<void> =>
    act(async () => {
      repos = (await api<{ repos: RepoHit[] }>("GET", base + "/repos?" + (listed ? "listed=1&" : "") + "q=" + encodeURIComponent(repoQuery.trim()))).repos;
    });

  function poll(): void {
    if (timer) return;
    timer = setInterval(() => {
      void api<Page>("GET", base).then((answer) => {
        page = answer;
        if (!indexingProgress(answer.indexing).running) stopPolling();
      }).catch(stopPolling);
    }, 2000);
  }

  function stopPolling(): void {
    if (timer) clearInterval(timer);
    timer = undefined;
  }

  const describeAll = (): Promise<void> =>
    act(async () => {
      for (const source of page?.sources ?? []) await api("POST", base + "/index", { repo: source.repo });
      await refreshPage();
      poll();
    });

  function close(): void {
    card = null;
    updating = "";
    acceptDanger = false;
    acceptNoLicense = false;
    confirming = false;
  }

  const look = (repo: string, dir: string, replacing = ""): Promise<void> =>
    act(async () => {
      close();
      card = await api<SkillCard>("GET", `${base}/card?repo=${encodeURIComponent(repo)}&dir=${encodeURIComponent(dir)}`);
      updating = replacing;
    });

  // The first press only asks; the files are copied on the second, once the page has said what is about to happen.
  const install = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    if (!card) return Promise.resolve();
    if (!confirming) {
      confirming = true;
      return Promise.resolve();
    }
    const shown = card;
    return act(async () => {
      const body = installBody(shown, project, { danger: acceptDanger, noLicense: acceptNoLicense }, true);
      const where = updating ? `${base}/installed/${encodeURIComponent(updating)}/update` : base + "/install";
      if (updating) {
        delete body.repo;
        delete body.dir;
      }
      const answer = await api<{ name: string }>("POST", where, body);
      const replaced = updating !== "";
      close();
      await refreshInstalled();
      done = t(replaced ? "tps.updated" : "tps.installed_done", answer.name, projectName(project));
    });
  };

  const checkUpdates = (): Promise<void> =>
    act(async () => {
      installed = (await api<{ installed: Installed[] }>("GET", base + "/updates")).installed;
      checked = true;
    });

  const remove = (skill: Installed): Promise<void> =>
    act(async () => {
      installed = (await api<{ installed: Installed[] }>("DELETE", `${base}/installed/${encodeURIComponent(skill.name)}?project=${encodeURIComponent(skill.project)}`)).installed;
      removing = "";
    });

  onMount(() => {
    void act(async () => {
      await refreshPage();
      await refreshInstalled();
      if (progress.running) poll();
    });
  });

  onDestroy(stopPolling);
</script>

<section class="tps" aria-labelledby="tps-title">
  <h2 id="tps-title">{t("tps.title")}</h2>
  <p class="muted">{t("tps.intro")}</p>
  {#if page?.offline}<p class="warn" role="status">{t("tps.offline")}</p>{/if}
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}

  {#if page}
    <div class="panel">
      <h3>{t("tps.search")}</h3>
      <form class="row" onsubmit={(event) => { event.preventDefault(); void search(); }}>
        <label for="tps-query">{t("tps.search_label")}</label>
        <input id="tps-query" type="text" bind:value={query} autocomplete="off" spellcheck="false" />
        <button type="submit" class="button primary" disabled={busy || page.offline}>{t("tps.search_go")}</button>
      </form>
      <div class="actions">
        <button type="button" class="button" disabled={busy || page.offline || progress.running} onclick={describeAll}>{t("tps.describe")}</button>
        {#if progress.running}<span class="muted" role="status">{t("tps.describing", progress.done, progress.total)}</span>{/if}
        {#if progress.error}<span class="problem">{progress.error}</span>{/if}
      </div>
      <p class="muted">{t("tps.describe_help")}</p>
      {#if found}
        {#if found.skills.length === 0}
          <p class="empty">{t("tps.no_result")}</p>
        {:else}
          <p class="muted" role="status">{t("tps.results", found.total)}</p>
          <ul class="list" aria-label={t("tps.search")}>
            {#each found.skills as hit (hit.repo + "/" + hit.dir)}
              <li class="item hit">
                <div class="line">
                  <strong>{hit.name}</strong>
                  <span class="muted">{hit.repo}{hit.dir ? "/" + hit.dir : ""}</span>
                  {#if hit.scripts}<span class="badge warning">{t("tps.scripts")}</span>{/if}
                </div>
                {#if hit.description}<p>{hit.description}</p>{/if}
                <p class="muted">{t("tps.files", hit.files)} · {formatBytes(hit.bytes, lang)} · {t("tps.tokens", hit.tokens)}</p>
                <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => look(hit.repo, hit.dir)}>{t("tps.look")}</button></div>
              </li>
            {/each}
          </ul>
          {#if found.more}<div class="actions"><button type="button" class="button" disabled={busy} onclick={() => search(true)}>{t("tps.more")}</button></div>{/if}
        {/if}
      {/if}
    </div>

    {#if card}
      <div class="panel cardpanel" role="region" aria-labelledby="tps-card-title">
        <h3 id="tps-card-title">{updating ? t("tps.card_update", card.name) : t("tps.card_title", card.name)}</h3>
        <p class="muted">{card.repo}{card.dir ? "/" + card.dir : ""}</p>
        {#if card.description}<p>{card.description}</p>{/if}
        <p class="muted">{lacksLicense(card) ? t("tps.no_license") : t("tps.license", card.license || t("tps.license_elsewhere"))} · {t("tps.files", card.file_count)} · {formatBytes(card.bytes, lang)} · {t("tps.tokens", card.tokens)}</p>
        {#if card.heavy}<p class="warn">{t("tps.heavy")}</p>{/if}
        {#if !card.installable}<p class="problem">{t("tps.too_big")}</p>{/if}
        {#if card.findings.length > 0}
          <h4>{t("tps.findings")}</h4>
          <ul class="list findings">
            {#each card.findings as finding, index (index)}
              <li class="finding">
                <span class="badge {finding.severity === 'danger' ? 'bad' : 'warning'}">{finding.severity === "danger" ? t("tps.sev_danger") : t("tps.sev_attention")}</span>
                {finding.explanation} <span class="muted">({finding.file}:{finding.line})</span>
                <code class="excerpt">{finding.excerpt}</code>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">{t("tps.no_findings")}</p>
        {/if}
        <details>
          <summary>{t("tps.files_show")}</summary>
          <ul class="plain">{#each card.files as file (file.path)}<li>{file.path} <span class="muted">{formatBytes(file.bytes, lang)}</span></li>{/each}</ul>
        </details>
        <details>
          <summary>{t("tps.text_show")}</summary>
          <textarea class="text" readonly rows="12" aria-label={t("tps.text_show")} value={card.text}></textarea>
          {#if card.text_truncated}<p class="muted">{t("tps.text_cut")}</p>{/if}
        </details>

        <form class="install" onsubmit={install}>
          {#if !updating && page.projects.length > 0}
            <label for="tps-project">{t("tps.project")}</label>
            <select id="tps-project" bind:value={project} onchange={() => (confirming = false)}>
              {#each page.projects as entry (entry.id)}<option value={entry.id}>{entry.name}</option>{/each}
            </select>
          {/if}
          {#if card.severity === "danger"}
            <label class="check"><input type="checkbox" bind:checked={acceptDanger} onchange={() => (confirming = false)} /> {t("tps.accept_danger")}</label>
          {/if}
          {#if lacksLicense(card)}
            <label class="check"><input type="checkbox" bind:checked={acceptNoLicense} onchange={() => (confirming = false)} /> {t("tps.accept_license")}</label>
          {/if}
          {#if confirming}<p class="warn" role="status">{t("tps.install_confirm", card.file_count, card.name, projectName(project))}</p>{/if}
          <div class="actions">
            <button type="submit" class="button primary" disabled={busy || page.offline || !project || !canInstall(card, { danger: acceptDanger, noLicense: acceptNoLicense })}>
              {confirming ? t("tps.install_yes") : updating ? t("tps.update") : t("tps.install")}
            </button>
            <button type="button" class="button" onclick={close}>{t("chat.cancel")}</button>
          </div>
        </form>
      </div>
    {/if}

    <div class="panel">
      <h3>{t("tps.installed")}</h3>
      {#if installed.length === 0}
        <p class="empty">{t("tps.installed_none")}</p>
      {:else}
        <ul class="list" aria-label={t("tps.installed")}>
          {#each installed as skill (skill.project + "/" + skill.name)}
            <li class="item installed">
              <div class="line">
                <strong>{skill.name}</strong>
                <span class="muted">{skill.repo}{skill.dir ? "/" + skill.dir : ""} · {projectName(skill.project)}</span>
                {#if checked && skill.update}<span class="badge warning">{t("tps.update_available")}</span>{/if}
                {#if checked && skill.gone}<span class="badge bad">{t("tps.gone")}</span>{/if}
                {#if checked && !skill.update && !skill.gone && !skill.error}<span class="badge ok">{t("tps.up_to_date")}</span>{/if}
              </div>
              {#if skill.description}<p class="muted">{skill.description}</p>{/if}
              {#if skill.error}<p class="problem">{skill.error}</p>{/if}
              <div class="actions">
                {#if checked && skill.update}
                  <button type="button" class="button" disabled={busy || page.offline} onclick={() => { project = skill.project; void look(skill.repo, skill.dir, skill.name); }}>{t("tps.update")}</button>
                {/if}
                {#if removing === skill.name + "/" + skill.project}
                  <span class="confirm" role="group" aria-label={t("tps.remove_confirm", skill.name)}>
                    <span>{t("tps.remove_confirm", skill.name)}</span>
                    <button type="button" class="button danger" disabled={busy} onclick={() => remove(skill)}>{t("tps.remove_yes")}</button>
                    <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
                  </span>
                {:else}
                  <button type="button" class="button" disabled={busy} onclick={() => (removing = skill.name + "/" + skill.project)}>{t("tps.remove")}</button>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
        <div class="actions"><button type="button" class="button" disabled={busy || page.offline} onclick={checkUpdates}>{t("tps.check")}</button></div>
      {/if}
    </div>

    <details class="panel">
      <summary><h3 class="inline">{t("tps.sources")}</h3></summary>
      <ul class="list" aria-label={t("tps.sources")}>
        {#each page.sources as source (source.repo)}
          <li class="item source">
            <div class="line"><strong>{source.name}</strong>{#if source.name !== source.repo}<span class="muted">{source.repo}</span>{/if}</div>
            {#if !source.default}
              {#if removingSource === source.repo}
                <span class="confirm" role="group" aria-label={t("tps.source_remove_confirm", source.repo)}>
                  <span>{t("tps.source_remove_confirm", source.repo)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => removeSource(source)}>{t("tps.remove_yes")}</button>
                  <button type="button" class="button" onclick={() => (removingSource = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => (removingSource = source.repo)}>{t("tps.source_remove")}</button></div>
              {/if}
            {/if}
          </li>
        {/each}
      </ul>
      <form class="row" onsubmit={(event) => addSource(newSource, event)}>
        <label for="tps-source">{t("tps.source_add_label")}</label>
        <input id="tps-source" type="text" bind:value={newSource} autocomplete="off" spellcheck="false" placeholder="owner/name" />
        <button type="submit" class="button" disabled={busy || !newSource.trim()}>{t("tps.source_add")}</button>
      </form>
      <h4>{t("tps.find_repos")}</h4>
      <div class="row">
        <label for="tps-repo-query">{t("tps.search_label")}</label>
        <input id="tps-repo-query" type="text" bind:value={repoQuery} autocomplete="off" spellcheck="false" />
        <button type="button" class="button" disabled={busy || page.offline} onclick={() => findRepos(false)}>{t("tps.find_topic")}</button>
        <button type="button" class="button" disabled={busy || page.offline} onclick={() => findRepos(true)}>{t("tps.find_lists")}</button>
      </div>
      {#if repos}
        {#if repos.length === 0}
          <p class="empty">{t("tps.no_result")}</p>
        {:else}
          <ul class="list" aria-label={t("tps.find_repos")}>
            {#each repos as hit (hit.repo)}
              <li class="item source">
                <div class="line">
                  <strong>{hit.repo}</strong>
                  {#if hit.stars !== undefined}<span class="muted">{t("tps.repo_stars", hit.stars)}</span>{/if}
                  {#if hit.citations !== undefined}<span class="muted">{t("tps.repo_citations", hit.citations)}</span>{/if}
                </div>
                {#if hit.description}<p class="muted">{hit.description}</p>{/if}
                <div class="actions">
                  <button type="button" class="button" disabled={busy || page.sources.some((source) => source.repo === hit.repo)} onclick={() => addSource(hit.repo)}>{t("tps.repo_add")}</button>
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      {/if}
    </details>

    <p class="muted">{t("tps.github_moved")} <a href="#/settings/general">{t("tps.github_where")}</a></p>
  {:else if !problem}
    <p class="muted">{t("tps.loading")}</p>
  {/if}
</section>

<style>
  .tps {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  h3,
  h4,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
  }

  h3 {
    font-size: var(--text-md);
  }

  h3.inline {
    display: inline;
  }

  h4 {
    font-size: var(--text-sm);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  summary {
    cursor: pointer;
  }

  .list,
  .plain {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .item {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }

  .line,
  .actions,
  .confirm,
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .install {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .check {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    font-weight: 400;
  }

  .empty {
    padding: var(--space-3);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  select {
    max-width: 24rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .badge.ok {
    color: var(--color-accent-text);
  }

  .badge.bad {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .finding {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .excerpt {
    flex-basis: 100%;
    overflow-wrap: anywhere;
    color: var(--color-text-muted);
  }

  .text {
    box-sizing: border-box;
    width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
    font-size: var(--text-sm);
    resize: vertical;
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .problem,
  .warn {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .done {
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
