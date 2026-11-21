<script lang="ts">
  // « Helper programs » in Settings › Tools (docs/modernization/PARITY.md, item 18): uv and Node.js, which some connectors and skills need. Installed by
  // Lutin in its own folder (removable here), or found on the machine (never touched).
  import { onMount } from "svelte";
  import { api, ApiError } from "../lib/api";
  import { t } from "../lib/messages";

  type Program = { name: string; label: string; help: string; installed: boolean; by_lutin: boolean; version: string };

  let programs = $state<Program[] | null>(null);
  let canConfigure = $state(false);
  let busy = $state("");
  let problem = $state("");

  function explain(cause: unknown): string {
    if (cause instanceof ApiError) return cause.message || (cause.code === "unreachable" ? t("error.unreachable") : t("error.generic", cause.code));
    return t("error.generic", String(cause));
  }

  async function act(program: Program, method: "POST" | "DELETE"): Promise<void> {
    busy = program.name;
    problem = "";
    try {
      programs = (await api<{ programs: Program[] }>(method, `/helper-programs/${encodeURIComponent(program.name)}${method === "POST" ? "/install" : ""}`, method === "POST" ? {} : undefined)).programs;
    } catch (cause) {
      problem = explain(cause);
    }
    busy = "";
  }

  onMount(() => {
    api<{ programs: Program[] }>("GET", "/helper-programs").then((answer) => (programs = answer.programs), (cause) => (problem = explain(cause)));
    api<{ access: { can_configure: boolean } }>("GET", "/status").then((answer) => (canConfigure = answer.access.can_configure), () => undefined);
  });
</script>

<section class="helpers" aria-labelledby="helpers-title">
  <h2 id="helpers-title">{t("helpers.title")}</h2>
  <p class="muted">{t("helpers.intro")}</p>
  {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
  {#if programs}
    <ul>
      {#each programs as program (program.name)}
        <li>
          <p><strong>{program.label}</strong> <span class="muted">{program.installed ? (program.by_lutin ? t("helpers.by_lutin", program.version) : t("helpers.on_machine", program.version)) : t("helpers.missing")}</span></p>
          <p class="muted">{program.help}</p>
          {#if canConfigure}
            {#if !program.installed}
              <button type="button" class="button" disabled={!!busy} onclick={() => act(program, "POST")}>{busy === program.name ? t("helpers.working") : t("helpers.install", program.label)}</button>
            {:else if program.by_lutin}
              <button type="button" class="button quiet danger" disabled={!!busy} onclick={() => act(program, "DELETE")}>{busy === program.name ? t("helpers.working") : t("helpers.uninstall", program.label)}</button>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .helpers {
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
    font-size: var(--text-sm);
  }

  .problem {
    color: var(--color-danger);
  }

  ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    align-items: flex-start;
  }
</style>
