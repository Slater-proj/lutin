<script lang="ts">
  // The Projects screen: the working folders, where Lutin reads and writes files for the conversations. One is current; adding or removing one is for the
  // person at this machine (the server refuses it to a paired device and says so). Removing a folder from the list deletes nothing in it.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Project = { id: string; name: string; path: string; usable: boolean; problem: string };
  type Projects = { projects: Project[]; current: string };

  let data = $state<Projects | null>(null);
  let problem = $state("");
  let path = $state("");
  let name = $state("");
  let busy = $state(false);
  let removing = $state("");

  // The folder browser: the sub-folders of one folder, to go down or up, so that nobody has to type a path. Without a path the server gives the starting points.
  type Listing = { path: string; parent: string | null; folders: { name: string; path: string }[]; truncated: boolean };
  let browsing = $state(false);
  let listing = $state<Listing | null>(null);
  let browseProblem = $state("");

  async function look(where: string): Promise<void> {
    try {
      browseProblem = "";
      listing = await api<Listing>("GET", "/projects/folders" + (where ? `?path=${encodeURIComponent(where)}` : ""));
    } catch (cause) {
      browseProblem = explain(cause);
    }
  }

  function toggleBrowser(): void {
    browsing = !browsing;
    if (browsing && !listing) void look(path.trim());
  }

  function useFolder(): void {
    if (!listing?.path) return;
    path = listing.path;
    browsing = false;
  }

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("projects.not_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<Projects | void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      const answer = await action();
      if (answer) data = answer;
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const load = (): Promise<void> => act(() => api<Projects>("GET", "/projects"));

  const select = (project: Project): Promise<void> => act(() => api<Projects>("POST", `/projects/${encodeURIComponent(project.id)}/select`, {}));

  async function add(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!path.trim()) return;
    await act(async () => {
      const answer = await api<Projects>("POST", "/projects", { path: path.trim(), name: name.trim() });
      path = "";
      name = "";
      return answer;
    });
  }

  async function remove(project: Project): Promise<void> {
    await act(async () => {
      const answer = await api<Projects>("DELETE", `/projects/${encodeURIComponent(project.id)}`);
      removing = "";
      return answer;
    });
  }

  onMount(() => {
    void load();
  });
</script>

<div class="projects">
  <header>
    <h1>{t("projects.title")}</h1>
    <p class="muted">{t("projects.intro")}</p>
  </header>

  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if data}
    {#if data.projects.length === 0}
      <p class="empty">{t("projects.none")}</p>
    {:else}
      <ul class="list" aria-label={t("projects.title")}>
        {#each data.projects as project (project.id)}
          <li class="card" class:current={project.id === data.current}>
            <div class="what">
              <p class="line"><strong>{project.name}</strong>{#if project.id === data.current} <span class="badge">{t("projects.current")}</span>{/if}</p>
              <p class="path">{project.path}</p>
              {#if !project.usable}<p class="warn">{project.problem}</p>{/if}
            </div>
            <div class="actions">
              {#if project.id !== data.current}
                <button type="button" class="button primary" disabled={busy || !project.usable} onclick={() => select(project)}>{t("projects.use")}</button>
              {/if}
              {#if removing === project.id}
                <span class="confirm" role="group" aria-label={t("projects.remove_confirm", project.name)}>
                  <span>{t("projects.remove_confirm", project.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(project)}>{t("projects.remove_yes")}</button>
                  <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (removing = project.id)}>{t("projects.remove")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={add}>
      <h2>{t("projects.add_title")}</h2>
      <label for="project-path">{t("projects.path")}</label>
      <input id="project-path" type="text" bind:value={path} autocomplete="off" spellcheck="false" aria-describedby="project-path-help" />
      <p class="muted" id="project-path-help">{t("projects.path_help")}</p>
      <div class="actions"><button type="button" class="button" aria-expanded={browsing} aria-controls="folder-browser" onclick={toggleBrowser}>{browsing ? t("projects.browse_close") : t("projects.browse")}</button></div>
      {#if browsing}
        <div class="browser" id="folder-browser" role="group" aria-label={t("projects.browse")}>
          {#if browseProblem}<p class="problem" role="alert">{browseProblem}</p>{/if}
          {#if listing}
            <p class="path">{listing.path || t("projects.places")}</p>
            <div class="actions">
              {#if listing.parent !== null}<button type="button" class="button" onclick={() => look(listing?.parent ?? "")}>{t("projects.up")}</button>{/if}
              {#if listing.path}<button type="button" class="button primary" onclick={useFolder}>{t("projects.use_folder")}</button>{/if}
            </div>
            {#if listing.folders.length === 0}
              <p class="muted">{t("projects.no_subfolder")}</p>
            {:else}
              <ul class="folders">
                {#each listing.folders as folder (folder.path)}
                  <li><button type="button" class="button folder" onclick={() => look(folder.path)}>{folder.name}</button></li>
                {/each}
              </ul>
              {#if listing.truncated}<p class="muted">{t("projects.truncated")}</p>{/if}
            {/if}
          {:else if !browseProblem}
            <p class="muted">{t("projects.loading")}</p>
          {/if}
        </div>
      {/if}
      <label for="project-name">{t("projects.name")}</label>
      <input id="project-name" type="text" bind:value={name} autocomplete="off" />
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !path.trim()}>{t("projects.add")}</button></div>
    </form>
  {:else if !problem}
    <p class="muted">{t("projects.loading")}</p>
  {/if}
</div>

<style>
  .projects {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    max-width: var(--measure);
    margin: 0 auto;
    padding: var(--space-5) var(--space-4) var(--space-6);
  }

  h1 {
    margin: 0;
    font-size: var(--text-xl);
  }

  h2 {
    margin: 0;
    font-size: var(--text-lg);
  }

  p {
    margin: 0;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .card.current {
    border-color: var(--color-accent);
  }

  .what {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .path {
    overflow-wrap: anywhere;
    color: var(--color-text-muted);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .warn,
  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .empty {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-lg);
    color: var(--color-text-muted);
  }

  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  label {
    font-weight: 600;
  }

  input {
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .browser {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }

  .folders {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-height: 16rem;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    list-style: none;
  }

  .folder {
    width: 100%;
    justify-content: flex-start;
    overflow-wrap: anywhere;
    text-align: left;
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }
</style>
