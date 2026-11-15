<script lang="ts">
  // The language of Lutin: French, English, or the one of the system. The pages read it when they load, so a change loads the page again.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Choice = "fr" | "en" | "auto";
  const CHOICES: readonly Choice[] = ["fr", "en", "auto"];

  let choice = $state<Choice | null>(null);
  let problem = $state("");

  async function choose(next: Choice): Promise<void> {
    try {
      problem = "";
      await api("PATCH", "/language", { language: next });
      choice = next;
      location.reload();
    } catch (cause) {
      problem = cause instanceof ApiError && cause.message ? cause.message : t("error.generic", String(cause));
    }
  }

  onMount(() => {
    void api<{ choice: Choice }>("GET", "/language").then((answer) => (choice = answer.choice)).catch(() => undefined);
  });
</script>

<fieldset class="language">
  <legend>{t("language.title")}</legend>
  {#each CHOICES as option (option)}
    <label class:on={choice === option}>
      <input type="radio" name="language" value={option} checked={choice === option} onchange={() => choose(option)} />
      <span>{t(("language." + option) as "language.fr")}</span>
    </label>
  {/each}
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
</fieldset>

<style>
  .language {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }

  legend {
    margin-bottom: var(--space-2);
    padding: 0;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  label {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    padding: 0 var(--space-4);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    cursor: pointer;
  }

  label.on {
    border-color: var(--color-accent);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-weight: 600;
  }

  input {
    accent-color: var(--color-accent);
  }

  .problem {
    flex-basis: 100%;
    margin: 0;
    color: var(--color-danger);
    font-size: var(--text-sm);
  }
</style>
