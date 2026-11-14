<script lang="ts">
  // The shell: five areas, one navigation, the theme. Each area is a screen under screens/.
  import { onMount } from "svelte";
  import { api, ApiError } from "./lib/api";
  import { t, type MessageKey } from "./lib/messages";
  import { applyTheme, nextTheme, readTheme, type Theme } from "./lib/theme";
  import type { Status } from "./lib/types";
  import Chat from "./screens/Chat.svelte";
  import ComingSoon from "./screens/ComingSoon.svelte";

  const AREAS = ["chat", "agents", "projects", "models", "settings"] as const;
  type Area = (typeof AREAS)[number];

  function areaOf(hash: string): Area {
    const name = hash.replace(/^#\/?/, "");
    return (AREAS as readonly string[]).includes(name) ? (name as Area) : "chat";
  }

  let area = $state<Area>(areaOf(location.hash));
  let theme = $state<Theme>(readTheme());
  let status = $state<Status | null>(null);
  let problem = $state("");

  async function refreshStatus(): Promise<void> {
    try {
      status = await api<Status>("GET", "/status");
      problem = "";
    } catch (cause) {
      problem = cause instanceof ApiError && cause.message ? cause.message : t("error.unreachable");
    }
  }

  function changeTheme(): void {
    theme = nextTheme(theme);
    applyTheme(theme);
  }

  onMount(() => {
    const onHash = (): void => {
      area = areaOf(location.hash);
    };
    addEventListener("hashchange", onHash);
    void refreshStatus();
    return () => removeEventListener("hashchange", onHash);
  });
</script>

<a class="skip" href="#main">{t("a11y.skip")}</a>
<div class="shell">
  <nav class="rail" aria-label={t("nav.label")}>
    <p class="brand">Lutin</p>
    <ul>
      {#each AREAS as name (name)}
        <li><a href={"#/" + name} aria-current={area === name ? "page" : undefined}>{t(("nav." + name) as MessageKey)}</a></li>
      {/each}
    </ul>
    <div class="foot">
      <button type="button" class="button quiet" onclick={changeTheme}>{t(("theme." + theme) as MessageKey)}</button>
      <a class="legacy" href="/">{t("legacy.link")}</a>
      {#if status}<p class="version">Lutin {status.version}</p>{/if}
    </div>
  </nav>
  <main id="main" tabindex="-1">
    {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
    {#if area === "chat"}
      <Chat {status} onchanged={refreshStatus} />
    {:else}
      <ComingSoon name={t(("nav." + area) as MessageKey)} />
    {/if}
  </main>
</div>

<style>
  .skip {
    position: absolute;
    left: var(--space-2);
    top: -10rem;
    z-index: 10;
    padding: var(--space-2) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .skip:focus {
    top: var(--space-2);
  }

  .shell {
    display: grid;
    grid-template-columns: var(--rail-width) minmax(0, 1fr);
    height: 100%;
  }

  .rail {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-4) var(--space-3);
    border-right: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .brand {
    padding: 0 var(--space-3);
    font-size: var(--text-lg);
    font-weight: 700;
  }

  ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li a {
    display: flex;
    align-items: center;
    min-height: var(--target);
    padding: 0 var(--space-3);
    border-radius: var(--radius-md);
    color: var(--color-text);
    text-decoration: none;
  }

  li a:hover {
    background: var(--color-surface-raised);
  }

  li a[aria-current="page"] {
    background: var(--color-accent-soft);
    font-weight: 600;
  }

  .foot {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    margin-top: auto;
    font-size: var(--text-sm);
  }

  .legacy,
  .version {
    padding: 0 var(--space-4);
    color: var(--color-text-muted);
  }

  main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    outline: none;
  }

  .banner {
    margin: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-danger);
    border-radius: var(--radius-md);
    background: var(--color-danger-soft);
  }

  /* Narrow screens (a phone held upright, down to 360 px): the navigation becomes a bar at the bottom. */
  @media (max-width: 720px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr) auto;
    }

    .rail {
      grid-row: 2;
      flex-direction: row;
      padding: var(--space-1);
      border-top: 1px solid var(--color-border);
      border-right: 0;
    }

    .brand,
    .foot {
      display: none;
    }

    ul {
      flex: 1;
      flex-direction: row;
    }

    li {
      flex: 1;
      min-width: 0;
    }

    li a {
      justify-content: center;
      padding: 0 var(--space-1);
      font-size: var(--text-xs);
    }
  }
</style>
