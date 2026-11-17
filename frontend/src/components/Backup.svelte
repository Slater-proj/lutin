<script lang="ts">
  // Back up and restore the data (docs/modernization/PARITY.md, item 3), in the section « Data » of Settings: where the data is, one .zip to keep
  // elsewhere, and putting one back (a second click; the state before is kept in a zip of its own, then Lutin asks for a restart).
  import { onMount } from "svelte";
  import { api, ApiError, download, upload } from "../lib/api";
  import { t } from "../lib/messages";

  type Where = { config: string; data: string; memory: string; backups: string };
  type Restored = { files: number; kept_before: string; version: string; date: string; restart_needed: boolean };
  let where = $state<Where | null>(null);
  let chosen = $state<File | null>(null);
  let busy = $state(false);
  let problem = $state("");
  let notice = $state("");
  let input = $state<HTMLInputElement | null>(null);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.code === "configurator" ? t("backup.not_here") : cause.message || t("error.generic", cause.code);
    return t("error.generic", String(cause));
  }

  async function save(): Promise<void> {
    busy = true;
    problem = notice = "";
    try {
      await download("/backup", "lutin-backup.zip");
      notice = t("backup.saved");
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function restore(): Promise<void> {
    if (!chosen) return;
    busy = true;
    problem = notice = "";
    try {
      const done = await upload<Restored>("/backup/restore", chosen);
      notice = t("backup.restored", done.files, done.date || "?") + (done.restart_needed ? " " + t("backup.restart") : "");
      chosen = null;
      if (input) input.value = "";
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    api<Where>("GET", "/backup/where").then((answer) => (where = answer), (cause) => (problem = explain(cause)));
  });
</script>

<section class="backup" aria-labelledby="backup-title">
  <h2 id="backup-title">{t("backup.title")}</h2>
  <p class="muted">{t("backup.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if where}
    <dl>
      <dt>{t("backup.data")}</dt><dd>{where.data}</dd>
      <dt>{t("backup.memory")}</dt><dd>{where.memory}</dd>
      {#if where.config}<dt>{t("backup.config")}</dt><dd>{where.config}</dd>{/if}
      <dt>{t("backup.backups")}</dt><dd>{where.backups}</dd>
    </dl>
  {/if}
  <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={save}>{t("backup.save")}</button></div>
  <div class="part">
    <h3>{t("backup.restore_title")}</h3>
    <p class="muted">{t("backup.restore_help")}</p>
    <label for="backup-file">{t("backup.choose")}</label>
    <input id="backup-file" type="file" accept=".zip,application/zip" bind:this={input} onchange={(event) => (chosen = event.currentTarget.files?.[0] ?? null)} />
    {#if chosen}
      <div class="confirm" role="group" aria-label={t("backup.restore_title")}>
        <p>{t("backup.confirm", chosen.name)}</p>
        <div class="actions">
          <button type="button" class="button danger" disabled={busy} onclick={restore}>{t("backup.restore")}</button>
          <button type="button" class="button" onclick={() => { chosen = null; if (input) input.value = ""; }}>{t("chat.cancel")}</button>
        </div>
      </div>
    {/if}
  </div>
</section>

<style>
  .backup {
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
    font-size: var(--text-md);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    max-width: var(--measure);
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

  dl {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: var(--space-1) var(--space-3);
    margin: 0;
    font-size: var(--text-sm);
  }

  dt {
    font-weight: 600;
  }

  dd {
    margin: 0;
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }

  label {
    font-weight: 600;
  }

  .part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }
</style>
