<script lang="ts">
  // « Access » in the section « Devices » of Settings (docs/modernization/PARITY.md, item 9): who may reach Lutin. The level is saved for the next
  // start (the shell's banner then asks for a restart); opening it needs « I understand the risks », and behind a proxy its public address and the
  // trusted proxy. The remote administration lets every admitted device configure Lutin. Both open the machine: only this machine changes them
  // (`can_change`), and in Docker they come from the container's variables.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Level = "local" | "network" | "proxy";
  type View = {
    level: Level;
    port: number;
    public_url: string;
    proxy_ips: string[];
    saved: { level: Level; public_url: string; proxy_ips: string[] };
    restart_needed: boolean;
    address: string;
    docker: boolean;
    can_change: boolean;
    can_restart: boolean;
    remote_admin: { active: boolean; can_change: boolean };
    levels: { id: Level; title: string; detail: string }[];
    warnings: { network: string; proxy: string };
  };

  let view = $state<View | null>(null);
  let chosen = $state<Level>("local");
  let publicUrl = $state("");
  let proxies = $state("");
  let understood = $state(false);
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  const changed = $derived(!!view && (chosen !== view.saved.level || (chosen === "proxy" && (publicUrl.trim() !== view.saved.public_url || proxies.trim() !== view.saved.proxy_ips.join(" ")))));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  function shown(answer: View): void {
    view = answer;
    chosen = answer.saved.level;
    publicUrl = answer.saved.public_url;
    proxies = answer.saved.proxy_ips.join(" ");
    understood = false;
  }

  async function send(path: string, body: object, done: string): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    try {
      shown(await api<View>("PATCH", path, body));
      notice = done;
      dispatchEvent(new CustomEvent("lutin-status")); // the shell's banner « restart needed »
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function save(event: SubmitEvent): void {
    event.preventDefault();
    const body = { level: chosen, understood, public_url: chosen === "proxy" ? publicUrl.trim() : "", proxy_ips: chosen === "proxy" ? proxies.split(/[\s,]+/).filter(Boolean) : [] };
    void send("/access", body, t("access.saved"));
  }

  onMount(() => {
    api<View>("GET", "/access").then(shown, (cause) => (problem = explain(cause)));
  });
</script>

<section class="access" aria-labelledby="access-title">
  <h2 id="access-title" tabindex="-1">{t("access.title")}</h2>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if view}
    <p>{t("access.running", view.levels.find((level) => level.id === view?.level)?.title ?? view.level)}</p>
    {#if view.level !== "local"}<p class="muted">{t("access.address", view.address)}</p>{/if}
    {#if view.restart_needed}<p class="warn">{t("access.restart_needed", view.levels.find((level) => level.id === view?.saved.level)?.title ?? view.saved.level)}</p>{/if}
    {#if view.docker}
      <p class="muted">{t("access.docker")}</p>
    {:else if !view.can_change}
      <p class="muted">{t("access.only_here")}</p>
    {/if}

    <form onsubmit={save}>
      <fieldset disabled={!view.can_change || busy}>
        <legend>{t("access.level")}</legend>
        {#each view.levels as level (level.id)}
          <label class="choice">
            <input type="radio" name="access-level" value={level.id} bind:group={chosen} />
            <span><strong>{level.title}</strong><small>{level.detail}</small></span>
          </label>
        {/each}
        {#if chosen === "proxy"}
          <label class="field">{t("access.public_url")}<input type="url" placeholder="https://lutin.example.org" autocomplete="off" bind:value={publicUrl} /></label>
          <label class="field">{t("access.proxies")}<input type="text" placeholder="192.168.1.10" autocomplete="off" bind:value={proxies} /></label>
        {/if}
        {#if chosen !== "local" && changed}
          <p class="warn">{chosen === "proxy" ? view.warnings.proxy : view.warnings.network}</p>
          <label class="choice"><input type="checkbox" bind:checked={understood} /><span>{t("access.understood")}</span></label>
        {/if}
        <div class="actions">
          <button type="submit" class="button primary" disabled={!changed || (chosen !== "local" && !understood)}>{t("access.save")}</button>
        </div>
      </fieldset>
    </form>

    <div class="part">
      <h3>{t("access.remote_title")}</h3>
      <p class="muted">{t("access.remote_help")}</p>
      <p role="status">{view.remote_admin.active ? t("access.remote_on") : t("access.remote_off")}</p>
      {#if view.remote_admin.can_change}
        <div class="actions">
          <button type="button" class="button" disabled={busy} onclick={() => send("/access/remote-admin", { active: !view?.remote_admin.active }, "")}>
            {view.remote_admin.active ? t("access.remote_close") : t("access.remote_open")}
          </button>
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .access {
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
    font-size: var(--text-md, 1rem);
  }

  .muted,
  small {
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

  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    max-width: var(--measure);
  }

  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
  }

  legend {
    font-weight: 600;
    margin-bottom: var(--space-1);
  }

  .choice {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
  }

  .choice span {
    display: flex;
    flex-direction: column;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 32rem;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }
</style>
