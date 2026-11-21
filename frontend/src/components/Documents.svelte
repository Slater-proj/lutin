<script lang="ts">
  // « Documents and notes » in Settings › Knowledge (docs/modernization/PARITY.md, item 14): the documents Lutin reads in the work folder and a search
  // in them (with the notes, skills and conversations); the notes one by one, added or deleted; and the small model of the search by meaning,
  // installed with one click from this machine.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes, percent } from "../lib/format";
  import { language, t } from "../lib/messages";

  type DocumentsView = { folders: string[]; formats: string[]; files: { name: string; passages: number }[]; errors: string[]; max: number };
  type Passage = { source: string; title: string; extract: string; conversation: boolean };
  type Note = { line: string; date: string | null; text: string };
  type Meaning = { active: boolean; model: string; installed: boolean; installation: { state: string; done_bytes: number; total_bytes: number; error: string } };

  const lang = language();
  let docs = $state<DocumentsView | null>(null);
  let words = $state("");
  let passages = $state<Passage[] | null>(null);
  let notes = $state<Note[] | null>(null);
  let note = $state("");
  let meaning = $state<Meaning | null>(null);
  let canConfigure = $state(false);
  let busy = $state(false);
  let problem = $state("");
  let timer: ReturnType<typeof setInterval> | undefined;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const search = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => void (passages = (await api<{ passages: Passage[] }>("GET", "/documents/search?q=" + encodeURIComponent(words.trim()))).passages));
  };
  const addNote = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      notes = (await api<{ notes: Note[] }>("POST", "/notes", { text: note })).notes;
      note = "";
    });
  };
  const removeNote = (entry: Note): Promise<void> => act(async () => void (notes = (await api<{ notes: Note[] }>("DELETE", "/notes?line=" + encodeURIComponent(entry.line))).notes));
  const install = (): Promise<void> =>
    act(async () => {
      meaning = await api<Meaning>("POST", "/search-by-meaning/install", {});
      clearInterval(timer);
      timer = setInterval(async () => {
        meaning = await api<Meaning>("GET", "/search-by-meaning").catch(() => meaning);
        if (meaning?.installation.state !== "running") clearInterval(timer);
      }, 1500);
    });

  onMount(() => {
    api<DocumentsView>("GET", "/documents").then((answer) => (docs = answer), (cause) => (problem = explain(cause)));
    api<{ notes: Note[] }>("GET", "/notes").then((answer) => (notes = answer.notes), () => undefined);
    api<Meaning>("GET", "/search-by-meaning").then((answer) => (meaning = answer), () => undefined);
    api<{ access: { can_configure: boolean } }>("GET", "/status").then((answer) => (canConfigure = answer.access.can_configure), () => undefined);
    return () => clearInterval(timer);
  });
</script>

<section class="documents" aria-labelledby="documents-title">
  <h2 id="documents-title">{t("docs.title")}</h2>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if docs}
    <p class="muted">{t("docs.where", docs.folders.join(", "), docs.formats.join(" "))}</p>
    {#if docs.files.length}
      <details>
        <summary>{t("docs.files", docs.files.length)}</summary>
        <ul>{#each docs.files as file (file.name)}<li>{file.name} <span class="muted">{t("docs.passages", file.passages)}</span></li>{/each}</ul>
      </details>
    {:else}
      <p class="muted">{t("docs.none")}</p>
    {/if}
    {#each docs.errors as error, index (index)}<p class="warn">{error}</p>{/each}
  {/if}
  <form class="row" onsubmit={search}>
    <label class="field" for="documents-search">{t("docs.search")}</label>
    <input id="documents-search" type="search" bind:value={words} />
    <button type="submit" class="button" disabled={busy || words.trim().length < 2}>{t("olib.search")}</button>
  </form>
  {#if passages}
    {#if passages.length === 0}<p class="muted">{t("olib.none")}</p>{/if}
    <ul class="passages">
      {#each passages as passage, index (index)}<li><strong>{passage.title}</strong> <span class="muted">{passage.source}</span><p>{passage.extract}</p></li>{/each}
    </ul>
  {/if}

  <h3>{t("notes.title")}</h3>
  <p class="muted">{t("notes.help")}</p>
  {#if notes}
    {#if notes.length === 0}<p class="muted">{t("notes.none")}</p>{/if}
    <ul class="notes">
      {#each notes as entry (entry.line)}
        <li><span>{entry.date ? entry.date + " · " : ""}{entry.text}</span>
          <button type="button" class="button quiet danger" disabled={busy} onclick={() => removeNote(entry)}>{t("devices.remove")}<span class="visually-hidden"> {entry.text}</span></button></li>
      {/each}
    </ul>
  {/if}
  <form class="row" onsubmit={addNote}>
    <label class="field" for="note-text">{t("notes.add")}</label>
    <input id="note-text" type="text" maxlength="600" bind:value={note} />
    <button type="submit" class="button" disabled={busy || !note.trim()}>{t("notes.keep")}</button>
  </form>

  {#if meaning}
    <h3>{t("meaning.title")}</h3>
    <p class="muted">{t("meaning.help", meaning.model)}</p>
    {#if meaning.installed}
      <p>{t("meaning.installed")}{meaning.active ? "" : " " + t("meaning.off")}</p>
    {:else if meaning.installation.state === "running"}
      {@const share = percent(meaning.installation.done_bytes, meaning.installation.total_bytes)}
      <progress max="100" value={share ?? undefined} aria-label={meaning.model}></progress>
      <p class="muted" role="status">{t("meaning.installing")}{meaning.installation.total_bytes ? " " + formatBytes(meaning.installation.done_bytes, lang) + " / " + formatBytes(meaning.installation.total_bytes, lang) : ""}</p>
    {:else}
      {#if meaning.installation.error}<p class="problem">{meaning.installation.error}</p>{/if}
      {#if canConfigure}<div class="row"><button type="button" class="button" disabled={busy} onclick={install}>{t("meaning.install")}</button></div>{/if}
    {/if}
  {/if}
</section>

<style>
  .documents {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
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
    margin-top: var(--space-3);
    font-size: var(--text-md, 1rem);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .problem {
    color: var(--color-danger);
  }

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .row input {
    flex: 1 1 14rem;
    min-width: 0;
  }

  .field {
    flex-basis: 100%;
    font-weight: 600;
  }

  ul {
    margin: 0;
    padding-left: var(--space-4);
  }

  .notes li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    overflow-wrap: anywhere;
  }

  .passages li {
    margin-bottom: var(--space-2);
    overflow-wrap: anywhere;
  }
</style>
