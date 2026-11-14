<script lang="ts">
  // The shell: five areas, one navigation, the theme. Each area is a screen under screens/.
  import { onMount } from "svelte";
  import Icon, { type IconName } from "./components/Icon.svelte";
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
    <p class="brand"><img src="/logo.svg" alt="" width="30" height="30" /><span>Lutin</span></p>
    <ul>
      {#each AREAS as name (name)}
        <li>
          <a href={"#/" + name} aria-current={area === name ? "page" : undefined}>
            <Icon name={name as IconName} /><span>{t(("nav." + name) as MessageKey)}</span>
          </a>
        </li>
      {/each}
    </ul>
    <div class="foot">
      <button type="button" class="theme" onclick={changeTheme}><Icon name={theme as IconName} size={18} /><span>{t(("theme." + theme) as MessageKey)}</span></button>
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
    gap: var(--space-5);
    padding: var(--space-4) var(--space-3);
    border-right: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-lg);
    font-weight: 700;
    letter-spacing: -0.01em;
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
    gap: var(--space-3);
    min-height: var(--target);
    padding: 0 var(--space-3);
    border-radius: var(--radius-md);
    color: var(--color-text-muted);
    font-weight: 500;
    text-decoration: none;
  }

  li a:hover {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  li a[aria-current="page"] {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-weight: 650;
  }

  .foot {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
    margin-top: auto;
    font-size: var(--text-sm);
  }

  .theme {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--target);
    padding: 0 var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--color-text-muted);
    cursor: pointer;
  }

  .theme:hover {
    background: var(--color-surface-raised);
    color: var(--color-text);
  }

  .legacy,
  .version {
    padding: 0 var(--space-3);
    color: var(--color-text-muted);
  }

  .version {
    font-size: var(--text-xs);
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

  /* Narrow screens (a phone held upright, down to 360 px): the navigation becomes a bar at the bottom, an icon above each name. */
  @media (max-width: 720px) {
    .shell {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr) auto;
    }

    .rail {
      grid-row: 2;
      flex-direction: row;
      padding: var(--space-1) var(--space-1) max(var(--space-1), env(safe-area-inset-bottom));
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
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      min-height: 3.25rem;
      padding: var(--space-1);
      font-size: var(--text-xs);
    }
  }
</style>
