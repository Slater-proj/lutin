<script lang="ts">
  // The skills: sheets of your own saying how you want something done. The model sees only the title and the « read when… » line of each, and opens a sheet when it needs it.
  // Adding, changing and deleting are for the machine itself (the server refuses a paired device and says so).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Skill = { name: string; title: string; read_when: string };

  let skills = $state<Skill[] | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let deleting = $state("");
  // The sheet being changed (empty: a new one is being written). A new sheet needs a name; a name cannot be changed afterwards.
  let editing = $state("");
  let name = $state("");
  let text = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("skills.only_here");
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

  const sheet = (skill: string): string => `/skills/${encodeURIComponent(skill)}`;

  function reset(): void {
    editing = "";
    name = "";
    text = "";
  }

  const load = (): Promise<void> =>
    act(async () => {
      skills = (await api<{ skills: Skill[] }>("GET", "/skills")).skills;
    });

  const edit = (skill: Skill): Promise<void> =>
    act(async () => {
      text = (await api<{ text: string }>("GET", sheet(skill.name))).text;
      editing = skill.name;
      name = skill.name;
    });

  const save = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      if (editing) await api("PATCH", sheet(editing), { text });
      else await api("POST", "/skills", { name: name.trim(), text });
      skills = (await api<{ skills: Skill[] }>("GET", "/skills")).skills;
      reset();
    });
  };

  const remove = (skill: Skill): Promise<void> =>
    act(async () => {
      skills = (await api<{ skills: Skill[] }>("DELETE", sheet(skill.name))).skills;
      deleting = "";
      if (editing === skill.name) reset();
    });

  onMount(() => {
    void load();
  });
</script>

<section class="skills" aria-labelledby="skills-title">
  <h2 id="skills-title">{t("skills.title")}</h2>
  <p class="muted">{t("skills.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if skills}
    {#if skills.length === 0}
      <p class="empty skills-empty">{t("skills.none")}</p>
    {:else}
      <ul class="list" aria-label={t("skills.title")}>
        {#each skills as skill (skill.name)}
          <li class="item">
            <div class="line">
              <strong>{skill.title}</strong>
              <span class="muted">{skill.name}</span>
            </div>
            {#if skill.read_when}<p class="muted">{t("skills.read_when", skill.read_when)}</p>{/if}
            <div class="actions">
              <button type="button" class="button" disabled={busy} onclick={() => edit(skill)}>{t("skills.edit")}</button>
              {#if deleting === skill.name}
                <span class="confirm" role="group" aria-label={t("skills.delete_confirm", skill.name)}>
                  <span>{t("skills.delete_confirm", skill.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(skill)}>{t("skills.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (deleting = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (deleting = skill.name)}>{t("skills.delete")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={save}>
      <h3>{editing ? t("skills.edit_title", editing) : t("skills.add_title")}</h3>
      {#if !editing}
        <label for="skill-name">{t("skills.name")}</label>
        <input id="skill-name" type="text" bind:value={name} maxlength="99" autocomplete="off" spellcheck="false" placeholder="my-notes.md" aria-describedby="skill-name-help" required />
        <p class="muted" id="skill-name-help">{t("skills.name_help")}</p>
      {/if}
      <label for="skill-text">{t("skills.text")}</label>
      <textarea id="skill-text" rows="8" maxlength="60000" bind:value={text} aria-describedby="skill-text-help"></textarea>
      <p class="muted" id="skill-text-help">{t("skills.text_help")}</p>
      <div class="actions">
        <button type="submit" class="button primary" disabled={busy || !text.trim() || (!editing && !name.trim())}>{editing ? t("skills.save") : t("skills.add")}</button>
        {#if editing}<button type="button" class="button" onclick={reset}>{t("chat.cancel")}</button>{/if}
      </div>
    </form>
  {:else if !problem}
    <p class="muted">{t("skills.loading")}</p>
  {/if}
</section>

<style>
  .skills {
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

  .item,
  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .line,
  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .empty {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-lg);
    color: var(--color-text-muted);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  textarea {
    max-width: 40rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
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
