<script lang="ts">
  // The guided choice of a model: the machine in plain words, what the person wants to do, one recommended model with a verdict for THIS machine,
  // and a confirmation that shows the size before anything is downloaded. The verdicts come from the server; this only says them and refuses what they refuse.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { blocker, choices, freeAfter, splitFit, USES, type Choice, type Machine, type Recommendation, type Use } from "../lib/guide";
  import { formatBytes } from "../lib/format";
  import { language, t, type MessageKey } from "../lib/messages";

  let { onstarted, onuse }: { onstarted: () => void; onuse: (model: string) => void } = $props();

  const lang = language();
  const gb = (value: number): string => formatBytes(Math.round(value * 1e9), lang);

  let machine = $state<Machine | null>(null);
  let machineFailed = $state(false);
  let use = $state<Use>("unsure");
  let recommendation = $state<Recommendation | null>(null);
  let selectedId = $state("");
  let confirming = $state(false);
  let started = $state("");
  let problem = $state("");
  let busy = $state(false);
  let alive = true;

  const list = $derived(recommendation ? choices(recommendation) : []);
  const selected = $derived(list.find((item) => item.model.id === selectedId) ?? list[0] ?? null);
  const stop = $derived(selected && recommendation ? blocker(selected, recommendation) : null);
  const left = $derived(selected && recommendation ? freeAfter(selected, recommendation) : null);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

  async function detect(): Promise<void> {
    // The detection starts programs: the server answers at once and the page asks again, for 30 seconds at most.
    for (let attempt = 0; attempt < 20 && alive; attempt += 1) {
      machine = await api<Machine>("GET", "/machine");
      if (machine.detected) return;
      await wait(1500);
    }
    machineFailed = true;
  }

  async function recommend(wanted: Use): Promise<void> {
    use = wanted;
    confirming = false;
    started = "";
    try {
      problem = "";
      const answer = await api<Recommendation>("GET", "/models/recommendation?use=" + wanted);
      if (!alive || use !== wanted) return;
      recommendation = answer;
      selectedId = answer.recommended?.model.id ?? "";
    } catch (cause) {
      problem = explain(cause);
    }
  }

  async function begin(): Promise<void> {
    if (!selected || busy) return;
    busy = true;
    try {
      problem = "";
      await api("POST", "/models", { name: selected.model.id });
      started = selected.model.id;
      confirming = false;
      onstarted();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  onMount(() => {
    void (async () => {
      try {
        await detect();
        if (machine?.detected) await recommend(use);
      } catch (cause) {
        problem = explain(cause);
      }
    })();
    return () => {
      alive = false;
    };
  });

  function pick(choice: Choice): void {
    selectedId = choice.model.id;
    confirming = false;
    started = "";
  }
</script>

<section class="guide" aria-labelledby="guide-title">
  <h2 id="guide-title">{t("guide.title")}</h2>

  <div class="machine" aria-live="polite">
    {#if machine?.detected}
      <p class="muted">{t("guide.machine")}</p>
      <p class="summary">{machine.summary}</p>
    {:else if machineFailed}
      <p class="warn">{t("guide.detect_failed")}</p>
    {:else}
      <p class="muted"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> {t("guide.detecting")}</p>
    {/if}
  </div>

  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}

  {#if machine?.detected}
    <fieldset class="uses">
      <legend>{t("guide.what")}</legend>
      {#each USES as option (option)}
        <label class:on={use === option}>
          <input type="radio" name="use" value={option} checked={use === option} onchange={() => recommend(option)} />
          <span><strong>{t(("guide.use." + option) as MessageKey)}</strong><small>{t(("guide.use_help." + option) as MessageKey)}</small></span>
        </label>
      {/each}
    </fieldset>

    {#if recommendation && selected}
      <article class="pick" aria-live="polite">
        <p class="tag">{selected.model.id === recommendation.recommended?.model.id ? t("guide.recommended") : t("guide.chosen")} · {t(("guide.role." + selected.role) as MessageKey)}</p>
        <h3>{selected.model.name}</h3>
        <p>{selected.model.summary}</p>
        {#if selected.model.fit}
          {@const verdict = splitFit(t(("guide.fit." + selected.model.fit.level) as MessageKey), selected.model.fit.text)}
          <p class={"fit " + selected.model.fit.level}><strong>{verdict.head}</strong>{verdict.rest}</p>
        {/if}
        <p class="muted">{t(("guide.runs_" + selected.runs_on) as MessageKey)} · {t("guide.context", selected.context_tokens)}</p>
        {#each selected.model.compatibility.reasons as reason (reason)}<p class="warn">{reason}</p>{/each}
        {#each selected.model.compatibility.warnings as warning (warning)}<p class="muted">{warning}</p>{/each}

        {#if selected.model.installed}
          <p class="ok">{t("guide.installed")}</p>
          <div class="actions"><button type="button" class="button primary" onclick={() => onuse(selected.model.id)}>{t("guide.use_this")}</button></div>
        {:else}
          <dl class="cost">
            <div><dt>{t("guide.size")}</dt><dd>{gb(selected.model.size_gb)}</dd></div>
            <div>
              <dt>{t("guide.disk")}</dt>
              <dd>{left === null ? t("guide.disk_unknown") : t("guide.free_after", gb(Math.max(left, 0)))}</dd>
            </div>
          </dl>
          {#if stop}<p class="warn" role="alert">{t(("guide.blocker." + stop) as MessageKey)}</p>{/if}
          {#if started === selected.model.id}
            <p class="ok" role="status">{t("guide.started")}</p>
          {:else if confirming}
            <div class="confirm" role="group" aria-label={t("guide.confirm_title", selected.model.name)}>
              <p><strong>{t("guide.confirm_title", selected.model.name)}</strong></p>
              <p>{t("guide.confirm_body", gb(selected.model.size_gb))}</p>
              <div class="actions">
                <button type="button" class="button primary" disabled={busy} onclick={begin}>{t("guide.confirm_yes")}</button>
                <button type="button" class="button" onclick={() => (confirming = false)}>{t("chat.cancel")}</button>
              </div>
            </div>
          {:else}
            <div class="actions">
              <button type="button" class="button primary" disabled={stop !== null} onclick={() => (confirming = true)}>{t("guide.download", gb(selected.model.size_gb))}</button>
            </div>
          {/if}
        {/if}
        <p class="estimate">{t("guide.estimate")}</p>
      </article>

      {#if list.length > 1}
        <details class="others">
          <summary>{t("guide.others")}</summary>
          <ul>
            {#each list.filter((item) => item.model.id !== selected?.model.id) as item (item.model.id)}
              <li>
                <div>
                  <strong>{item.model.name}</strong>
                  <small>{t(("guide.role." + item.role) as MessageKey)} · {gb(item.model.size_gb)}{item.model.fit ? " · " + t(("guide.fit." + item.model.fit.level) as MessageKey) : ""}</small>
                </div>
                <button type="button" class="button" onclick={() => pick(item)}>{t("guide.choose")}<span class="visually-hidden"> {item.model.name}</span></button>
              </li>
            {/each}
          </ul>
        </details>
      {/if}
    {:else if recommendation && !recommendation.recommended}
      <p class="warn">{t("guide.none")}</p>
    {/if}
  {/if}
</section>

<style>
  .guide {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  h2 {
    font-size: var(--text-md);
    font-weight: 650;
  }

  h3 {
    font-size: var(--text-lg);
    letter-spacing: -0.01em;
  }

  .machine {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .summary {
    font-weight: 600;
  }

  .muted,
  small,
  .estimate {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  .estimate {
    font-size: var(--text-xs);
  }

  .warn,
  .problem {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    font-size: var(--text-sm);
  }

  .problem {
    border: 1px solid var(--color-danger);
    background: var(--color-danger-soft);
  }

  .ok {
    color: var(--color-accent-text);
    font-weight: 600;
  }

  .dots {
    display: inline-flex;
    gap: 4px;
    margin-right: var(--space-2);
  }

  .dots i {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-pill);
    background: var(--color-accent);
    animation: breathe 1.2s ease-in-out infinite;
  }

  .dots i:nth-child(2) {
    animation-delay: 0.15s;
  }

  .dots i:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes breathe {
    0%,
    80%,
    100% {
      opacity: 0.25;
    }

    40% {
      opacity: 1;
    }
  }

  .uses {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }

  legend {
    margin-bottom: var(--space-2);
    padding: 0;
    font-weight: 650;
  }

  .uses label {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    cursor: pointer;
  }

  .uses label.on {
    border-color: var(--color-accent);
    background: var(--color-accent-soft);
  }

  .uses label:has(input:focus-visible) {
    outline: 3px solid var(--color-focus);
    outline-offset: 2px;
  }

  .uses input {
    margin-top: 0.3rem;
    accent-color: var(--color-accent);
  }

  .uses span {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .pick {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 2px solid var(--color-accent);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: var(--shadow-raised);
  }

  .tag {
    font-size: var(--text-xs);
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--color-accent-text);
  }

  .fit {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }

  .fit.comfortable,
  .fit.good {
    background: var(--color-accent-soft);
  }

  .fit.tight {
    background: var(--color-warning-soft);
  }

  .fit.too_big {
    background: var(--color-danger-soft);
  }

  .cost {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
    margin: 0;
    font-size: var(--text-sm);
  }

  .cost div {
    display: flex;
    gap: var(--space-2);
  }

  dt {
    color: var(--color-text-muted);
  }

  dd {
    margin: 0;
    font-weight: 600;
  }

  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-md);
    background: var(--color-accent-soft);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .others summary {
    min-height: var(--target);
    display: flex;
    align-items: center;
    font-weight: 600;
    cursor: pointer;
  }

  .others ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .others li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  .others li div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
</style>
