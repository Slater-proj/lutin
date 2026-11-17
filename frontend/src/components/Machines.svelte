<script lang="ts">
  // The Machines tab of the Models screen (ADR 0016, stage 4): the other computers whose engine this one may use. Who answers by default, one card
  // per machine (its state and wake sequence, what it allows, the rights one may ask for, its details), the form to pair one, and the log.
  // GET /machines never waits for the network (a stale machine is probed in the background): the list is read again every few seconds.
  // What stops or changes another machine (shut down, update, unpair) says what it does and waits for a second click.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { formatBytes } from "../lib/format";
  import { actionsOf, rightsToAsk, RIGHTS, type MachineAction, type MachinesView, type PairedMachine, type Right } from "../lib/machines";
  import { language, t, type MessageKey } from "../lib/messages";

  let { onchanged }: { onchanged: () => void } = $props();

  type Asked = "shutdown" | "update" | "unpair";
  const lang = language();
  let view = $state<MachinesView | null>(null);
  let problem = $state("");
  let notice = $state("");
  let busy = $state(false);
  let asking = $state<{ id: string; what: Asked } | null>(null);
  let address = $state("");
  let code = $state("");
  let name = $state("");
  let macs = $state<Record<string, string>>({});
  let alive = true;

  const rightName = (right: Right): string => t(("machines.right." + right) as MessageKey);
  const path = (machine: PairedMachine, rest = ""): string => `/machines/${encodeURIComponent(machine.id)}${rest}`;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("machines.not_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    view = await api<MachinesView>("GET", "/machines");
  }

  /** Runs one action, then reads the list again; what it did is said in `notice`, what went wrong in `problem`. */
  async function act(action: () => Promise<string>): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    notice = "";
    try {
      notice = await action();
      asking = null;
      await load();
      onchanged();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const turnOn = (): Promise<void> => act(async () => (await api("PATCH", "/settings", { cluster: true }), ""));

  const answering = (event: Event): Promise<void> =>
    act(async () => (await api("PATCH", "/settings", { machine: (event.currentTarget as HTMLSelectElement).value }), ""));

  function pair(event: SubmitEvent): void {
    event.preventDefault();
    if (!address.trim() || !code.trim()) return;
    void act(async () => {
      const paired = await api<PairedMachine>("POST", "/machines", { address: address.trim(), code: code.trim(), ...(name.trim() ? { name: name.trim() } : {}) });
      address = code = name = "";
      return t("machines.paired", paired.name);
    });
  }

  function click(machine: PairedMachine, action: MachineAction): void {
    if (action === "shutdown" || action === "update") asking = { id: machine.id, what: action };
    else void run(machine, action);
  }

  const run = (machine: PairedMachine, action: MachineAction): Promise<void> =>
    act(async () => {
      const answer = await api<{ mac?: string; shutdown_in_s?: number }>("POST", path(machine, "/actions/" + action));
      if (action === "wake") return t("machines.done.wake", answer.mac ?? "");
      if (action === "shutdown") return t("machines.done.shutdown", answer.shutdown_in_s ?? 30);
      return t(("machines.done." + action) as MessageKey);
    });

  const ask = (machine: PairedMachine, right: Right): Promise<void> =>
    act(async () => (await api("POST", path(machine, "/rights-requests"), { right }), t("machines.asked")));

  function saveMac(event: SubmitEvent, machine: PairedMachine): void {
    event.preventDefault();
    void act(async () => (await api("PATCH", path(machine), { mac: (macs[machine.id] ?? machine.mac).trim() }), ""));
  }

  const importFrom = (machine: PairedMachine, kind: "skills" | "memory"): Promise<void> =>
    act(async () => {
      const counts = await api<Record<string, number>>("POST", path(machine, "/imports/" + kind));
      return kind === "skills" ? t("machines.imported.skills", counts.added, counts.updated, counts.already_there) : t("machines.imported.memory", counts.notes_added, counts.notes_skipped);
    });

  const unpair = (machine: PairedMachine): Promise<void> => act(async () => (await api("DELETE", path(machine)), ""));

  function confirmed(machine: PairedMachine, what: Asked): void {
    if (what === "unpair") void unpair(machine);
    else void run(machine, what);
  }

  onMount(() => {
    void load().catch((cause) => (problem = explain(cause)));
    const timer = setInterval(() => {
      if (alive && !busy) void load().catch(() => undefined);
    }, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

<section class="machines" aria-labelledby="machines-title">
  <h2 id="machines-title">{t("machines.title")}</h2>
  <p class="muted">{t("machines.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>

  {#if !view}
    {#if !problem}<p class="muted">{t("machines.loading")}</p>{/if}
  {:else if !view.enabled}
    <p>{t("machines.off")}</p>
    <div class="actions"><button type="button" class="button primary turn-on" disabled={busy} onclick={turnOn}>{t("machines.turn_on")}</button></div>
  {:else}
    <div class="field">
      <label for="machine-answering">{t("machines.answering")}</label>
      <select id="machine-answering" onchange={answering} disabled={busy} aria-describedby="machine-answering-help">
        <option value="" selected={view.answering === ""}>{t("machines.this_one")}</option>
        {#each view.machines as machine (machine.id)}<option value={machine.id} selected={view.answering === machine.id}>{machine.name}</option>{/each}
      </select>
      <p class="help" id="machine-answering-help">{t("machines.answering_help")}</p>
    </div>

    {#if view.machines.length === 0}
      <p class="empty">{t("machines.none")}</p>
    {:else}
      <ul class="list" aria-label={t("machines.title")}>
        {#each view.machines as machine (machine.id)}
          {@const granted = RIGHTS.filter((right) => machine.allowed[right])}
          <li class="card machine" class:current={view.answering === machine.id} data-id={machine.id}>
            <div class="line">
              <strong>{machine.name}</strong>
              <span class={"state " + machine.state}>{t(("machines.state." + machine.state) as MessageKey)}</span>
              {#if view.answering === machine.id}<span class="badge">{t("machines.answers")}</span>{/if}
              {#if machine.version}<span class="muted">Lutin {machine.version}</span>{/if}
            </div>
            <p class="muted address">{machine.address}</p>
            {#if machine.step}
              <p class="step">{t(("machines.step." + machine.step) as MessageKey)}{#if machine.shutdown_in_s !== null}{" · " + t("machines.shutdown_in", machine.shutdown_in_s)}{/if}</p>
            {/if}
            {#if machine.wake_failed}<p class="error">{t("machines.wake_failed")}</p>{/if}
            {#if machine.detail}<p class="muted">{machine.detail}</p>{/if}
            {#each machine.warnings as warning, index (index)}<p class="warning">{warning}</p>{/each}
            {#if machine.models.length}<p class="muted models-of">{t("machines.models", machine.models.join(", "))}</p>{/if}
            <p class="rights">{granted.length ? t("machines.granted", granted.map(rightName).join(", ")) : t("machines.granted_none")}</p>
            {#if machine.requested.length}<p class="muted">{t("machines.waiting", machine.requested.map(rightName).join(", "))}</p>{/if}

            {#if asking && asking.id === machine.id}
              <div class="confirm" role="group" aria-label={t(("machines." + (asking.what === "unpair" ? "unpair" : "action." + asking.what)) as MessageKey)}>
                <p>{t(("machines.confirm." + asking.what) as MessageKey, machine.name)}</p>
                <div class="actions">
                  <button type="button" class="button primary" disabled={busy} onclick={() => confirmed(machine, asking!.what)}>{t("machines.confirm_yes")}</button>
                  <button type="button" class="button" onclick={() => (asking = null)}>{t("chat.cancel")}</button>
                </div>
              </div>
            {:else}
              <div class="actions">
                {#each actionsOf(machine) as action (action)}
                  <button type="button" class="button" data-action={action} disabled={busy} onclick={() => click(machine, action)}>{t(("machines.action." + action) as MessageKey)}</button>
                {/each}
                {#each rightsToAsk(machine) as right (right)}
                  <button type="button" class="button quiet" data-right={right} disabled={busy} onclick={() => ask(machine, right)}>{t("machines.ask", rightName(right))}</button>
                {/each}
              </div>
            {/if}

            <details>
              <summary>{t("machines.details")}<span class="visually-hidden"> {machine.name}</span></summary>
              <div class="more">
                {#if machine.load?.ram && machine.load.ram.total}<p>{t("machines.load", formatBytes(machine.load.ram.free ?? 0, lang), formatBytes(machine.load.ram.total, lang))}</p>{/if}
                {#if machine.load?.vram && machine.load.vram.total}<p>{t("machines.vram", machine.load.vram.name, formatBytes(machine.load.vram.free ?? 0, lang), formatBytes(machine.load.vram.total, lang))}</p>{/if}
                {#if machine.load?.busy_here}<p>{t("machines.busy")}</p>{/if}
                {#if machine.load?.remote_turns}<p>{t("machines.remote_turns", machine.load.remote_turns)}</p>{/if}
                {#if machine.added}<p class="muted">{t("machines.added", machine.added)}</p>{/if}
                <form class="mac" onsubmit={(event) => saveMac(event, machine)}>
                  <label for={"mac-" + machine.id}>{t("machines.mac")}</label>
                  <div class="row">
                    <input id={"mac-" + machine.id} type="text" autocomplete="off" spellcheck="false" placeholder="00:1A:2B:3C:4D:5E" value={macs[machine.id] ?? machine.mac} oninput={(event) => (macs = { ...macs, [machine.id]: event.currentTarget.value })} />
                    <button type="submit" class="button" disabled={busy}>{t("machines.mac_save")}</button>
                  </div>
                  {#if machine.mac_auto}<p class="help">{t("machines.mac_auto")}</p>{/if}
                </form>
                <div class="actions">
                  {#if machine.shares.skills}<button type="button" class="button" disabled={busy} onclick={() => importFrom(machine, "skills")}>{t("machines.import.skills")}</button>{/if}
                  {#if machine.shares.memory}<button type="button" class="button" disabled={busy} onclick={() => importFrom(machine, "memory")}>{t("machines.import.memory")}</button>{/if}
                  <button type="button" class="button quiet danger unpair" disabled={busy} onclick={() => (asking = { id: machine.id, what: "unpair" })}>{t("machines.unpair")}<span class="visually-hidden"> {machine.name}</span></button>
                </div>
              </div>
            </details>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="pair card" onsubmit={pair} aria-labelledby="machines-pair">
      <h3 id="machines-pair">{t("machines.pair")}</h3>
      <p class="help">{t("machines.pair_help")}</p>
      <div class="fields">
        <div class="field">
          <label for="machine-address">{t("machines.address")}</label>
          <input id="machine-address" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="http://192.168.1.20:8777" bind:value={address} />
        </div>
        <div class="field">
          <label for="machine-code">{t("machines.code")}</label>
          <input id="machine-code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="1234-5678" bind:value={code} />
        </div>
        <div class="field">
          <label for="machine-name">{t("machines.name")}</label>
          <input id="machine-name" type="text" autocomplete="off" bind:value={name} />
        </div>
      </div>
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !address.trim() || !code.trim()}>{t("machines.pair_button")}</button></div>
    </form>

    {#if view.log.length}
      <details class="log">
        <summary>{t("machines.log")}</summary>
        <ul>{#each view.log.slice().reverse() as line, index (index)}<li>{line}</li>{/each}</ul>
      </details>
    {/if}
  {/if}
</section>

<style>
  .machines {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: var(--text-md);
  }

  .muted,
  .help {
    color: var(--color-text-muted);
  }

  .help,
  .muted,
  .intro {
    max-width: var(--measure);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  label {
    font-weight: 600;
  }

  input,
  select {
    width: 100%;
    max-width: 24rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 28rem), 1fr));
    align-items: start;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .card.current {
    border-color: var(--color-accent);
  }

  .line,
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .row input {
    flex: 1 1 12rem;
  }

  .address,
  .models-of {
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
  }

  .state,
  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .state {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .state.operational,
  .badge {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .state.wake_sent,
  .state.reachable {
    background: var(--color-warning-soft);
  }

  .step {
    font-weight: 600;
  }

  .warning {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
    gap: var(--space-3);
  }

  details {
    font-size: var(--text-sm);
  }

  summary {
    min-height: var(--target);
    display: inline-flex;
    align-items: center;
    color: var(--color-accent-text);
    cursor: pointer;
  }

  .more,
  .mac {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .log ul {
    margin: 0;
    padding-left: var(--space-5);
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
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

  .error,
  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
