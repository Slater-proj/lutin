<script lang="ts">
  // The two notes the model always has in front of it: the context (who you are, what you work on) and the memory (what to remember). Plain text, kept when you press the button.
  // Writing them is for the machine itself (the server refuses a paired device and says so).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Notes = { context: string; memory: string };

  let notes = $state<Notes | null>(null);
  let context = $state("");
  let memory = $state("");
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("memory.only_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      problem = "";
      done = "";
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  function show(answer: Notes): void {
    notes = answer;
    context = answer.context;
    memory = answer.memory;
  }

  const load = (): Promise<void> => act(async () => show(await api<Notes>("GET", "/memory")));

  const save = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      show(await api<Notes>("PATCH", "/memory", { context, memory }));
      done = t("memory.saved");
    });
  };

  onMount(() => {
    void load();
  });
</script>

<section class="memory" aria-labelledby="memory-title">
  <h2 id="memory-title">{t("memory.title")}</h2>
  <p class="muted">{t("memory.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}
  {#if notes}
    <form onsubmit={save}>
      <label for="memory-context">{t("memory.context")}</label>
      <textarea id="memory-context" rows="5" maxlength="60000" bind:value={context} aria-describedby="memory-context-help"></textarea>
      <p class="muted" id="memory-context-help">{t("memory.context_help")}</p>
      <label for="memory-notes">{t("memory.memory")}</label>
      <textarea id="memory-notes" rows="5" maxlength="60000" bind:value={memory} aria-describedby="memory-notes-help"></textarea>
      <p class="muted" id="memory-notes-help">{t("memory.memory_help")}</p>
      <div class="actions"><button type="submit" class="button primary" disabled={busy || (context === notes.context && memory === notes.memory)}>{t("memory.save")}</button></div>
    </form>
  {:else if !problem}
    <p class="muted">{t("memory.loading")}</p>
  {/if}
</section>

<style>
  .memory,
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
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

  label {
    font-weight: 600;
  }

  textarea {
    max-width: 40rem;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .done {
    color: var(--color-accent-text);
    font-size: var(--text-sm);
  }
</style>
