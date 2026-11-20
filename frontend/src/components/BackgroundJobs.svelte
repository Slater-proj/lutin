<script lang="ts">
  // « Background work » on the Agents screen (docs/modernization/PARITY.md, item 13): a folder of documents, the kinds of files, an instruction applied
  // to each document while nobody talks to Lutin (it gives way as soon as someone writes). A trial stops after the first documents until they are
  // validated. Creating and acting is for this machine; the report of a job is read here.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { percent } from "../lib/format";
  import { t, type MessageKey } from "../lib/messages";

  type Job = { id: string; name: string; folder: string; patterns: string[]; instruction: string; regular: boolean; interval_hours: number; paused: boolean; validated: boolean; state: string; total: number; done: number; failed: number; message: string; has_report: boolean };

  let jobs = $state<Job[] | null>(null);
  let form = $state({ name: "", folder: "", patterns: "*.pdf", instruction: "", regular: false, trial: true });
  let report = $state<{ id: string; text: string } | null>(null);
  let deleting = $state("");
  let busy = $state(false);
  let problem = $state("");
  let timer: ReturnType<typeof setInterval> | undefined;

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const set = (answer: { jobs: Job[] }): void => void (jobs = answer.jobs);
  const add = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      set(await api<{ jobs: Job[] }>("POST", "/background-jobs", form));
      form = { ...form, name: "", instruction: "" };
    });
  };
  const run = (job: Job, action: string): Promise<void> => act(async () => set(await api<{ jobs: Job[] }>("POST", `/background-jobs/${job.id}/${action}`, {})));
  const remove = (job: Job): Promise<void> => act(async () => ((deleting = ""), set(await api<{ jobs: Job[] }>("DELETE", `/background-jobs/${job.id}`))));
  const showReport = (job: Job): Promise<void> => act(async () => void (report = { id: job.id, text: (await api<{ text: string }>("GET", `/background-jobs/${job.id}/report`)).text }));

  onMount(() => {
    api<{ jobs: Job[] }>("GET", "/background-jobs").then(set, (cause) => (problem = explain(cause)));
    timer = setInterval(() => {
      if (jobs?.some((job) => job.state === "running")) api<{ jobs: Job[] }>("GET", "/background-jobs").then(set, () => undefined);
    }, 3000);
    return () => clearInterval(timer);
  });
</script>

<section class="jobs" aria-labelledby="jobs-title">
  <h2 id="jobs-title">{t("jobs.title")}</h2>
  <p class="muted">{t("jobs.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if jobs}
    {#if jobs.length === 0}<p class="muted">{t("jobs.none")}</p>{/if}
    <ul class="cards">
      {#each jobs as job (job.id)}
        {@const share = percent(job.done, job.total)}
        <li class="card">
          <p class="line"><strong>{job.name}</strong><span class="tag">{t(("jobs.state." + job.state) as MessageKey)}</span></p>
          <p class="muted">{job.folder} · {job.patterns.join(", ")}</p>
          <p>{job.instruction}</p>
          {#if job.total}<progress max="100" value={share ?? 0} aria-label={job.name}></progress><p class="muted">{t("jobs.progress", job.done, job.total, job.failed)}</p>{/if}
          {#if job.message}<p class="muted">{job.message}</p>{/if}
          <div class="line">
            {#if job.state === "to_validate"}<button type="button" class="button primary" disabled={busy} onclick={() => run(job, "validate")}>{t("jobs.validate")}</button>{/if}
            {#if job.paused}
              <button type="button" class="button" disabled={busy} onclick={() => run(job, "resume")}>{t("jobs.resume")}</button>
            {:else}
              <button type="button" class="button" disabled={busy} onclick={() => run(job, "pause")}>{t("jobs.pause")}</button>
            {/if}
            <button type="button" class="button" disabled={busy} onclick={() => run(job, "restart")}>{t("jobs.restart")}</button>
            {#if job.has_report || job.done}<button type="button" class="button" disabled={busy} onclick={() => showReport(job)}>{t("jobs.report")}</button>{/if}
            {#if deleting === job.id}
              <span>{t("jobs.delete_confirm")}</span>
              <button type="button" class="button danger" disabled={busy} onclick={() => remove(job)}>{t("upkeep.delete_yes")}</button>
              <button type="button" class="button" onclick={() => (deleting = "")}>{t("chat.cancel")}</button>
            {:else}
              <button type="button" class="button quiet danger" disabled={busy} onclick={() => (deleting = job.id)}>{t("jobs.delete")}<span class="visually-hidden"> {job.name}</span></button>
            {/if}
          </div>
          {#if report?.id === job.id}<pre class="report">{report.text}</pre>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  <form class="card add" onsubmit={add}>
    <h3>{t("jobs.add")}</h3>
    <label>{t("jobs.name")}<input type="text" maxlength="80" bind:value={form.name} /></label>
    <label>{t("jobs.folder")}<input type="text" placeholder="D:/Documents/Factures" bind:value={form.folder} /></label>
    <label>{t("jobs.patterns")}<input type="text" bind:value={form.patterns} /></label>
    <label>{t("jobs.instruction")}<textarea rows="3" maxlength="4000" bind:value={form.instruction}></textarea></label>
    <label class="check"><input type="checkbox" bind:checked={form.trial} /> {t("jobs.trial")}</label>
    <label class="check"><input type="checkbox" bind:checked={form.regular} /> {t("jobs.regular")}</label>
    <div class="line"><button type="submit" class="button primary" disabled={busy || !form.name.trim() || !form.folder.trim() || !form.instruction.trim()}>{t("jobs.create")}</button></div>
  </form>
</section>

<style>
  .jobs,
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .jobs {
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
    font-size: var(--text-md, 1rem);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .problem {
    color: var(--color-danger);
  }

  .cards {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .card {
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    overflow-wrap: anywhere;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .tag {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--color-surface-raised);
    font-size: var(--text-xs);
    font-weight: 600;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 36rem;
  }

  label.check {
    flex-direction: row;
    align-items: center;
  }

  .report {
    margin: 0;
    padding: var(--space-2);
    max-height: 20rem;
    position: relative; /* the positioned texts inside (hidden for the eyes) scroll with it, never lengthen an outer area */
    overflow: auto;
    border-radius: var(--radius-md);
    background: var(--color-code-bg);
    font-size: var(--text-sm);
    white-space: pre-wrap;
  }
</style>
