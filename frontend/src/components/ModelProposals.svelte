<script lang="ts">
  // The proposals of the Models screen (docs/modernization/PARITY.md, item 10): what the check at launch found, or a check asked now — an update of
  // an installed model, a better model for a role on this machine, an old model replaced by one already installed. Installing goes through
  // POST /models and then tells the proposal it was followed; deleting an old model waits for a second click. Nothing happens without a click.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { language, t, type MessageKey } from "../lib/messages";

  type Proposal = { key: string; kind: "update" | "new" | "obsolete"; model: string; role: string | null; replaces: string | null; replaced_by: string | null; size_gb: number | null; summary: string; reason: string };
  type View = { proposals: Proposal[]; errors: string[]; checked_at: number; catalogue: string | null };

  let { onchanged }: { onchanged: () => void } = $props();

  const lang = language();
  let view = $state<View | null>(null);
  let busy = $state(false);
  let checking = $state("");
  let deleting = $state("");
  let notice = $state("");
  let problem = $state("");

  const path = (proposal: Proposal): string => "/models/proposals/" + encodeURIComponent(proposal.key);
  const gb = (value: number): string => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    problem = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const check = (scope: "updates" | "new"): Promise<void> =>
    act(async () => {
      checking = scope;
      notice = t("upkeep.checking");
      try {
        view = await api<View>("POST", "/models/check", { scope });
        const found = view.proposals.filter((proposal) => (scope === "updates") === (proposal.kind === "update")).length;
        notice = found ? t("upkeep.found", found) : t(scope === "updates" ? "upkeep.all_current" : "upkeep.nothing_better");
        if (scope === "new" && view.catalogue === "absent") notice += " " + t("upkeep.no_catalogue");
      } finally {
        checking = "";
      }
    });

  const install = (proposal: Proposal): Promise<void> =>
    act(async () => {
      await api("POST", "/models", { name: proposal.model });
      view = await api<View>("POST", path(proposal) + "/applied", {});
      notice = t("upkeep.started", proposal.model);
      onchanged();
    });

  const dismiss = (proposal: Proposal): Promise<void> =>
    act(async () => {
      view = await api<View>("DELETE", path(proposal));
    });

  const removeOld = (proposal: Proposal): Promise<void> =>
    act(async () => {
      await api("DELETE", "/models/" + encodeURIComponent(proposal.model));
      deleting = "";
      view = await api<View>("DELETE", path(proposal));
      onchanged();
    });

  function title(proposal: Proposal): string {
    if (proposal.kind === "update") return t("upkeep.update_of", proposal.model);
    if (proposal.kind === "obsolete") return t("upkeep.old_model", proposal.model);
    return proposal.role ? t("upkeep.best_for", t(("guide.role." + proposal.role) as MessageKey), proposal.model) : proposal.model;
  }

  onMount(() => {
    api<View>("GET", "/models/proposals").then((answer) => (view = answer), (cause) => (problem = explain(cause)));
  });
</script>

<section class="proposals" aria-labelledby="proposals-title">
  <h2 id="proposals-title">{t("upkeep.title")}</h2>
  <div class="actions">
    <button type="button" class="button" disabled={busy} onclick={() => check("updates")}>{checking === "updates" ? t("upkeep.checking") : t("upkeep.check_updates")}</button>
    <button type="button" class="button" disabled={busy} onclick={() => check("new")}>{checking === "new" ? t("upkeep.checking") : t("upkeep.check_new")}</button>
  </div>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if view}
    {#each view.errors as error, index (index)}<p class="muted">{error}</p>{/each}
    {#if view.proposals.length}
      <ul class="cards">
        {#each view.proposals as proposal (proposal.key)}
          <li class="card" data-kind={proposal.kind}>
            <p class="line"><strong>{title(proposal)}</strong>{#if proposal.size_gb}<span class="muted">{t("upkeep.size", gb(proposal.size_gb))}</span>{/if}</p>
            {#if proposal.summary}<p>{proposal.summary}</p>{/if}
            <p class="muted">{proposal.reason}{#if proposal.replaces} {t("upkeep.replaces", proposal.replaces)}{/if}</p>
            <div class="actions">
              {#if proposal.kind === "obsolete"}
                {#if deleting === proposal.key}
                  <span class="confirm" role="group" aria-label={t("upkeep.delete_confirm", proposal.model)}>
                    <span>{t("upkeep.delete_confirm", proposal.model)}</span>
                    <button type="button" class="button danger" disabled={busy} onclick={() => removeOld(proposal)}>{t("upkeep.delete_yes")}</button>
                    <button type="button" class="button" onclick={() => (deleting = "")}>{t("chat.cancel")}</button>
                  </span>
                {:else}
                  <button type="button" class="button primary" disabled={busy} onclick={() => (deleting = proposal.key)}>{t("upkeep.delete", proposal.model)}</button>
                  <button type="button" class="button" disabled={busy} onclick={() => dismiss(proposal)}>{t("upkeep.keep")}</button>
                {/if}
              {:else}
                <button type="button" class="button primary" disabled={busy} onclick={() => install(proposal)}>{proposal.kind === "update" ? t("upkeep.update") : t("upkeep.install")}</button>
                <button type="button" class="button" disabled={busy} onclick={() => dismiss(proposal)}>{t("upkeep.dismiss")}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .proposals {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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
    font-size: var(--text-sm);
  }

  .notice:empty {
    display: none;
  }

  .notice {
    color: var(--color-accent-text);
  }

  .problem {
    color: var(--color-danger);
  }

  .actions,
  .confirm,
  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
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
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    overflow-wrap: anywhere;
  }
</style>
