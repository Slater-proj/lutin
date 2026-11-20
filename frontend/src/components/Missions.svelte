<script lang="ts">
  // The missions: a long job given to Lutin, carried on by itself in a conversation of its own, in a project. Following one, pausing it, answering its question and stopping it
  // are open to any paired device; starting one (it writes in a project) and deleting one are for the machine itself (the server refuses a paired device and says so).
  import { onDestroy, onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type Mission = {
    id: string;
    name: string;
    brief: string;
    project_path: string;
    hours: number;
    autonomous: boolean;
    state: "running" | "paused" | "blocked" | "done";
    conversation: string;
    turns: number;
    actions: number;
    started_at: number;
    ended_at: number;
    report: string;
    question: string;
    message: string;
    log: string[];
  };
  type Missions = { missions: Mission[] };
  type Projects = { projects: { id: string; name: string; usable: boolean }[]; current: string };

  const HOURS = [1, 2, 4, 8, 12, 24, 48, 72];

  let view = $state<Mission[] | null>(null);
  let projects = $state<{ id: string; name: string }[]>([]);
  let problem = $state("");
  let busy = $state(false);
  let stopping = $state("");
  let deleting = $state("");
  let name = $state("");
  let brief = $state("");
  let project = $state("");
  let hours = $state(8);
  let autonomous = $state(true);
  let answers = $state<Record<string, string>>({});
  let timer: ReturnType<typeof setInterval> | undefined;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("missions.only_here");
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
      view = (await api<Missions>("GET", "/missions")).missions;
    });

  /** The progress is followed while the page is open: a mission moves on by itself. A failed refresh is not shown, the next one tries again. */
  async function follow(): Promise<void> {
    if (busy || !view) return;
    try {
      view = (await api<Missions>("GET", "/missions")).missions;
    } catch {
      /* the next turn of the timer asks again */
    }
  }

  const start = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      await api<Mission>("POST", "/missions", { name: name.trim(), brief: brief.trim(), project, hours, autonomous });
      name = "";
      brief = "";
      view = (await api<Missions>("GET", "/missions")).missions;
    });
  };

  const steer = (mission: Mission, action: "pause" | "resume" | "stop", body: Record<string, unknown> = {}): Promise<void> =>
    act(async () => {
      view = (await api<Missions>("POST", `/missions/${encodeURIComponent(mission.id)}/${action}`, body)).missions;
      stopping = "";
    });

  const reply = (mission: Mission, event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      view = (await api<Missions>("POST", `/missions/${encodeURIComponent(mission.id)}/reply`, { text: (answers[mission.id] ?? "").trim() })).missions;
      answers[mission.id] = "";
    });
  };

  const remove = (mission: Mission): Promise<void> =>
    act(async () => {
      view = (await api<Missions>("DELETE", `/missions/${encodeURIComponent(mission.id)}`)).missions;
      deleting = "";
    });

  onMount(() => {
    void load();
    void api<Projects>("GET", "/projects")
      .then((answer) => {
        projects = answer.projects.filter((entry) => entry.usable);
        project = (answer.projects.find((entry) => entry.id === answer.current && entry.usable) ?? projects[0])?.id ?? "";
      })
      .catch(() => {
        /* without the list, the form cannot start anything: it says so below */
      });
    timer = setInterval(() => void follow(), 5000);
  });
  onDestroy(() => clearInterval(timer));
</script>

<section class="missions" aria-labelledby="missions-title">
  <h2 id="missions-title">{t("missions.title")}</h2>
  <p class="muted">{t("missions.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if view}
    {#if view.length === 0}
      <p class="empty missions-empty">{t("missions.none")}</p>
    {:else}
      <ul class="list" aria-label={t("missions.title")}>
        {#each view as mission (mission.id)}
          <li class="card">
            <div class="line">
              <strong>{mission.name}</strong>
              <span class="badge">{t(("missions.state." + mission.state) as MessageKey)}</span>
              <span class="badge">{mission.autonomous ? t("missions.autonomous") : t("missions.dry")}</span>
            </div>
            <p class="muted">{t("missions.progress", mission.turns, mission.actions, t("opt.hours", mission.hours))}</p>
            <p class="where">{mission.project_path}</p>
            {#if mission.message && mission.state !== "done"}<p class="muted">{mission.message}</p>{/if}
            {#if mission.state === "blocked" && mission.question}
              <form class="question" onsubmit={(event) => reply(mission, event)}>
                <p><strong>{t("missions.asks")}</strong> {mission.question}</p>
                <label for={"mission-answer-" + mission.id}>{t("missions.answer")}</label>
                <textarea id={"mission-answer-" + mission.id} rows="2" bind:value={answers[mission.id]} autocomplete="off"></textarea>
                <div class="actions"><button type="submit" class="button primary" disabled={busy || !(answers[mission.id] ?? "").trim()}>{t("missions.send")}</button></div>
              </form>
            {/if}
            {#if mission.log.length && mission.state !== "done"}
              <details>
                <summary>{t("missions.activity")}</summary>
                <pre>{mission.log.join("\n")}</pre>
              </details>
            {/if}
            {#if mission.report}
              <details open={mission.state === "done"}>
                <summary>{t("missions.report")}</summary>
                <pre>{mission.report}</pre>
              </details>
            {/if}
            <div class="actions">
              {#if mission.state === "running"}<button type="button" class="button" disabled={busy} onclick={() => steer(mission, "pause")}>{t("missions.pause")}</button>{/if}
              {#if mission.state === "paused"}<button type="button" class="button primary" disabled={busy} onclick={() => steer(mission, "resume")}>{t("missions.resume")}</button>{/if}
              {#if mission.state !== "done"}
                {#if stopping === mission.id}
                  <span class="confirm" role="group" aria-label={t("missions.stop_confirm")}>
                    <span>{t("missions.stop_confirm")}</span>
                    <button type="button" class="button danger" disabled={busy} onclick={() => steer(mission, "stop")}>{t("missions.stop_yes")}</button>
                    <button type="button" class="button" onclick={() => (stopping = "")}>{t("chat.cancel")}</button>
                  </span>
                {:else}
                  <button type="button" class="button" disabled={busy} onclick={() => (stopping = mission.id)}>{t("missions.stop")}</button>
                {/if}
              {/if}
              {#if deleting === mission.id}
                <span class="confirm" role="group" aria-label={t("missions.delete_confirm", mission.name)}>
                  <span>{t("missions.delete_confirm", mission.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(mission)}>{t("missions.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (deleting = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (deleting = mission.id)}>{t("missions.delete")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={start}>
      <h3>{t("missions.add_title")}</h3>
      <label for="mission-name">{t("missions.name")}</label>
      <input id="mission-name" type="text" bind:value={name} maxlength="60" autocomplete="off" required />
      <label for="mission-brief">{t("missions.brief")}</label>
      <textarea id="mission-brief" rows="5" bind:value={brief} autocomplete="off" aria-describedby="mission-brief-help" required></textarea>
      <p class="muted" id="mission-brief-help">{t("missions.brief_help")}</p>
      <label for="mission-project">{t("missions.project")}</label>
      <select id="mission-project" bind:value={project} required>
        {#each projects as entry (entry.id)}<option value={entry.id}>{entry.name}</option>{/each}
      </select>
      {#if projects.length === 0}<p class="muted">{t("missions.no_project")}</p>{/if}
      <label for="mission-hours">{t("missions.hours")}</label>
      <select id="mission-hours" bind:value={hours}>
        {#each HOURS as entry (entry)}<option value={entry}>{t("opt.hours", entry)}</option>{/each}
      </select>
      <label class="inline"><input type="checkbox" bind:checked={autonomous} /> {t("missions.autonomous_help")}</label>
      <div class="actions"><button type="submit" class="button primary" disabled={busy || !name.trim() || !brief.trim() || !project}>{t("missions.start")}</button></div>
    </form>
  {:else if !problem}
    <p class="muted">{t("missions.loading")}</p>
  {/if}
</section>

<style>
  .missions {
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

  .card,
  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .question {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .line,
  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .where {
    overflow-wrap: anywhere;
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .empty {
    padding: var(--space-4);
    border: 1px dashed var(--color-border-strong);
    border-radius: var(--radius-lg);
    color: var(--color-text-muted);
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

  pre {
    max-height: 16rem;
    margin: 0;
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  textarea,
  select {
    max-width: 32rem;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font: inherit;
  }

  label.inline {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    font-weight: 400;
    cursor: pointer;
  }

  input[type="checkbox"] {
    accent-color: var(--color-accent);
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
