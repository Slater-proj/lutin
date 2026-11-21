<script lang="ts">
  // « Lend this machine » (ADR 0016, stage 5): this computer as a node for the machines paired with it. What waits for its owner (rights requests,
  // a shutdown asked by another machine), lending on or off, a pairing code with the address to type on the other machine, the machines that may
  // use this one (revoked with a second click), what it shares and allows, and autostart. Read again every 5 s; after each reading the number of
  // things waiting is announced (event `lutin-node`) for the badge of Settings in the navigation.
  // The server has the last word on rights: what may only be changed from this machine itself answers 403 elsewhere, and that answer is shown.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { RIGHTS, type Right } from "../lib/machines";
  import { t, type MessageKey } from "../lib/messages";
  import { requestPath, SHARES, waiting, type NodeView, type Share } from "../lib/node";
  import type { Status } from "../lib/types";

  let node = $state<NodeView | null>(null);
  let level = $state("");
  let address = $state("");
  let code = $state<{ code: string; valid_seconds: number } | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let revoking = $state<string | null>(null);
  let renaming = $state<string | null>(null); // the machine being given a clear name, and that name
  let newName = $state("");
  let alive = true;

  const rightName = (right: Right): string => t(("machines.right." + right) as MessageKey);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  function announce(): void {
    dispatchEvent(new CustomEvent("lutin-node", { detail: waiting(node) }));
  }

  async function load(): Promise<void> {
    node = await api<NodeView>("GET", "/node");
    announce();
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    try {
      await action();
      await load();
    } catch (cause) {
      problem = explain(cause);
      await load().catch(() => undefined); // what the server holds is what is shown again
    }
    busy = false;
  }

  const setLending = (event: Event): Promise<void> =>
    act(async () => {
      node = await api<NodeView>("PATCH", "/node", { lending: (event.currentTarget as HTMLInputElement).checked });
      if (!node.lending) code = null;
    });

  const permit = (body: Record<string, unknown>): Promise<void> => act(async () => void (node = await api<NodeView>("PATCH", "/node/permissions", body)));

  const newCode = (): Promise<void> =>
    act(async () => {
      code = await api<{ code: string; valid_seconds: number }>("POST", "/node/pairing-code");
    });

  const revoke = (name: string): Promise<void> =>
    act(async () => {
      node = await api<NodeView>("DELETE", `/node/authorized/${encodeURIComponent(name)}`);
      revoking = null;
    });

  function rename(event: SubmitEvent, name: string): void {
    event.preventDefault();
    if (!newName.trim()) return;
    void act(async () => {
      node = await api<NodeView>("PATCH", `/node/authorized/${encodeURIComponent(name)}`, { name: newName.trim() });
      renaming = null;
    });
  }

  const answer = (request: NodeView["requests"][number], accept: boolean): Promise<void> =>
    act(async () => void (node = await api<NodeView>("POST", requestPath(request), { accept })));

  const cancelShutdown = (): Promise<void> => act(async () => void (await api("POST", "/node/shutdown/cancel")));

  onMount(() => {
    void load().catch((cause) => (problem = explain(cause)));
    api<Status>("GET", "/status").then((status) => (level = status.access.level), () => undefined);
    api<{ address: string }>("GET", "/devices").then((devices) => (address = devices.address), () => undefined);
    const timer = setInterval(() => {
      if (alive && !busy) void load().catch(() => undefined);
    }, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

<section class="lend" aria-labelledby="lend-title">
  <h2 id="lend-title">{t("lend.title")}</h2>
  <p class="muted">{t("lend.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if !node}
    {#if !problem}<p class="muted">{t("lend.loading")}</p>{/if}
  {:else}
    {#if node.requests.length}
      <div class="waiting requests">
        <h3>{t("lend.requests")}</h3>
        <ul>
          {#each node.requests as request (request.machine + request.right)}
            <li>
              <p>{t("lend.request", request.machine, rightName(request.right))} <span class="muted">{request.date}</span></p>
              <div class="actions">
                <button type="button" class="button primary" disabled={busy} onclick={() => answer(request, true)}>{t("lend.accept")}</button>
                <button type="button" class="button" disabled={busy} onclick={() => answer(request, false)}>{t("lend.refuse")}</button>
              </div>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if node.pending_shutdown}
      <div class="waiting shutdown">
        <p><strong>{t("lend.shutdown", node.pending_shutdown.by, node.pending_shutdown.in_s)}</strong></p>
        <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={cancelShutdown}>{t("lend.cancel_shutdown")}</button></div>
      </div>
    {/if}

    {#if level === "local" && !node.lending}
      <p class="closed" role="note">{t("lend.local_level")} <a href="#/settings/devices">{t("lend.open_access")}</a></p>
    {:else}
      <div class="row switch">
        <label for="lend-on">{t("lend.on")}</label>
        <input id="lend-on" type="checkbox" role="switch" checked={node.lending} disabled={busy} onchange={setLending} aria-describedby="lend-on-help" />
        <p class="help" id="lend-on-help">{t("lend.on_help")}</p>
      </div>
    {/if}

    {#if node.lending}
      <div class="part">
        <h3>{t("lend.pairing")}</h3>
        {#if code}
          <p class="code" aria-live="polite">{code.code}</p>
          <p class="help">{t("lend.code_help", address || "http://…", Math.round(code.valid_seconds / 60))}</p>
        {/if}
        <div class="actions"><button type="button" class="button" disabled={busy} onclick={newCode}>{code ? t("lend.another_code") : t("lend.give_code")}</button></div>
      </div>

      <div class="part">
        <h3>{t("lend.authorized")}</h3>
        {#if node.authorized.length === 0}
          <p class="muted">{t("lend.none")}</p>
        {:else}
          <ul class="authorized">
            {#each node.authorized as allowed (allowed.name)}
              <li>
                <span><strong>{allowed.name}</strong> <span class="muted">{t("lend.since", allowed.date)}</span></span>
                {#if renaming === allowed.name}
                  <form class="confirm rename" onsubmit={(event) => rename(event, allowed.name)}>
                    <label class="visually-hidden" for="lend-rename">{t("lend.rename_label", allowed.name)}</label>
                    <input id="lend-rename" type="text" maxlength="40" autocomplete="off" bind:value={newName} />
                    <button type="submit" class="button primary" disabled={busy || !newName.trim()}>{t("lend.rename_save")}</button>
                    <button type="button" class="button" onclick={() => (renaming = null)}>{t("chat.cancel")}</button>
                  </form>
                {:else if revoking === allowed.name}
                  <span class="confirm" role="group" aria-label={t("lend.revoke")}>
                    <span>{t("lend.revoke_confirm", allowed.name)}</span>
                    <button type="button" class="button danger" disabled={busy} onclick={() => revoke(allowed.name)}>{t("lend.revoke")}</button>
                    <button type="button" class="button" onclick={() => (revoking = null)}>{t("chat.cancel")}</button>
                  </span>
                {:else}
                  <span class="actions">
                    <button type="button" class="button quiet" disabled={busy} onclick={() => ((renaming = allowed.name), (newName = allowed.name))}>{t("lend.rename")}<span class="visually-hidden"> {allowed.name}</span></button>
                    <button type="button" class="button quiet danger" disabled={busy} onclick={() => (revoking = allowed.name)}>{t("lend.revoke")}<span class="visually-hidden"> {allowed.name}</span></button>
                  </span>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}

    <div class="part">
      <h3>{t("lend.granted")}</h3>
      <p class="help">{t("lend.granted_help")}</p>
      <div class="fields">
        {#each SHARES as share (share)}
          <div class="row switch">
            <label for={"lend-share-" + share}>{t(("lend.share." + share) as MessageKey)}</label>
            <input id={"lend-share-" + share} type="checkbox" role="switch" checked={node.shares[share]} disabled={busy} onchange={(event) => permit({ shares: { [share as Share]: event.currentTarget.checked } })} />
          </div>
        {/each}
        {#each RIGHTS as right (right)}
          <div class="row switch">
            <label for={"lend-allow-" + right}>{t(("lend.allow." + right) as MessageKey)}<span class="care">{t("settings.risky")}</span></label>
            <input id={"lend-allow-" + right} type="checkbox" role="switch" checked={node.allow[right]} disabled={busy} onchange={(event) => permit({ allow: { [right]: event.currentTarget.checked } })} aria-describedby={"lend-allow-" + right + "-help"} />
            <p class="help" id={"lend-allow-" + right + "-help"}>{t(("lend.allow_help." + right) as MessageKey)}</p>
          </div>
        {/each}
      </div>
    </div>

    <div class="part">
      <div class="row switch">
        <label for="lend-autostart">{t("lend.autostart")}</label>
        <input id="lend-autostart" type="checkbox" role="switch" checked={node.startup.installed} disabled={busy || !node.startup.possible} onchange={(event) => permit({ autostart: event.currentTarget.checked })} aria-describedby="lend-autostart-help" />
        <p class="help" id="lend-autostart-help">{node.startup.limits}</p>
      </div>
    </div>
  {/if}
</section>

<style>
  .lend {
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

  .muted,
  .help {
    color: var(--color-text-muted);
  }

  .help,
  .muted {
    max-width: var(--measure);
    font-size: var(--text-sm);
  }

  .part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  .waiting {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .waiting ul,
  .authorized {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .authorized li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
    column-gap: var(--space-5);
  }

  .row {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--space-1);
    padding-top: var(--space-2);
  }

  .row.switch {
    grid-template-columns: 1fr auto;
    align-items: center;
    column-gap: var(--space-3);
  }

  .row.switch .help {
    grid-column: 1 / -1;
  }

  label {
    font-weight: 600;
  }

  .care {
    margin-left: var(--space-2);
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-warning-soft);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  input[type="checkbox"] {
    inline-size: 2.75rem;
    block-size: 1.5rem;
    accent-color: var(--color-accent);
  }

  .rename input {
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .code {
    font-family: var(--font-mono);
    font-size: var(--text-xl);
    font-weight: 700;
    letter-spacing: 0.08em;
  }

  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .closed {
    margin: 0;
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    max-width: var(--measure);
  }
</style>
