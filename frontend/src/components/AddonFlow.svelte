<script lang="ts">
  // The flow of an add-on: the list of calls it makes to its service. Advanced: for when a service changes and the add-on stops working. The text is checked by the server before it
  // is kept (right structure, only the hosts the add-on declares); the shipped flow can always be put back. After a failed check the model can propose a corrected flow: it is only
  // placed in the box for you to read, and kept only when you save. For the machine itself only.
  import { ApiError, api } from "../lib/api";
  import { canPropose, flowText, isChanged, parseFlow, type Flow } from "../lib/addonflow";
  import { t } from "../lib/messages";

  let { id, check }: { id: string; check: { ok: boolean } | null } = $props();

  type View = { flow: Flow; shipped: Flow; modified: boolean };
  type Proposal = { flow: Flow; diff: string; explanation: string };

  let view = $state<View | null>(null);
  let text = $state("");
  let problem = $state("");
  let done = $state("");
  let busy = $state(false);
  let restoring = $state(false);
  let proposal = $state<Proposal | null>(null);

  const path = $derived(`/addons/${encodeURIComponent(id)}/flow`);
  const changed = $derived(view !== null && isChanged(text, view.flow));

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.code === "configurator") return t("flow.only_here");
      if (cause.code === "offline") return t("flow.offline");
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

  function show(next: View): void {
    view = next;
    text = flowText(next.flow);
  }

  const load = (): Promise<void> => (view ? Promise.resolve() : act(async () => show(await api<View>("GET", path))));

  const save = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      const parsed = parseFlow(text);
      if (!parsed.ok) {
        problem = t("flow.not_json");
        return;
      }
      show(await api<View>("PATCH", path, { flow: parsed.flow }));
      proposal = null;
      done = t("flow.saved");
    });
  };

  const restore = (): Promise<void> =>
    act(async () => {
      show(await api<View>("POST", path + "/restore", {}));
      restoring = false;
      proposal = null;
      done = t("flow.restored");
    });

  const propose = (): Promise<void> =>
    act(async () => {
      proposal = await api<Proposal>("POST", `/addons/${encodeURIComponent(id)}/correction`, {});
    });

  function useProposal(): void {
    if (!proposal) return;
    text = flowText(proposal.flow);
    done = t("flow.proposal_placed");
    proposal = null;
  }
</script>

<details class="flow" ontoggle={(event) => event.currentTarget.open && void load()}>
  <summary>{t("flow.title")}</summary>
  <p class="muted">{t("flow.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if done}<p class="done" role="status">{done}</p>{/if}
  {#if view}
    <form onsubmit={save}>
      <label for={"flow-" + id}>{t("flow.label")}</label>
      <textarea id={"flow-" + id} rows="14" spellcheck="false" bind:value={text}></textarea>
      <p class="muted">{view.modified ? t("flow.is_yours") : t("flow.is_shipped")}</p>
      <div class="actions">
        <button type="submit" class="button primary" disabled={busy || !changed}>{t("flow.save")}</button>
        {#if canPropose(check)}<button type="button" class="button" disabled={busy} onclick={propose}>{t("flow.propose")}</button>{/if}
        {#if view.modified}
          {#if restoring}
            <span class="confirm" role="group" aria-label={t("flow.restore_confirm")}>
              <span>{t("flow.restore_confirm")}</span>
              <button type="button" class="button danger" disabled={busy} onclick={restore}>{t("flow.restore_yes")}</button>
              <button type="button" class="button" onclick={() => (restoring = false)}>{t("chat.cancel")}</button>
            </span>
          {:else}
            <button type="button" class="button" disabled={busy} onclick={() => (restoring = true)}>{t("flow.restore")}</button>
          {/if}
        {/if}
      </div>
    </form>
    {#if proposal}
      <div class="proposal" role="region" aria-label={t("flow.proposal")}>
        <h4>{t("flow.proposal")}</h4>
        {#if proposal.explanation}<p>{proposal.explanation}</p>{/if}
        <label for={"flow-diff-" + id}>{t("flow.diff")}</label>
        <textarea id={"flow-diff-" + id} class="diff" readonly rows="10" value={proposal.diff}></textarea>
        <div class="actions">
          <button type="button" class="button primary" onclick={useProposal}>{t("flow.use")}</button>
          <button type="button" class="button" onclick={() => (proposal = null)}>{t("flow.dismiss")}</button>
        </div>
      </div>
    {/if}
  {:else if !problem}
    <p class="muted">{t("flow.loading")}</p>
  {/if}
</details>

<style>
  .flow {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  summary {
    cursor: pointer;
    font-weight: 600;
  }

  form,
  .proposal {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  h4,
  p {
    margin: 0;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .actions,
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  textarea {
    box-sizing: border-box;
    width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-mono, monospace);
    font-size: var(--text-sm);
    resize: vertical;
  }

  label {
    font-weight: 600;
  }

  .danger {
    background: var(--color-danger-soft);
    color: var(--color-danger);
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
