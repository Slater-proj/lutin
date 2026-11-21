<script lang="ts">
  // The paired devices (a phone, another computer) and the pairing of a new one. The code is asked from the machine itself: the server gives it to nobody else,
  // and this component only shows it. A device is removed with a confirmation; it must then be paired again.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t } from "../lib/messages";
  import { qrPath } from "../lib/qr";

  type Device = { id: string; name: string; paired_at: number; seen_at: number };
  type View = { devices: Device[]; level: "local" | "network" | "proxy"; pairing_possible: boolean; address: string };
  type Code = { code: string; valid_seconds: number; address: string; qr: { size: number; rows: string[] } };

  let { compact = false }: { compact?: boolean } = $props(); // compact: the first launch shows the pairing only, not the list

  const lang = language();
  let view = $state<View | null>(null);
  let code = $state<Code | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let removing = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "local_only" && cause.status === 403) return t("devices.only_here");
      if (cause.code === "configurator") return t("devices.only_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
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

  const load = (): Promise<void> =>
    act(async () => {
      view = await api<View>("GET", "/devices");
    });

  const pair = (): Promise<void> =>
    act(async () => {
      code = await api<Code>("POST", "/devices/pairing-code", {});
    });

  const remove = (device: Device): Promise<void> =>
    act(async () => {
      view = await api<View>("DELETE", `/devices/${encodeURIComponent(device.id)}`);
      removing = "";
    });

  const removeAll = (): Promise<void> =>
    act(async () => {
      view = await api<View>("DELETE", "/devices");
      removing = "";
    });

  const seen = (seconds: number): string => new Date(seconds * 1000).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" });

  onMount(() => {
    void load();
  });
</script>

<section class="devices" aria-labelledby="devices-title">
  <h2 id="devices-title">{compact ? t("devices.pair_title") : t("devices.title")}</h2>
  <p class="muted">{t("devices.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if view}
    {#if !compact}
      {#if view.devices.length === 0}
        <p class="muted">{t("devices.none")}</p>
      {:else}
        <ul class="list">
          {#each view.devices as device (device.id)}
            <li>
              <span class="what"><strong>{device.name}</strong> <span class="muted">{t("devices.seen", seen(device.seen_at))}</span></span>
              {#if removing === device.id}
                <span class="confirm" role="group" aria-label={t("devices.remove_confirm", device.name)}>
                  <span>{t("devices.remove_confirm", device.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(device)}>{t("devices.remove_yes")}</button>
                  <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (removing = device.id)}>{t("devices.remove")}</button>
              {/if}
            </li>
          {/each}
        </ul>
        {#if removing === "*"}
          <p class="confirm" role="group" aria-label={t("devices.remove_all")}>
            <span>{t("devices.remove_all_confirm", view.devices.length)}</span>
            <button type="button" class="button danger" disabled={busy} onclick={removeAll}>{t("devices.remove_all_yes")}</button>
            <button type="button" class="button" onclick={() => (removing = "")}>{t("chat.cancel")}</button>
          </p>
        {:else}
          <div class="actions"><button type="button" class="button" disabled={busy} onclick={() => (removing = "*")}>{t("devices.remove_all")}</button></div>
        {/if}
      {/if}
    {/if}

    {#if !view.pairing_possible}
      <p class="note">{t("devices.local_level")} <a href="#/settings/devices" onclick={() => document.getElementById("access-title")?.focus()}>{t("devices.open_access")}</a></p>
    {:else if code}
      <div class="code" role="status">
        <svg class="qr" viewBox={`0 0 ${code.qr.size + 8} ${code.qr.size + 8}`} role="img" aria-label={t("devices.qr_label", code.address)}>
          <rect width={code.qr.size + 8} height={code.qr.size + 8} fill="#ffffff" />
          <path d={qrPath(code.qr.rows, 4)} fill="#000000" />
        </svg>
        <div class="steps">
          <p>{t("devices.step_open")}</p>
          <p class="address">{code.address}</p>
          <p>{t("devices.step_code")}</p>
          <p class="digits">{code.code}</p>
          <p class="muted">{t("devices.valid", Math.round(code.valid_seconds / 60))}</p>
          <div class="actions"><button type="button" class="button" disabled={busy} onclick={pair}>{t("devices.new_code")}</button></div>
        </div>
      </div>
    {:else}
      <div class="actions"><button type="button" class="button primary" disabled={busy} onclick={pair}>{t("devices.pair")}</button></div>
    {/if}
  {/if}
</section>

<style>
  .devices {
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
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .list li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }

  .what {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .confirm,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .note {
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  .note a {
    color: var(--color-text);
    font-weight: 600;
  }

  .code {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: var(--space-4);
  }

  .qr {
    width: 11rem;
    height: 11rem;
    border-radius: var(--radius-md);
  }

  .steps {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .address {
    overflow-wrap: anywhere;
    font-family: var(--font-mono);
    font-weight: 600;
  }

  .digits {
    font-family: var(--font-mono);
    font-size: var(--text-xl);
    font-weight: 700;
    letter-spacing: 0.2em;
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
