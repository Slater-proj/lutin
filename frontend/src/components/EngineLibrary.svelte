<script lang="ts">
  // The library of the engine in use (Hugging Face for llama.cpp): search a model, see its quantisations with what each one means for THIS machine, download one.
  // A download weighs gigabytes: it says the size and waits for a second click before it is sent with `confirm`. Searching reads the network, so strict offline mode is said and not tried.
  import { ApiError, api } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { canDownload, downloadBody, downloadPath, filesPath, searchPath, shortName, type LibraryFile } from "../lib/library";
  import { language, t } from "../lib/messages";

  let { engine, onstarted }: { engine: string; onstarted: () => void } = $props();

  type Hit = { repo: string; downloads: number; likes: number };

  const lang = language();
  let query = $state("");
  let results = $state<Hit[] | null>(null);
  let repo = $state("");
  let files = $state<LibraryFile[] | null>(null);
  let confirming = $state("");
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("library.only_here");
      if (cause.code === "offline") return t("library.offline");
      if (cause.code === "no_library") return t("library.none");
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

  const search = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      repo = "";
      files = null;
      results = (await api<{ results: Hit[] }>("GET", searchPath(engine, query))).results;
    });
  };

  const open = (hit: Hit): Promise<void> =>
    act(async () => {
      confirming = "";
      files = null;
      repo = hit.repo;
      files = (await api<{ files: LibraryFile[] }>("GET", filesPath(engine, hit.repo))).files;
    });

  // The first click asks (with the size); the second one downloads.
  const download = (file: LibraryFile): Promise<void> => {
    if (confirming !== file.file) {
      confirming = file.file;
      return Promise.resolve();
    }
    return act(async () => {
      await api("POST", downloadPath(engine), downloadBody(repo, file, true));
      confirming = "";
      done = t("library.started", file.file);
      onstarted();
    });
  };
</script>

<section class="library" aria-labelledby="library-title">
  <h3 id="library-title">{t("library.title")}</h3>
  <p class="muted">{t("library.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}

  <form class="row" onsubmit={search}>
    <label for="library-query">{t("library.query")}</label>
    <input id="library-query" type="text" bind:value={query} autocomplete="off" spellcheck="false" placeholder="qwen3" />
    <button type="submit" class="button primary" disabled={busy || !query.trim()}>{t("library.search")}</button>
  </form>

  {#if results}
    {#if results.length === 0}
      <p class="empty">{t("library.no_result")}</p>
    {:else}
      <ul class="list" aria-label={t("library.title")}>
        {#each results as hit (hit.repo)}
          <li class="item" class:open={hit.repo === repo}>
            <div class="line">
              <strong>{shortName(hit.repo)}</strong>
              <span class="muted">{hit.repo} · {t("library.downloads", hit.downloads)} · {t("library.likes", hit.likes)}</span>
            </div>
            <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => open(hit)}>{t("library.files")}</button></div>
            {#if hit.repo === repo && files}
              {#if files.length === 0}
                <p class="empty">{t("library.no_files")}</p>
              {:else}
                <ul class="list files" aria-label={t("library.files_of", shortName(hit.repo))}>
                  {#each files as file (file.file)}
                    <li class="file">
                      <div class="line">
                        <strong>{file.file}</strong>
                        <span class="muted">{file.size_bytes ? formatBytes(file.size_bytes, lang) : t("library.size_unknown")}</span>
                        {#if file.fit}<span class="badge {file.fit.level === 'too_big' ? 'bad' : file.fit.level === 'tight' ? 'warning' : 'ok'}">{t(("library.fit_" + file.fit.level) as "library.fit_good")}</span>{/if}
                      </div>
                      {#if file.fit}<p class="muted">{file.fit.text}</p>{/if}
                      {#if confirming === file.file}<p class="warn" role="status">{t("library.confirm", file.file, file.size_bytes ? formatBytes(file.size_bytes, lang) : "?")}</p>{/if}
                      <div class="actions">
                        <button type="button" class="button primary" disabled={busy || !canDownload(file)} onclick={() => download(file)}>{confirming === file.file ? t("library.confirm_yes") : t("library.download")}</button>
                        {#if confirming === file.file}<button type="button" class="button" onclick={() => (confirming = "")}>{t("chat.cancel")}</button>{/if}
                      </div>
                    </li>
                  {/each}
                </ul>
              {/if}
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .library {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .row,
  .line,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .item,
  .file {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .file {
    background: var(--color-bg);
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

  input[type="text"] {
    max-width: 20rem;
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
