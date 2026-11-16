<script lang="ts">
  // The Settings screen: every setting of /api/v1/settings in groups, each kept as soon as it is changed. What the person typed is checked here first
  // (a number, its range); the server checks again and has the last word, and what it answers is what is shown.
  import { onMount } from "svelte";
  import ApprovalRules from "../components/ApprovalRules.svelte";
  import Devices from "../components/Devices.svelte";
  import Memory from "../components/Memory.svelte";
  import Skills from "../components/Skills.svelte";
  import ThirdPartySkills from "../components/ThirdPartySkills.svelte";
  import Notifications from "../components/Notifications.svelte";
  import LanguageChoice from "../components/LanguageChoice.svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";
  import { fieldsOf, GROUPS, parseTyped, shown, type Field, type Value } from "../lib/settings";

  let values = $state<Record<string, Value> | null>(null);
  let problem = $state("");
  let errors = $state<Record<string, string>>({});
  let saved = $state("");
  let timer: ReturnType<typeof setTimeout> | undefined;

  const label = (field: Field): string => t(("settings.f." + field.name) as MessageKey);
  const help = (field: Field): string => t(("settings.h." + field.name) as MessageKey);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function load(): Promise<void> {
    try {
      problem = "";
      values = await api<Record<string, Value>>("GET", "/settings");
    } catch (cause) {
      problem = explain(cause);
    }
  }

  async function save(field: Field, value: Value): Promise<void> {
    try {
      problem = "";
      errors = { ...errors, [field.name]: "" };
      values = await api<Record<string, Value>>("PATCH", "/settings", { [field.name]: value });
      saved = label(field);
      clearTimeout(timer);
      timer = setTimeout(() => (saved = ""), 2500);
    } catch (cause) {
      errors = { ...errors, [field.name]: explain(cause) };
      await load(); // what the server holds is what is shown again
    }
  }

  function typed(field: Field, event: Event): void {
    const box = event.currentTarget as HTMLInputElement | HTMLTextAreaElement;
    const result = parseTyped(field, box.value);
    if (!result.ok) {
      errors = { ...errors, [field.name]: t(("settings.error_" + result.error) as MessageKey) };
      return;
    }
    void save(field, result.value);
  }

  onMount(() => {
    void load();
    return () => clearTimeout(timer);
  });
</script>

{#snippet control(field: Field)}
  {@const id = "setting-" + field.name}
  {#if field.kind === "boolean"}
    <input {id} type="checkbox" role="switch" checked={values?.[field.name] === true} onchange={(event) => save(field, event.currentTarget.checked)} aria-describedby={id + "-help"} />
  {:else if field.kind === "select"}
    <select {id} onchange={(event) => save(field, event.currentTarget.value)} aria-describedby={id + "-help"}>
      {#each field.options ?? [] as option (option)}
        <option value={option} selected={values?.[field.name] === option}>{t(("settings.o." + field.name + "." + option) as MessageKey)}</option>
      {/each}
    </select>
  {:else if field.kind === "strings"}
    <textarea {id} rows="3" value={shown(field, values?.[field.name])} onchange={(event) => typed(field, event)} aria-describedby={id + "-help"}></textarea>
  {:else if field.kind === "text"}
    <input {id} type="text" value={shown(field, values?.[field.name])} onchange={(event) => typed(field, event)} aria-describedby={id + "-help"} />
  {:else}
    <input
      {id}
      type="number"
      inputmode="decimal"
      min={field.min}
      max={field.max}
      step={field.step ?? 1}
      placeholder={field.nullable ? t("settings.empty_auto") : undefined}
      value={shown(field, values?.[field.name])}
      onchange={(event) => typed(field, event)}
      aria-describedby={id + "-help"}
    />
  {/if}
{/snippet}

{#snippet row(field: Field)}
  <div class="row" class:risky={field.risky} class:switch={field.kind === "boolean"}>
    <label for={"setting-" + field.name}>{label(field)}{#if field.risky}<span class="care">{t("settings.risky")}</span>{/if}</label>
    {@render control(field)}
    <p class="help" id={"setting-" + field.name + "-help"}>
      {help(field)}{#if field.min !== undefined && field.max !== undefined && (field.kind === "number" || field.kind === "integer")} {t("settings.range", field.min, field.max)}.{/if}
    </p>
    {#if errors[field.name]}<p class="error" role="alert">{errors[field.name]}</p>{/if}
  </div>
{/snippet}

<div class="settings">
  <header>
    <h1>{t("settings.title")}</h1>
    <p class="muted">{t("settings.intro")}</p>
    <p class="saved" role="status">{#if saved}✓ {t("settings.saved")} · {saved}{/if}</p>
  </header>

  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if !values}
    {#if !problem}<p class="muted">{t("settings.loading")}</p>{/if}
  {:else}
    <section class="group" aria-labelledby="g-language">
      <h2 id="g-language">{t("settings.language")}</h2>
      <LanguageChoice />
    </section>

    <div class="group"><Devices /></div>
    <div class="group"><ApprovalRules /></div>
    <div class="group"><Notifications /></div>
    <div class="group"><Memory /></div>
    <div class="group"><Skills /></div>
    <div class="group"><ThirdPartySkills /></div>

    {#each GROUPS as group (group)}
      {#if group === "sampling"}
        <details class="group">
          <summary><h2 id={"g-" + group}>{t(("settings.g." + group) as MessageKey)}</h2></summary>
          <p class="muted">{t(("settings.gh." + group) as MessageKey)}</p>
          {#each fieldsOf(group) as field (field.name)}{@render row(field)}{/each}
        </details>
      {:else}
        <section class="group" aria-labelledby={"g-" + group}>
          <h2 id={"g-" + group}>{t(("settings.g." + group) as MessageKey)}</h2>
          <p class="muted">{t(("settings.gh." + group) as MessageKey)}</p>
          {#each fieldsOf(group) as field (field.name)}{@render row(field)}{/each}
        </section>
      {/if}
    {/each}
  {/if}
</div>

<style>
  .settings {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    max-width: var(--measure);
    margin: 0 auto;
    padding: var(--space-5) var(--space-4) var(--space-6);
  }

  h1 {
    margin: 0;
    font-size: var(--text-xl);
  }

  h2 {
    margin: 0;
    font-size: var(--text-lg);
  }

  header p,
  .group > p {
    margin: 0;
  }

  .muted,
  .help {
    color: var(--color-text-muted);
  }

  .saved {
    min-height: 1.5em;
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  summary {
    display: flex;
    align-items: center;
    min-height: var(--target);
    cursor: pointer;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--space-1);
    padding-top: var(--space-3);
    border-top: 1px solid var(--color-border);
  }

  .row.switch {
    grid-template-columns: 1fr auto;
    align-items: center;
    column-gap: var(--space-3);
  }

  .row.switch .help,
  .row.switch .error {
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

  input[type="number"],
  input[type="text"],
  select,
  textarea {
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

  textarea {
    max-width: 100%;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }

  input[type="checkbox"] {
    inline-size: 2.75rem;
    block-size: 1.5rem;
    accent-color: var(--color-accent);
  }

  .help,
  .error {
    margin: 0;
    font-size: var(--text-sm);
  }

  .error,
  .problem {
    color: var(--color-danger);
  }
</style>
