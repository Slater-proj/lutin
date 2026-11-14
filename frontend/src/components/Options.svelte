<script lang="ts">
  // The options of one conversation, beside the field: how it answers (mode, reasoning, web) and what it may do without asking.
  // The two automatic approvals are never inherited from the settings of the machine: they are off until ticked here, for this conversation only.
  import Icon from "./Icon.svelte";
  import { t, type MessageKey } from "../lib/messages";
  import type { ConversationOptions } from "../lib/types";

  let { options, onchange }: { options: ConversationOptions; onchange: (patch: Partial<ConversationOptions>) => void } = $props();

  const MODES = ["general", "technical", "scenario", "research", "chat", "mission"] as const;
  const HOURS = [1, 2, 4, 8, 12, 24, 48, 72];
  let open = $state(false);

  const automatic = $derived([options.auto_approve_writes ? t("opt.auto_writes_short") : "", options.auto_approve_commands ? t("opt.auto_commands_short") : ""].filter(Boolean));

  function tick(key: "thinking" | "web" | "dry_run" | "auto_approve_writes" | "auto_approve_commands", event: Event): void {
    onchange({ [key]: (event.currentTarget as HTMLInputElement).checked });
  }
</script>

<div class="bar">
  <button type="button" class="toggle" aria-expanded={open} aria-controls="options-panel" onclick={() => (open = !open)}>
    <Icon name="settings" size={16} /><span>{t("opt.title")}</span><span class="mode">{t(("opt.mode." + options.mode) as MessageKey)}</span>
  </button>
  {#if automatic.length}<span class="auto" role="status">{t("opt.auto_on", automatic.join(", "))}</span>{/if}
  {#if options.dry_run}<span class="auto dry">{t("opt.dry_run_on")}</span>{/if}
</div>

{#if open}
  <div class="panel" id="options-panel" role="group" aria-label={t("opt.title")}>
    <label class="field">
      <span>{t("opt.mode")}</span>
      <select value={options.mode} onchange={(event) => onchange({ mode: event.currentTarget.value as ConversationOptions["mode"] })}>
        {#each MODES as mode (mode)}<option value={mode}>{t(("opt.mode." + mode) as MessageKey)}</option>{/each}
      </select>
      <small>{t(("opt.mode_help." + options.mode) as MessageKey)}</small>
    </label>

    {#if options.mode === "mission"}
      <label class="field">
        <span>{t("opt.mission_hours")}</span>
        <select value={options.mission_hours} onchange={(event) => onchange({ mission_hours: Number(event.currentTarget.value) })}>
          {#each HOURS as hours (hours)}<option value={hours}>{t("opt.hours", hours)}</option>{/each}
        </select>
      </label>
    {/if}

    <div class="switches">
      <label><input type="checkbox" checked={options.thinking} onchange={(event) => tick("thinking", event)} /><span>{t("opt.thinking")}</span></label>
      <label><input type="checkbox" checked={options.web} onchange={(event) => tick("web", event)} /><span>{t("opt.web")}</span></label>
      <label>
        <input type="checkbox" checked={options.dry_run} onchange={(event) => tick("dry_run", event)} />
        <span>{t("opt.dry_run")}<small>{t("opt.dry_run_help")}</small></span>
      </label>
    </div>

    <fieldset class="approvals">
      <legend>{t("opt.approvals")}</legend>
      <p>{t("opt.approvals_help")}</p>
      <label><input type="checkbox" checked={options.auto_approve_writes} onchange={(event) => tick("auto_approve_writes", event)} /><span>{t("opt.auto_writes")}<small>{t("opt.auto_writes_help")}</small></span></label>
      <label>
        <input type="checkbox" checked={options.auto_approve_commands} onchange={(event) => tick("auto_approve_commands", event)} />
        <span>{t("opt.auto_commands")}<small>{t("opt.auto_commands_help")}</small></span>
      </label>
    </fieldset>
  </div>
{/if}

<style>
  .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 2.25rem;
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    cursor: pointer;
  }

  .toggle:hover,
  .toggle[aria-expanded="true"] {
    border-color: var(--color-accent);
    color: var(--color-text);
  }

  .mode {
    padding-left: var(--space-2);
    border-left: 1px solid var(--color-border);
    color: var(--color-accent-text);
    font-weight: 600;
  }

  .auto {
    padding: 0.2rem var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--color-warning-soft);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .panel {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
    align-items: start;
    gap: var(--space-3) var(--space-5);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: var(--shadow-raised);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--text-sm);
    font-weight: 600;
  }

  .field select {
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-weight: 400;
  }

  small {
    display: block;
    color: var(--color-text-muted);
    font-size: var(--text-xs);
    font-weight: 400;
  }

  .switches,
  .approvals {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }

  label:has(> input[type="checkbox"]) {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-1) 0;
    font-size: var(--text-sm);
    cursor: pointer;
  }

  input[type="checkbox"] {
    flex: none;
    width: 1.25rem;
    height: 1.25rem;
    margin-top: 0.1rem;
    accent-color: var(--color-accent);
  }

  .approvals {
    grid-column: 1 / -1;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
  }

  legend {
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
    font-weight: 650;
  }

  .approvals p {
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }
</style>
