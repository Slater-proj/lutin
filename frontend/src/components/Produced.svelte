<script lang="ts">
  // What a tool produced in a conversation (docs/modernization/PARITY.md, item 5): the images it generated and the files it created, shown under its
  // result and not folded with it. An image opens in full in a new tab; a file is downloaded, or opened by this machine's system. Deleting asks a
  // second click, then erases the file from the disk: only from this machine's browser, and never for a conversation held by another machine
  // (its files are managed there, as on the old page).
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { language, t } from "../lib/messages";
  import { conversationPath, imageUrl, producedFileUrl } from "../lib/place";
  import type { Produced } from "../lib/turn";
  import Icon from "./Icon.svelte";

  let { produced, conversation, machine = "", canOpen = false, canDelete = false, ondeleted }: {
    produced: Produced;
    conversation: string;
    machine?: string;
    canOpen?: boolean;
    canDelete?: boolean;
    ondeleted?: (kind: "media" | "files", id: string) => void;
  } = $props();

  const lang = language();
  let asking = $state(""); // "media:<id>" or "files:<id>": the item whose deletion waits for the second click
  let busy = $state(false);
  let problem = $state("");

  const fileName = (path: string, id: string): string => path.split(/[\\/]/).pop() || "lutin-" + id;

  function said(cause: unknown): string {
    return cause instanceof ApiError && cause.message ? cause.message : t("error.generic", String(cause));
  }

  async function open(id: string): Promise<void> {
    problem = "";
    try {
      await api("POST", `${conversationPath(machine, conversation)}/files/${encodeURIComponent(id)}/open`, {});
    } catch (cause) {
      problem = said(cause);
    }
  }

  async function remove(kind: "media" | "files", id: string): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    try {
      await api("DELETE", `${conversationPath(machine, conversation)}/${kind}/${encodeURIComponent(id)}`);
      asking = "";
      ondeleted?.(kind, id);
    } catch (cause) {
      problem = said(cause);
    }
    busy = false;
  }
</script>

{#snippet confirm(kind: "media" | "files", id: string)}
  <span class="confirm" role="group" aria-label={t(kind === "media" ? "produced.confirm_image" : "produced.confirm_file")}>
    <span>{t(kind === "media" ? "produced.confirm_image" : "produced.confirm_file")}</span>
    <button type="button" class="quiet-action danger confirm-delete" disabled={busy} onclick={() => remove(kind, id)}>{t("produced.delete")}</button>
    <button type="button" class="quiet-action" onclick={() => (asking = "")}>{t("chat.cancel")}</button>
  </span>
{/snippet}

{#if produced.media.length || produced.files.length}
  <div class="produced">
    {#each produced.media as image (image.id)}
      <figure class="media">
        <a href={imageUrl(machine, image.id)} target="_blank" rel="noopener"><img src={imageUrl(machine, image.id)} alt={t("produced.image")} loading="lazy" /></a>
        {#if image.path}<code class="path" title={t("produced.where")}>{image.path}</code>{/if}
        <div class="actions">
          <a class="quiet-action" href={imageUrl(machine, image.id)} download={fileName(image.path, image.id)}>{t("produced.download")}</a>
          {#if canDelete}
            {#if asking === "media:" + image.id}
              {@render confirm("media", image.id)}
            {:else}
              <button type="button" class="quiet-action delete" onclick={() => (asking = "media:" + image.id)}>{t("produced.delete")}</button>
            {/if}
          {/if}
        </div>
      </figure>
    {/each}
    {#each produced.files as file (file.id)}
      <div class="file">
        <p class="name"><Icon name="file" size={16} /><span>{file.name}</span>{#if file.size}<span class="muted">{formatBytes(file.size, lang)}</span>{/if}</p>
        {#if file.path}<code class="path" title={t("produced.where")}>{file.path}</code>{/if}
        <div class="actions">
          {#if canOpen}<button type="button" class="quiet-action open" onclick={() => open(file.id)}>{t("produced.open")}</button>{/if}
          <a class="quiet-action" href={producedFileUrl(machine, conversation, file.id, file.name)} download={file.name}>{t("produced.download")}</a>
          {#if canDelete}
            {#if asking === "files:" + file.id}
              {@render confirm("files", file.id)}
            {:else}
              <button type="button" class="quiet-action delete" onclick={() => (asking = "files:" + file.id)}>{t("produced.delete")}</button>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  </div>
{/if}

<style>
  .produced {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .media {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
  }

  .media img {
    display: block;
    max-width: min(100%, 32rem);
    max-height: 32rem;
    border-radius: var(--radius-md);
    object-fit: contain;
    cursor: zoom-in;
  }

  .file {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .muted {
    font-weight: 400;
    color: var(--color-text-muted);
  }

  .path {
    font-size: var(--text-xs);
    color: var(--color-text-muted);
    overflow-wrap: anywhere;
  }

  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .quiet-action {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
    padding: 0 var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: none;
    color: var(--color-text-muted);
    font: inherit;
    font-size: var(--text-xs);
    text-decoration: none;
    cursor: pointer;
  }

  .quiet-action:hover {
    color: var(--color-text);
  }

  .danger {
    border-color: var(--color-danger);
    color: var(--color-danger);
  }

  .problem {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
    font-size: var(--text-sm);
  }
</style>
