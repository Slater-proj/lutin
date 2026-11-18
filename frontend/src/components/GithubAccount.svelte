<script lang="ts">
  // « GitHub account » in the section « General » of Settings: Lutin reads GitHub for the new versions of its engines, for its own update and for the
  // third-party skills. Without an account GitHub allows 60 requests an hour from this address; a token (with no permission) lifts that limit for
  // the whole application. The token is kept on this machine and never shown again; keeping or testing it is for this machine (`configurator`).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type View = { github: { configured: boolean; source: string }; offline: boolean };

  let canConfigure = $state(false);
  let view = $state<View | null>(null);
  let token = $state("");
  let busy = $state(false);
  let notice = $state("");
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(action: () => Promise<void>): Promise<void> {
    busy = true;
    problem = "";
    notice = "";
    try {
      await action();
    } catch (cause) {
      problem = explain(cause);
    }
    busy = false;
  }

  const load = async (): Promise<void> => void (view = await api<View>("GET", "/github"));

  const save = (event: SubmitEvent): Promise<void> => {
    event.preventDefault();
    return act(async () => {
      await api("PATCH", "/github", { token: token.trim() });
      token = "";
      await load();
      notice = t("web.saved");
    });
  };

  const remove = (): Promise<void> =>
    act(async () => {
      await api("PATCH", "/github", { token: "" });
      await load();
    });

  const test = (): Promise<void> =>
    act(async () => {
      const result = await api<{ limit: number; remaining: number; authenticated: boolean; account: string }>("POST", "/github/test", {});
      notice = t(result.authenticated ? "tps.tested_account" : "tps.tested", result.remaining, result.limit, result.account);
    });

  onMount(() => {
    void load().catch((cause) => (problem = explain(cause)));
    void api<{ access: { can_configure: boolean } }>("GET", "/status").then((answer) => (canConfigure = answer.access.can_configure)).catch(() => undefined);
  });
</script>

<section class="github" aria-labelledby="github-title">
  <h2 id="github-title">{t("tps.github")}</h2>
  <p class="muted">{t("github.uses")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  <p class="notice" role="status">{notice}</p>
  {#if view}
    <p>{view.github.configured ? t("tps.github_set", view.github.source === "environment" ? t("tps.github_from_env") : t("tps.github_from_settings")) : t("tps.github_none")}</p>
    {#if canConfigure}
      <p class="muted">{t("github.how")}</p>
      <form class="row" onsubmit={save}>
        <label for="github-token">{t("tps.github_token")}</label>
        <input id="github-token" type="password" bind:value={token} autocomplete="off" spellcheck="false" />
        <button type="submit" class="button" disabled={busy || !token.trim()}>{t("tps.github_save")}</button>
      </form>
      <div class="row">
        <button type="button" class="button" disabled={busy || view.offline} onclick={test}>{t("tps.github_test")}</button>
        {#if view.github.configured && view.github.source !== "environment"}<button type="button" class="button" disabled={busy} onclick={remove}>{t("tps.github_remove")}</button>{/if}
      </div>
    {:else}
      <p class="muted">{t("github.only_here")}</p>
    {/if}
  {/if}
</section>

<style>
  .github {
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
    max-width: var(--measure);
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

  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .row input {
    flex: 1 1 16rem;
    min-width: 0;
  }
</style>
