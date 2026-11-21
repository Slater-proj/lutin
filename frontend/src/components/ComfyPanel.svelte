<script lang="ts">
  // The ComfyUI panel: where it is installed, the models it holds, what Lutin can make with them, and the download of a model. It is read when opened, then again every few seconds
  // while it stays open (ComfyUI is asked each time, so a closed panel asks nothing). A download weighs gigabytes and only Hugging Face and Civitai are allowed: it waits for a second
  // click and the server says no to anything else. For the machine itself only.
  import { onDestroy } from "svelte";
  import { ApiError, api } from "../lib/api";
  import { canAskDownload, downloadBody, downloadShare, kindCounts, type ComfyPanel } from "../lib/comfy";
  import { formatBytes } from "../lib/format";
  import { language, t } from "../lib/messages";

  const base = "/addons/comfyui/panel";
  const lang = language();

  let panel = $state<ComfyPanel | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let folder = $state("");
  let url = $state("");
  let kind = $state("checkpoints");
  let confirming = $state(false);
  let timer: ReturnType<typeof setInterval> | undefined;

  const share = $derived(panel ? downloadShare(panel.download) : null);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("comfy.only_here");
      if (cause.code === "offline") return t("comfy.offline");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function read(): Promise<void> {
    panel = (await api<{ panel: ComfyPanel }>("GET", base)).panel;
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function stop(): void {
    if (timer) clearInterval(timer);
    timer = undefined;
  }

  function opened(open: boolean): void {
    stop();
    if (!open) return;
    void act(read);
    timer = setInterval(() => void read().catch(stop), 4000);
  }

  const send = (action: string, body: Record<string, unknown> = {}): Promise<void> =>
    act(async () => {
      panel = (await api<{ panel: ComfyPanel }>("POST", `${base}/${action}`, body)).panel;
    });

  const useFolder = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return send("use_folder", { folder: folder.trim() }).then(() => {
      folder = "";
    });
  };

  const download = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    if (!confirming) {
      confirming = true;
      return Promise.resolve();
    }
    return send("download", downloadBody(url, kind, true)).then(() => {
      confirming = false;
      url = "";
    });
  };

  onDestroy(stop);
</script>

<details class="comfy" ontoggle={(event) => opened(event.currentTarget.open)}>
  <summary>{t("comfy.title")}</summary>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if panel}
    <p>
      <span class={"badge" + (panel.running ? " on" : "")}>{panel.running ? t("comfy.running") : t("comfy.stopped")}</span>
      {#if panel.version}<span class="muted">{t("comfy.version", panel.version)}</span>{/if}
      {#if panel.gpu}<span class="muted">· {panel.gpu}</span>{/if}
    </p>
    {#if panel.error && !panel.running}<p class="muted">{panel.error}</p>{/if}

    <h4>{t("comfy.folder")}</h4>
    {#if panel.folder}
      <p><code>{panel.folder}</code> <span class={"badge" + (panel.folder_valid ? " on" : "")}>{panel.folder_valid ? t("comfy.folder_ok") : t("comfy.folder_bad")}</span></p>
      {#if panel.folder_problem}<p class="warn">{panel.folder_problem}</p>{/if}
    {:else}
      <p class="muted">{t("comfy.folder_none")}</p>
    {/if}
    <form class="row" onsubmit={useFolder}>
      <label for="comfy-folder">{t("comfy.folder_label")}</label>
      <input id="comfy-folder" type="text" bind:value={folder} autocomplete="off" spellcheck="false" />
      <button type="submit" class="button" disabled={busy || !folder.trim()}>{t("comfy.folder_use")}</button>
      <button type="button" class="button" disabled={busy} onclick={() => send("detect")}>{t("comfy.detect")}</button>
    </form>

    <h4>{t("comfy.models")}</h4>
    {#if kindCounts(panel.models.by_kind).length === 0}
      <p class="muted">{t("comfy.models_none")}</p>
    {:else}
      <ul class="plain" aria-label={t("comfy.models")}>
        {#each kindCounts(panel.models.by_kind) as entry (entry.kind)}<li>{entry.kind}: {entry.count}</li>{/each}
      </ul>
    {/if}
    <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => send("refresh_models")}>{t("comfy.refresh")}</button></div>
    {#if panel.unusable_models.length}<p class="muted">{t("comfy.unusable", panel.unusable_models.length)}</p>{/if}

    <h4>{t("comfy.makes")}</h4>
    <ul class="plain" aria-label={t("comfy.makes")}>
      <li>{t("comfy.image")}: {panel.engines.image.join(", ") || "—"}</li>
      <li>{t("comfy.video")}: {panel.engines.video.join(", ") || "—"}</li>
      <li>{t("comfy.sound")}: {panel.engines.sound.join(", ") || "—"}</li>
    </ul>

    <h4>{t("comfy.download")}</h4>
    {#if panel.download.state === "running"}
      <p role="status">{t("comfy.downloading", panel.download.name)}{share !== null ? " · " + share + " %" : ""}{panel.download.total_bytes ? " · " + formatBytes(panel.download.done_bytes, lang) + " / " + formatBytes(panel.download.total_bytes, lang) : ""}</p>
      <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => send("cancel_download")}>{t("comfy.cancel")}</button></div>
    {:else}
      {#if panel.download.state === "done"}<p class="done" role="status">{t("comfy.done", panel.download.name)}</p>{/if}
      {#if panel.download.state === "failed"}<p class="warn" role="status">{panel.download.error}</p>{/if}
      <form onsubmit={download}>
        <p class="muted">{t("comfy.download_help")}</p>
        <label for="comfy-url">{t("comfy.url")}</label>
        <input id="comfy-url" type="text" bind:value={url} oninput={() => (confirming = false)} autocomplete="off" spellcheck="false" placeholder="https://huggingface.co/…" />
        <label for="comfy-kind">{t("comfy.kind")}</label>
        <select id="comfy-kind" bind:value={kind} onchange={() => (confirming = false)}>
          {#each panel.download_kinds as option (option)}<option value={option}>{option}</option>{/each}
        </select>
        {#if confirming}<p class="warn" role="status">{t("comfy.confirm", panel.folder)}</p>{/if}
        <div class="actions">
          <button type="submit" class="button primary" disabled={busy || !canAskDownload(panel, url, kind)}>{confirming ? t("comfy.confirm_yes") : t("comfy.start")}</button>
          {#if confirming}<button type="button" class="button" onclick={() => (confirming = false)}>{t("chat.cancel")}</button>{/if}
        </div>
      </form>
    {/if}
  {:else if !problem}
    <p class="muted">{t("comfy.loading")}</p>
  {/if}
</details>

<style>
  .comfy {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  summary {
    cursor: pointer;
    font-weight: 600;
  }

  h4,
  p {
    margin: var(--space-2) 0 0;
  }

  h4 {
    font-size: var(--text-sm);
  }

  .muted {
    color: var(--color-text-muted);
  }

  .plain {
    margin: 0;
    padding-left: var(--space-4);
  }

  .row,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  select {
    max-width: 32rem;
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

  .badge.on {
    color: var(--color-accent-text);
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
