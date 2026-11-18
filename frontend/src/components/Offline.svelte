<script lang="ts">
  // « Strict offline mode » in the section « Safety » of Settings (docs/modernization/PARITY.md, item 7): no connection leaves for the Internet,
  // only this machine and the services the person set up. Anyone may turn it on; only this machine turns it off (a paired phone cannot open it to
  // the network), and LUTIN_HORS_LIGNE=1 keeps it on for the whole launch. The shell reads its status again (event `lutin-status`) after a change:
  // its mark in the navigation and the « Web » option of the Chat follow.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type OfflineView = { active: boolean; forced: boolean; can_turn_off: boolean; allowed_hosts: string[]; blocks: string[] };

  let view = $state<OfflineView | null>(null);
  let busy = $state(false);
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function change(on: boolean): Promise<void> {
    busy = true;
    problem = "";
    try {
      view = await api<OfflineView>(on ? "POST" : "DELETE", "/offline", on ? {} : undefined);
      dispatchEvent(new CustomEvent("lutin-status"));
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    api<OfflineView>("GET", "/offline").then((answer) => (view = answer), (cause) => (problem = explain(cause)));
  });
</script>

<section class="offline" aria-labelledby="offline-title">
  <h2 id="offline-title">{t("offline.title")}</h2>
  <p class="muted">{t("offline.help")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if view}
    <p class="state" role="status">{view.active ? t("offline.on") : t("offline.off")}</p>
    {#if view.active}
      {#if view.forced}
        <p class="muted">{t("offline.forced")}</p>
      {:else if view.can_turn_off}
        <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => change(false)}>{t("offline.turn_off")}</button></div>
      {:else}
        <p class="muted">{t("offline.not_here")}</p>
      {/if}
    {:else}
      <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={() => change(true)}>{t("offline.turn_on")}</button></div>
    {/if}
    <details>
      <summary>{t("offline.details")}</summary>
      <p>{t("offline.blocks")}</p>
      <ul>{#each view.blocks as name (name)}<li>{t(("offline.block." + name) as MessageKey)}</li>{/each}</ul>
      <p>{t("offline.allowed")}</p>
      <ul class="hosts">{#each view.allowed_hosts as host (host)}<li><code>{host}</code></li>{/each}</ul>
    </details>
  {/if}
</section>

<style>
  .offline {
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

  .state {
    font-weight: 600;
  }

  .problem {
    color: var(--color-danger);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  ul {
    margin: var(--space-1) 0 var(--space-2);
  }

  .hosts code {
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }
</style>
