<script lang="ts">
  // The two banners of Lutin's own version (docs/modernization/PARITY.md, item 6), above every screen, from GET /status: a newer version found by
  // the check made at launch (what's new, update — in Settings, where the update is followed —, later, ignore this version), and a change that
  // waits for a restart, with « Restart Lutin » when something starts it again and this browser may configure. Nothing is installed from here.
  import { api, ApiError } from "../lib/api";
  import { remindedLater, remindLater, untilRestarted } from "../lib/lutin";
  import { t } from "../lib/messages";
  import type { Status } from "../lib/types";

  let { status, onchanged }: { status: Status | null; onchanged: () => void } = $props();

  let later = $state<string[]>([]); // the versions put off in this page, on top of what the browser keeps
  let busy = $state(false);
  let restarting = $state(false);
  let problem = $state("");

  const shown = $derived(status?.new_version && !later.includes(status.new_version.version) && !remindedLater(status.new_version.version) ? status.new_version : null);
  const canRestart = $derived(!!status?.restart.possible && !!status?.access.can_configure);

  function explain(cause: unknown): string {
    return cause instanceof ApiError && cause.message ? cause.message : t("error.generic", cause instanceof ApiError ? cause.code : String(cause));
  }

  function putOff(version: string): void {
    remindLater(version);
    later = [...later, version];
  }

  async function ignore(version: string): Promise<void> {
    busy = true;
    problem = "";
    try {
      await api("POST", "/lutin/ignored-version", { version });
      onchanged();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function restart(): Promise<void> {
    busy = true;
    problem = "";
    try {
      await api("POST", "/lutin/restart", {});
    } catch (cause) {
      problem = explain(cause);
      busy = false;
      return;
    }
    restarting = true;
    const back = await untilRestarted(() => api("GET", "/status").then(() => true, () => false));
    if (back) location.reload();
    else problem = t("lutin.restart_failed");
    restarting = busy = false;
  }
</script>

{#if shown}
  <section class="lutin-banner new-version" aria-label={t("lutin.title")}>
    <p>{t("lutin.banner_new", shown.version, status?.version ?? "")}</p>
    <div class="actions">
      <a class="button" href={shown.page} target="_blank" rel="noopener noreferrer">{t("lutin.whats_new")}</a>
      <a class="button primary" href="#/settings/general/version">{t("lutin.update")}</a>
      <button type="button" class="button" onclick={() => putOff(shown.version)}>{t("lutin.later")}</button>
      <button type="button" class="button" disabled={busy} onclick={() => ignore(shown.version)}>{t("lutin.ignore")}</button>
    </div>
  </section>
{/if}
{#if status?.restart.needed || restarting}
  <section class="lutin-banner restart-needed" aria-label={t("lutin.restart")}>
    {#if restarting}
      <p role="status">{t("lutin.restarting")}</p>
    {:else}
      <p>{t("lutin.restart_needed")}{#if !canRestart}{" " + (status?.restart.possible ? t("lutin.restart_not_here") : t("lutin.restart_yourself"))}{/if}</p>
      {#if canRestart}
        <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={restart}>{t("lutin.restart")}</button></div>
      {/if}
    {/if}
  </section>
{/if}
{#if problem}<p class="lutin-problem" role="alert">{problem}</p>{/if}

<style>
  .lutin-banner {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    margin: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
  }

  .restart-needed {
    border-color: var(--color-border-strong);
    background: var(--color-warning-soft);
  }

  p {
    margin: 0;
    max-width: var(--measure);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .lutin-problem {
    margin: var(--space-3);
    color: var(--color-danger);
  }
</style>
