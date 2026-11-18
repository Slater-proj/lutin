<script lang="ts">
  // « Lutin's version » in the section « General » of Settings (docs/modernization/PARITY.md, item 6): the version running, « check for updates »
  // (one request to GitHub now), the update asked with a second click and followed line by line (GET /lutin/update every 1.2 s), the command that
  // does the same in a terminal, and « Restart Lutin ». The banner « Update » leads here (`#/settings/general/version`). An update started before a
  // reload is followed again. The status of the shell is read again (event `lutin-status`) when what it shows changes.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { copyText } from "../lib/clipboard";
  import { untilRestarted, updateOver, type NewVersion, type UpdateView } from "../lib/lutin";
  import { t, type MessageKey } from "../lib/messages";
  import type { Status } from "../lib/types";

  let status = $state<Status | null>(null);
  let view = $state<UpdateView | null>(null);
  let busy = $state(false);
  let asking = $state(false); // the first click on « Update Lutin »: the confirmation shows
  let checked = $state("");
  let problem = $state("");
  let copied = $state(false);
  let restarting = $state(false);
  let heading = $state<HTMLHeadingElement | null>(null);
  let alive = true;

  const canConfigure = $derived(!!status?.access.can_configure);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  const refreshShell = (): void => void dispatchEvent(new CustomEvent("lutin-status"));

  async function check(): Promise<void> {
    busy = true;
    problem = "";
    checked = t("lutin.checking");
    try {
      const answer = await api<{ current: string; latest: string; new_version: NewVersion | null }>("POST", "/lutin/check", {});
      checked = answer.new_version ? t("lutin.available", answer.new_version.version) : t("lutin.up_to_date", answer.current);
      refreshShell();
    } catch (cause) {
      checked = "";
      problem = explain(cause);
    }
    busy = false;
  }

  async function follow(): Promise<void> {
    while (alive && view && !updateOver(view.state)) {
      await new Promise((done) => setTimeout(done, 1200));
      try {
        view = await api<UpdateView>("GET", "/lutin/update");
      } catch {
        break; // the server stopped answering: it is restarting
      }
    }
    if (!alive || !view) return;
    if (view.state === "running" || view.state === "restarting") await waitForRestart();
    else refreshShell(); // « installed » asks for a restart: the banner says so
  }

  async function update(): Promise<void> {
    asking = false;
    busy = true;
    problem = "";
    try {
      view = await api<UpdateView>("POST", "/lutin/update", {});
      await follow();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function waitForRestart(): Promise<void> {
    restarting = true;
    const back = await untilRestarted(() => api("GET", "/status").then(() => true, () => false));
    if (back) location.reload();
    else problem = t("lutin.restart_failed");
    restarting = false;
  }

  async function restart(): Promise<void> {
    busy = true;
    problem = "";
    try {
      await api("POST", "/lutin/restart", {});
      await waitForRestart();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  async function copy(): Promise<void> {
    if (!view) return;
    await copyText(view.command);
    copied = true;
    setTimeout(() => (copied = false), 2000);
  }

  function ended(state: UpdateView): string {
    if (state.state === "idle" || state.state === "running") return "";
    return t(("lutin.state." + state.state) as MessageKey, state.before, state.after);
  }

  onMount(() => {
    api<Status>("GET", "/status").then((answer) => (status = answer), (cause) => (problem = explain(cause)));
    api<UpdateView>("GET", "/lutin/update").then((answer) => {
      view = answer;
      if (answer.state === "running") {
        busy = true;
        void follow().finally(() => (busy = false));
      }
    }, (cause) => (problem = explain(cause)));
    if (location.hash.endsWith("/version")) {
      queueMicrotask(() => heading?.scrollIntoView({ block: "start" }));
      setTimeout(() => heading?.focus(), 0);
    }
    return () => {
      alive = false;
    };
  });
</script>

<section class="lutin-version" aria-labelledby="lutin-version-title">
  <h2 id="lutin-version-title" tabindex="-1" bind:this={heading}>{t("lutin.title")}</h2>
  {#if status}<p>{t("lutin.current", status.version)}</p>{/if}
  <p class="muted">{t("lutin.help")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{restarting ? t("lutin.restarting") : checked}</p>

  {#if view}
    <div class="actions">
      {#if view.can_check}<button type="button" class="button" disabled={busy} onclick={check}>{t("lutin.check")}</button>{/if}
      {#if view.can_update && canConfigure}
        <button type="button" class="button primary" disabled={busy} onclick={() => (asking = true)}>{t("lutin.update_now")}</button>
      {/if}
      {#if view.can_restart && canConfigure}
        <button type="button" class="button" disabled={busy} onclick={restart}>{t("lutin.restart")}</button>
      {/if}
    </div>
    {#if asking}
      <div class="confirm" role="group" aria-label={t("lutin.update_now")}>
        <p>{t("lutin.update_confirm")}</p>
        <div class="actions">
          <button type="button" class="button primary" onclick={update}>{t("lutin.update_yes")}</button>
          <button type="button" class="button" onclick={() => (asking = false)}>{t("chat.cancel")}</button>
        </div>
      </div>
    {/if}

    {#if view.state !== "idle"}
      <div class="progress">
        <p class={view.state === "failed" ? "problem" : ""}>{view.state === "running" ? t("lutin.state.running") : ended(view)}</p>
        {#if view.lines.length}
          <details open={view.state === "running" || view.state === "failed"}>
            <summary>{t("lutin.lines")}</summary>
            <ol class="lines" aria-live="polite">
              {#each view.lines as line, index (index)}<li>{line}</li>{/each}
            </ol>
          </details>
        {/if}
      </div>
    {/if}

    <div class="part">
      {#if !view.can_update}<p class="muted">{t("lutin.in_docker")}</p>{:else if !canConfigure}<p class="muted">{t("lutin.update_not_here")}</p>{/if}
      <p class="command-row">
        <span>{t("lutin.command")}</span>
        <code class="command">{view.command}</code>
        <button type="button" class="button" onclick={copy}>{copied ? t("lutin.copied") : t("lutin.copy")}</button>
      </p>
    </div>
  {/if}
</section>

<style>
  .lutin-version {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: var(--text-lg);
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

  .progress {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .lines {
    margin: var(--space-2) 0 0;
    padding-left: var(--space-5, 1.5rem);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  .command-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .command {
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm, 4px);
    background: var(--color-code-bg);
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }
</style>
