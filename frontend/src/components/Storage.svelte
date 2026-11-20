<script lang="ts">
  // « Files and locations » in Settings › Data (docs/modernization/PARITY.md, item 17): every folder Lutin uses with its size and the free space of
  // its disk, and every file Lutin created (documents, images, videos, sounds), to clean up: ticked, then deleted after a second click (from the disk
  // and from the conversations that show them). Paths of this machine: for this machine only.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t } from "../lib/messages";

  type Location = { key: string; name: string; path: string; explanation: string; exists: boolean; size_bytes: number | null; disk: { free: number; total: number } | null };
  type Created = { id: string; kind: string; name: string; path: string; size_bytes: number; date: number; conversation: string | null };

  const lang = language();
  let canConfigure = $state(false);
  let places = $state<Location[] | null>(null);
  let files = $state<Created[] | null>(null);
  let total = $state(0);
  let chosen = $state<string[]>([]);
  let asking = $state(false);
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const size = (bytes: number | null): string => (bytes === null ? "—" : formatBytes(bytes, lang));
  const day = (seconds: number): string => (seconds ? new Date(seconds * 1000).toLocaleDateString(lang) : "");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    const [where, made] = await Promise.all([api<{ locations: Location[] }>("GET", "/locations"), api<{ files: Created[]; total_bytes: number }>("GET", "/created-files")]);
    places = where.locations;
    files = made.files;
    total = made.total_bytes;
    chosen = chosen.filter((id) => made.files.some((file) => file.id === id));
  }

  async function remove(): Promise<void> {
    busy = true;
    problem = "";
    try {
      const done = await api<{ deleted: number; freed_bytes: number; skipped: string[] }>("POST", "/created-files/delete", { ids: chosen });
      notice = t("storage.deleted", done.deleted, size(done.freed_bytes)) + (done.skipped.length ? " " + done.skipped.join(" ; ") : "");
      asking = false;
      chosen = [];
      await load();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    api<{ access: { can_configure: boolean } }>("GET", "/status").then((answer) => {
      canConfigure = answer.access.can_configure;
      if (canConfigure) void load().catch((cause) => (problem = explain(cause)));
    }, () => undefined);
  });
</script>

<section class="storage" aria-labelledby="storage-title">
  <h2 id="storage-title">{t("storage.title")}</h2>
  {#if !canConfigure}
    <p class="muted">{t("storage.only_here")}</p>
  {:else}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    <p class="notice" role="status">{notice}</p>
    {#if places}
      <div class="table">
        <table>
          <caption class="visually-hidden">{t("storage.places")}</caption>
          <thead><tr><th scope="col">{t("storage.place")}</th><th scope="col">{t("storage.size")}</th><th scope="col">{t("storage.free")}</th></tr></thead>
          <tbody>
            {#each places as place (place.key)}
              <tr><th scope="row">{place.name}<small>{place.path}</small><small>{place.explanation}</small></th><td>{size(place.size_bytes)}</td><td>{place.disk ? size(place.disk.free) : "—"}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    {#if files}
      <h3>{t("storage.created", files.length, size(total))}</h3>
      {#if files.length === 0}
        <p class="muted">{t("storage.none")}</p>
      {:else}
        <fieldset disabled={busy}>
          <legend class="visually-hidden">{t("storage.created_list")}</legend>
          <label class="check"><input type="checkbox" checked={chosen.length === files.length} onchange={(event) => (chosen = event.currentTarget.checked ? files?.map((file) => file.id) ?? [] : [])} /> {t("storage.all")}</label>
          <ul>
            {#each files as file (file.id)}
              <li><label class="check"><input type="checkbox" value={file.id} bind:group={chosen} /> {file.name}</label> <span class="muted">{size(file.size_bytes)} · {day(file.date)}</span></li>
            {/each}
          </ul>
        </fieldset>
        {#if asking}
          <div class="confirm" role="group" aria-label={t("storage.delete")}>
            <span>{t("storage.delete_confirm", chosen.length)}</span>
            <button type="button" class="button danger" disabled={busy} onclick={remove}>{t("upkeep.delete_yes")}</button>
            <button type="button" class="button" onclick={() => (asking = false)}>{t("chat.cancel")}</button>
          </div>
        {:else}
          <div class="actions"><button type="button" class="button" disabled={busy || !chosen.length} onclick={() => (asking = true)}>{t("storage.delete")}</button></div>
        {/if}
      {/if}
    {/if}
  {/if}
</section>

<style>
  .storage,
  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
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

  .muted,
  small {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  small {
    display: block;
    font-weight: normal;
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

  .table {
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    min-width: 100%;
  }

  th,
  td {
    padding: var(--space-1) var(--space-2);
    border-bottom: 1px solid var(--color-border);
    text-align: left;
    vertical-align: top;
  }

  td {
    white-space: nowrap;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
    max-height: 20rem;
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow-y: auto;
  }

  li {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: baseline;
    overflow-wrap: anywhere;
  }

  .check {
    display: inline-flex;
    gap: var(--space-2);
    align-items: center;
  }

  .confirm,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
</style>
