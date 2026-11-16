<script lang="ts">
  // The add-ons: what connects Lutin to a service (mail, Telegram, X, ComfyUI, a voice studio). Each one describes itself, so this page only draws what it is told: the steps to
  // follow, the settings to fill, the hosts it will talk to. An add-on is off until it is set up and its check succeeds. A secret is typed once and never shown again: the
  // page only says that it is set (leave the box empty to keep it). Setting up and starting are for the machine itself (the server refuses a paired device and says so).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import AddonFlow from "./AddonFlow.svelte";
  import AddonPanel from "./AddonPanel.svelte";
  import { t } from "../lib/messages";

  type Choice = { value: string; label: string };
  type Setting = { key: string; secret: boolean; multiline: boolean; label: string; help: string; default: string; choices: Choice[] | null; value?: string; set?: boolean };
  type Check = { ok: boolean; at: number; steps: { call: string; ok: boolean; message: string }[] };
  type Addon = {
    id: string;
    name: string;
    description: string;
    doc: string;
    hosts: string[];
    steps: { title: string; text: string }[];
    settings: Setting[];
    missing: string[];
    active: boolean;
    state: string;
    check: Check | null;
  };
  type View = { addons: Addon[]; alerts: { id: string; name: string }[] };

  // The add-ons that have a live panel here (the others, ComfyUI for now, are set up above and used from the chat).
  const PANELS = ["telegram", "mail", "x"];

  let view = $state<View | null>(null);
  let problem = $state("");
  let busy = $state(false);
  // What is being typed, per add-on and per setting. Only what was touched is sent.
  let typed = $state<Record<string, Record<string, string>>>({});

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("addons.only_here");
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

  const shown = (addon: Addon, setting: Setting): string => typed[addon.id]?.[setting.key] ?? setting.value ?? "";

  function type(addon: Addon, setting: Setting, value: string): void {
    typed[addon.id] = { ...typed[addon.id], [setting.key]: value };
  }

  const load = (): Promise<void> =>
    act(async () => {
      view = await api<View>("GET", "/addons");
    });

  const save = (addon: Addon): Promise<void> =>
    act(async () => {
      const settings = typed[addon.id] ?? {};
      if (Object.keys(settings).length) view = await api<View>("PATCH", `/addons/${encodeURIComponent(addon.id)}`, { settings });
      typed[addon.id] = {};
    });

  const check = (addon: Addon): Promise<void> =>
    act(async () => {
      await api("POST", `/addons/${encodeURIComponent(addon.id)}/check`, {});
      view = await api<View>("GET", "/addons");
    });

  const switchTo = (addon: Addon, active: boolean): Promise<void> =>
    act(async () => {
      const settings = typed[addon.id] ?? {};
      // What was typed is saved first, so that starting checks what is on the screen.
      view = await api<View>("PATCH", `/addons/${encodeURIComponent(addon.id)}`, Object.keys(settings).length ? { settings, active } : { active });
      typed[addon.id] = {};
    });

  const moment = (seconds: number): string => new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  onMount(() => {
    void load();
  });
</script>

<section class="addons" aria-labelledby="addons-title">
  <h2 id="addons-title">{t("addons.title")}</h2>
  <p class="muted">{t("addons.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if view}
    {#each view.alerts as alert (alert.id)}<p class="warn" role="status">{t("addons.alert", alert.name)}</p>{/each}
    <ul class="list" aria-label={t("addons.title")}>
      {#each view.addons as addon (addon.id)}
        <li class="card">
          <div class="line">
            <strong>{addon.name}</strong>
            <span class={"badge" + (addon.active ? " on" : "")}>{addon.active ? t("addons.on") : t("addons.off")}</span>
          </div>
          <p>{addon.description}</p>
          {#if addon.hosts.length}<p class="muted">{t("addons.hosts", addon.hosts.join(", "))}</p>{/if}

          {#if addon.steps.length}
            <details>
              <summary>{t("addons.steps")}</summary>
              <ol class="steps">
                {#each addon.steps as step, index (index)}<li><strong>{step.title}</strong> {step.text}</li>{/each}
              </ol>
            </details>
          {/if}

          {#if addon.settings.length}
            <form class="settings" onsubmit={(event) => { event.preventDefault(); void save(addon); }}>
              {#each addon.settings as setting (setting.key)}
                {@const id = `addon-${addon.id}-${setting.key}`}
                <label for={id}>{setting.label}</label>
                {#if setting.choices}
                  <select {id} value={shown(addon, setting)} onchange={(event) => type(addon, setting, event.currentTarget.value)} aria-describedby={setting.help ? id + "-help" : undefined}>
                    {#each setting.choices as choice (choice.value)}<option value={choice.value}>{choice.label}</option>{/each}
                  </select>
                {:else if setting.multiline}
                  <textarea {id} rows="3" value={shown(addon, setting)} oninput={(event) => type(addon, setting, event.currentTarget.value)} aria-describedby={setting.help ? id + "-help" : undefined}></textarea>
                {:else}
                  <input
                    {id}
                    type={setting.secret ? "password" : "text"}
                    value={setting.secret ? (typed[addon.id]?.[setting.key] ?? "") : shown(addon, setting)}
                    placeholder={setting.secret && setting.set ? t("addons.secret_kept") : ""}
                    autocomplete="off"
                    spellcheck="false"
                    oninput={(event) => type(addon, setting, event.currentTarget.value)}
                    aria-describedby={setting.help ? id + "-help" : undefined}
                  />
                {/if}
                {#if setting.help}<p class="muted" id={id + "-help"}>{setting.help}</p>{/if}
              {/each}
              <div class="actions"><button type="submit" class="button" disabled={busy || !Object.keys(typed[addon.id] ?? {}).length}>{t("addons.save")}</button></div>
            </form>
          {/if}

          {#if addon.missing.length && !addon.active}<p class="muted">{t("addons.missing", addon.missing.join(", "))}</p>{/if}
          {#if addon.check}
            <div class="check" role="status">
              <p class={addon.check.ok ? "done" : "warn"}>{addon.check.ok ? t("addons.check_ok", moment(addon.check.at)) : t("addons.check_failed", moment(addon.check.at))}</p>
              <ul>
                {#each addon.check.steps as step, index (index)}<li class={step.ok ? "" : "warn"}>{step.ok ? "✓" : "✗"} {step.call} {step.message}</li>{/each}
              </ul>
            </div>
          {/if}

          {#if addon.active && PANELS.includes(addon.id)}<AddonPanel id={addon.id} />{/if}

          <AddonFlow id={addon.id} check={addon.check} />

          <div class="actions">
            {#if addon.active}
              <button type="button" class="button" disabled={busy} onclick={() => switchTo(addon, false)}>{t("addons.stop")}</button>
            {:else}
              <button type="button" class="button primary" disabled={busy} onclick={() => switchTo(addon, true)}>{t("addons.start")}</button>
            {/if}
            <button type="button" class="button" disabled={busy} onclick={() => check(addon)}>{t("addons.check")}</button>
          </div>
        </li>
      {/each}
    </ul>
  {:else if !problem}
    <p class="muted">{t("addons.loading")}</p>
  {/if}
</section>

<style>
  .addons {
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

  .line,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
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
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
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

  .steps {
    margin: 0;
    padding-left: var(--space-5);
  }

  .settings {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  label {
    font-weight: 600;
  }

  input,
  select,
  textarea {
    max-width: 32rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .check ul {
    margin: 0;
    padding-left: var(--space-5);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
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
