<script lang="ts">
  // The Agents screen: what Lutin does by itself. For now, the scheduled tasks: a request carried out at a time of the week, or once on a date, always in the same
  // conversation. Managing them is for the machine itself (the server refuses a paired device and says so). Nothing runs because a form was opened.
  import { onMount } from "svelte";
  import Addons from "../components/Addons.svelte";
  import Connectors from "../components/Connectors.svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";
  import { chosenDays, dayList, dayName, isEveryDay, shownMoment, type ScheduledTask } from "../lib/tasks";

  const lang = language();
  type Tasks = { tasks: ScheduledTask[] };
  type Channels = { channels: { id: string; name: string }[] };

  let data = $state<Tasks | null>(null);
  let problem = $state("");
  let busy = $state(false);
  let deleting = $state("");
  let name = $state("");
  let request = $state("");
  let time = $state("08:00");
  let once = $state(false);
  let date = $state("");
  let checked = $state([true, true, true, true, true, false, false]);
  // The id of the task being changed: the form below then saves it instead of adding a new one.
  let editing = $state("");
  // The channel a finished task writes to (empty: none). The channels are set up in the Settings; a failure to read them only hides the choice.
  let notify = $state("");
  let channels = $state<{ id: string; name: string }[]>([]);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("tasks.not_here");
      return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    }
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
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
      data = await api<Tasks>("GET", "/scheduled-tasks");
    });

  async function reload(): Promise<void> {
    data = await api<Tasks>("GET", "/scheduled-tasks");
  }

  function resetForm(): void {
    editing = "";
    name = "";
    request = "";
    time = "08:00";
    notify = "";
    once = false;
    date = "";
    checked = [true, true, true, true, true, false, false];
  }

  async function create(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await act(async () => {
      // Changing a task sends the whole moment: a weekly task sent with an empty date stops being a one-time one, and the other way round.
      const when = once ? { date, days: [] } : { days: chosenDays(checked), date: "" };
      const body = { name: name.trim(), request: request.trim(), time, notify, ...when };
      if (editing) await api("PATCH", `/scheduled-tasks/${encodeURIComponent(editing)}`, body);
      else await api("POST", "/scheduled-tasks", once ? { name: body.name, request: body.request, time, notify, date } : { name: body.name, request: body.request, time, notify, days: when.days });
      resetForm();
      await reload();
    });
  }

  function edit(task: ScheduledTask): void {
    editing = task.id;
    name = task.name;
    request = task.request;
    time = task.time;
    notify = task.notify;
    once = Boolean(task.date);
    date = task.date;
    checked = [0, 1, 2, 3, 4, 5, 6].map((day) => task.days.includes(day));
    document.getElementById("task-name")?.focus();
  }

  const pause = (task: ScheduledTask): Promise<void> =>
    act(async () => {
      await api("PATCH", `/scheduled-tasks/${encodeURIComponent(task.id)}`, { active: !task.active });
      await reload();
    });

  const run = (task: ScheduledTask): Promise<void> =>
    act(async () => {
      await api("POST", `/scheduled-tasks/${encodeURIComponent(task.id)}/run`, {});
      await reload();
    });

  const stop = (task: ScheduledTask): Promise<void> =>
    act(async () => {
      await api("POST", `/scheduled-tasks/${encodeURIComponent(task.id)}/stop`, {});
      await reload();
    });

  const remove = (task: ScheduledTask): Promise<void> =>
    act(async () => {
      data = await api<Tasks>("DELETE", `/scheduled-tasks/${encodeURIComponent(task.id)}`);
      deleting = "";
      if (editing === task.id) resetForm();
    });

  function when(task: ScheduledTask): string {
    if (task.date) return t("tasks.once", task.date, task.time);
    return t("tasks.weekly", isEveryDay(task.days) ? t("tasks.every_day") : dayList(task.days, lang), task.time);
  }

  onMount(() => {
    void load();
    api<Channels>("GET", "/notification-channels")
      .then((answer) => (channels = answer.channels))
      .catch(() => undefined);
    // A task at work changes state without anyone asking: the list is read again every few seconds while the screen is open.
    const timer = setInterval(() => {
      if (!busy && data) void reload().catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  });
</script>

<div class="agents">
  <header>
    <h1>{t("tasks.title")}</h1>
    <p class="muted">{t("tasks.intro")}</p>
  </header>

  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if data}
    {#if data.tasks.length === 0}
      <p class="empty tasks-empty">{t("tasks.none")}</p>
    {:else}
      <ul class="list tasks" aria-label={t("tasks.title")}>
        {#each data.tasks as task (task.id)}
          <li class="card" class:paused={!task.active}>
            <div class="what">
              <p class="line">
                <strong>{task.name}</strong>
                <span class={"badge " + task.last_state}>{t(("tasks.state." + task.last_state) as MessageKey)}</span>
                {#if !task.active}<span class="badge paused-badge">{t("tasks.paused")}</span>{/if}
              </p>
              <p class="when">{when(task)}{#if task.next_run} · {t("tasks.next", shownMoment(task.next_run))}{/if}</p>
              <p class="request">{task.request}</p>
              {#if task.last_state === "failed" && task.last_error}<p class="warn">{task.last_error}</p>{/if}
              {#if task.history.length}
                <details>
                  <summary>{t("tasks.history")}</summary>
                  <ul class="history">
                    {#each task.history as item, index (index)}
                      <li>{shownMoment(item.at)} · {t(("tasks.state." + item.state) as MessageKey)} · {t("tasks.seconds", item.seconds)}{item.error ? " · " + item.error : ""}</li>
                    {/each}
                  </ul>
                </details>
              {/if}
            </div>
            <div class="actions">
              {#if task.running}
                <button type="button" class="button" disabled={busy} onclick={() => stop(task)}>{t("tasks.stop")}</button>
              {:else}
                <button type="button" class="button primary" disabled={busy} onclick={() => run(task)}>{t("tasks.run")}</button>
              {/if}
              <button type="button" class="button" disabled={busy} onclick={() => edit(task)}>{t("tasks.edit")}</button>
              <button type="button" class="button" disabled={busy} onclick={() => pause(task)}>{task.active ? t("tasks.pause") : t("tasks.resume")}</button>
              {#if deleting === task.id}
                <span class="confirm" role="group" aria-label={t("tasks.delete_confirm", task.name)}>
                  <span>{t("tasks.delete_confirm", task.name)}</span>
                  <button type="button" class="button danger" disabled={busy} onclick={() => remove(task)}>{t("tasks.delete_yes")}</button>
                  <button type="button" class="button" onclick={() => (deleting = "")}>{t("chat.cancel")}</button>
                </span>
              {:else}
                <button type="button" class="button" disabled={busy} onclick={() => (deleting = task.id)}>{t("tasks.delete")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <form class="add" onsubmit={create}>
      <h2>{editing ? t("tasks.edit_title") : t("tasks.add_title")}</h2>
      <label for="task-name">{t("tasks.name")}</label>
      <input id="task-name" type="text" bind:value={name} maxlength="60" autocomplete="off" required />
      <label for="task-request">{t("tasks.request")}</label>
      <textarea id="task-request" rows="3" bind:value={request} maxlength="4000" aria-describedby="task-request-help" required></textarea>
      <p class="muted" id="task-request-help">{t("tasks.request_help")}</p>
      <label for="task-time">{t("tasks.time")}</label>
      <input id="task-time" type="time" bind:value={time} required />
      {#if channels.length}
        <label for="task-notify">{t("tasks.notify")}</label>
        <select id="task-notify" bind:value={notify}>
          <option value="">{t("tasks.notify_none")}</option>
          {#each channels as channel (channel.id)}<option value={channel.id}>{channel.name}</option>{/each}
        </select>
      {/if}
      <fieldset class="when-choice">
        <legend>{t("tasks.when")}</legend>
        <label class="inline"><input type="radio" name="when" checked={!once} onchange={() => (once = false)} /> {t("tasks.weekly_choice")}</label>
        <label class="inline"><input type="radio" name="when" checked={once} onchange={() => (once = true)} /> {t("tasks.once_choice")}</label>
      </fieldset>
      {#if once}
        <label for="task-date">{t("tasks.date")}</label>
        <input id="task-date" type="date" bind:value={date} required />
      {:else}
        <fieldset class="days">
          <legend>{t("tasks.days")}</legend>
          {#each checked as _, day (day)}
            <label class="day" class:on={checked[day]}><input type="checkbox" bind:checked={checked[day]} /> <span>{dayName(day, lang)}</span></label>
          {/each}
        </fieldset>
      {/if}
      <div class="actions">
        <button type="submit" class="button primary" disabled={busy || !name.trim() || !request.trim() || (once ? !date : !checked.some(Boolean))}>{editing ? t("tasks.save") : t("tasks.add")}</button>
        {#if editing}<button type="button" class="button" disabled={busy} onclick={resetForm}>{t("chat.cancel")}</button>{/if}
      </div>
    </form>
  {:else if !problem}
    <p class="muted">{t("tasks.loading")}</p>
  {/if}

  <Addons />

  <Connectors />
</div>

<style>
  .agents {
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

  p {
    margin: 0;
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
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .card.paused {
    opacity: 0.85;
  }

  .what {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
    flex: 1 1 16rem;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .when {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .request {
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }

  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .badge.ok,
  .badge.running {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .badge.failed,
  .badge.interrupted {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }

  .warn,
  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
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

  .history {
    margin: 0;
    padding-left: var(--space-5);
    color: var(--color-text-muted);
  }

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

  .add {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  label {
    font-weight: 600;
  }

  input[type="text"],
  input[type="time"],
  input[type="date"],
  select,
  textarea {
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
  }

  fieldset {
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
    font-weight: 600;
  }

  label.inline,
  label.day {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    font-weight: 400;
    cursor: pointer;
  }

  label.day.on {
    border-color: var(--color-accent);
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  input[type="radio"],
  input[type="checkbox"] {
    accent-color: var(--color-accent);
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
  }
</style>
