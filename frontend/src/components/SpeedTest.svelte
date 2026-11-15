<script lang="ts">
  // An optional quick test of how fast the chosen model writes here. Nothing starts without a click on « Yes »; « No thanks » closes it.
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t, type MessageKey } from "../lib/messages";

  type Speed = { state: "idle" | "running" | "done" | "failed"; tokens_per_second: number | null; level: string | null; error: string };

  let speed = $state<Speed>({ state: "idle", tokens_per_second: null, level: null, error: "" });
  let declined = $state(false);
  let problem = $state("");
  let alive = true;

  const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

  async function follow(): Promise<void> {
    while (alive && speed.state === "running") {
      await wait(1000);
      speed = await api<Speed>("GET", "/speed-test");
    }
  }

  async function start(): Promise<void> {
    try {
      problem = "";
      speed = await api<Speed>("POST", "/speed-test", {});
      await follow();
    } catch (cause) {
      problem = cause instanceof ApiError && cause.message ? cause.message : t("error.generic", String(cause));
    }
  }

  onMount(() => {
    void api<Speed>("GET", "/speed-test").then((answer) => {
      speed = answer;
      void follow();
    }).catch(() => undefined);
    return () => {
      alive = false;
    };
  });
</script>

{#if !declined}
  <section class="speed" aria-labelledby="speed-title">
    <h2 id="speed-title">{t("speed.title")}</h2>
    {#if speed.state === "running"}
      <p class="muted" role="status"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> {t("speed.running")}</p>
    {:else if speed.state === "done" && speed.tokens_per_second !== null}
      <p role="status"><strong>{t(("speed.level." + speed.level) as MessageKey)}</strong> · {t("speed.figure", speed.tokens_per_second)}</p>
    {:else}
      {#if speed.state === "failed"}<p class="warn" role="status">{speed.error || t("speed.failed")}</p>{/if}
      <p class="muted">{t("speed.body")}</p>
      <div class="actions">
        <button type="button" class="button primary" onclick={start}>{t("speed.yes")}</button>
        <button type="button" class="button quiet" onclick={() => (declined = true)}>{t("speed.no")}</button>
      </div>
    {/if}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  </section>
{/if}

<style>
  .speed {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
  }

  h2 {
    margin: 0;
    font-size: var(--text-md);
  }

  p {
    margin: 0;
  }

  .muted {
    color: var(--color-text-muted);
  }

  .warn,
  .problem {
    color: var(--color-danger);
    font-size: var(--text-sm);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
