<script lang="ts">
  // The shell: five areas, one navigation, the theme. Each area is a screen under screens/.
  import { onMount } from "svelte";
  import Icon, { type IconName } from "./components/Icon.svelte";
  import LutinBanners from "./components/LutinBanners.svelte";
  import Palette from "./components/Palette.svelte";
  import { api, ApiError } from "./lib/api";
  import { t, type MessageKey } from "./lib/messages";
  import { waiting, type NodeView } from "./lib/node";
  import { applyTheme, nextTheme, readTheme, type Theme } from "./lib/theme";
  import type { Status } from "./lib/types";
  import Chat from "./screens/Chat.svelte";
  import Models from "./screens/Models.svelte";
  import Setup from "./screens/Setup.svelte";
  import Agents from "./screens/Agents.svelte";
  import ComingSoon from "./screens/ComingSoon.svelte";
  import Projects from "./screens/Projects.svelte";
  import Settings from "./screens/Settings.svelte";

  const AREAS = ["chat", "agents", "projects", "models", "settings"] as const;
  type Area = (typeof AREAS)[number];

  function areaOf(hash: string): Area {
    const name = hash.replace(/^#\/?/, "").split("/")[0]; // `#/settings/safety` is the area Settings; what follows is for the screen
    return (AREAS as readonly string[]).includes(name) ? (name as Area) : "chat";
  }

  let area = $state<Area>(areaOf(location.hash));
  let theme = $state<Theme>(readTheme());
  let status = $state<Status | null>(null);
  let problem = $state("");
  let setupNeeded = $state<boolean | null>(null); // null while the server is asked: the shell is not drawn first and replaced a moment later
  let nodeWaiting = $state(0); // rights requests and a shutdown asked by another machine: a badge on Settings, as on the old page (ADR 0016, stage 5)

  async function refreshNode(): Promise<void> {
    nodeWaiting = waiting(await api<NodeView>("GET", "/node").catch(() => null));
  }

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
    const onStatus = (): void => void refreshStatus(); // what a screen changed and the shell shows: a banner of Lutin's version
    const onNode = (event: Event): void => {
      nodeWaiting = (event as CustomEvent<number>).detail; // announced by the « Lend this machine » group after each of its readings
    };
    addEventListener("hashchange", onHash);
    addEventListener("lutin-node", onNode);
    addEventListener("lutin-status", onStatus);
    void refreshStatus();
    void refreshNode();
    const timer = setInterval(() => void refreshNode(), 15000);
    api<{ needed: boolean }>("GET", "/setup").then((answer) => (setupNeeded = answer.needed), () => (setupNeeded = false)); // a server that does not answer must not trap the person in a guide
    return () => {
      removeEventListener("hashchange", onHash);
      removeEventListener("lutin-node", onNode);
      removeEventListener("lutin-status", onStatus);
      clearInterval(timer);
    };
  });
</script>

{#if setupNeeded === null}
  <p class="loading" role="status">{t("setup.engine_looking")}</p>
{:else if setupNeeded}
  <Setup {status} onfinished={() => ((setupNeeded = false), void refreshStatus())} />
{:else}
<a class="skip" href="#main">{t("a11y.skip")}</a>
<Palette />
<div class="shell">
  <nav class="rail" aria-label={t("nav.label")}>
    <p class="brand"><img src="/logo.svg" alt="" width="30" height="30" /><span>Lutin</span></p>
    <ul>
      {#each AREAS as name (name)}
        <li>
          <a href={"#/" + name} aria-current={area === name ? "page" : undefined}>
            <Icon name={name as IconName} /><span>{t(("nav." + name) as MessageKey)}</span>
            {#if name === "settings" && nodeWaiting > 0}<span class="count" aria-hidden="true">{nodeWaiting}</span><span class="visually-hidden">{t("nav.waiting", nodeWaiting)}</span>{/if}
          </a>
        </li>
      {/each}
    </ul>
    <div class="foot">
      <button type="button" class="theme" onclick={changeTheme}><Icon name={theme as IconName} size={18} /><span>{t(("theme." + theme) as MessageKey)}</span></button>
      <a class="legacy" href="/">{t("legacy.link")}</a>
      {#if status?.offline}<a class="offline-mark" href="#/settings/safety" title={t("offline.mark_title")}>{t("offline.mark")}</a>{/if}
      {#if status}<p class="version">Lutin {status.version}</p>{/if}
    </div>
  </nav>
  <main id="main" tabindex="-1">
    {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
    <LutinBanners {status} onchanged={refreshStatus} />
    {#if area === "chat"}
      <Chat {status} onchanged={refreshStatus} />
    {:else if area === "models"}
      <Models {status} onchanged={refreshStatus} />
    {:else if area === "agents"}
      <Agents />
    {:else if area === "projects"}
      <Projects />
    {:else if area === "settings"}
      <Settings />
    {:else}
      <ComingSoon name={t(("nav." + area) as MessageKey)} />
    {/if}
  </main>
</div>
{/if}

<style>
  .loading {
    padding: var(--space-6);
    color: var(--color-text-muted);
  }

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
    grid-template-rows: minmax(0, 1fr); /* one row the height of the window: a long screen scrolls inside <main>, never the whole page under the navigation */
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

  /* What waits for an answer (Settings): a count at the end of the line, at the corner of the icon on a phone. */
  li a {
    position: relative;
  }

  .count {
    min-width: 1.4rem;
    margin-left: auto;
    padding: 0 var(--space-1);
    border-radius: var(--radius-pill);
    background: var(--color-warning-soft);
    color: var(--color-text);
    font-size: var(--text-xs);
    font-weight: 700;
    text-align: center;
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

  .offline-mark {
    align-self: flex-start;
    margin: 0 var(--space-3);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-warning-soft);
    color: var(--color-text);
    font-size: var(--text-sm);
  }

  main {
    position: relative; /* the containing block of what is positioned inside (a text hidden for the eyes): it scrolls with <main> instead of lengthening the page */
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow-y: auto; /* a long screen scrolls here: the navigation stays in place, and on a phone nothing covers the bar at the bottom */
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

    .count {
      position: absolute;
      top: 2px;
      right: 2px;
      margin: 0;
    }
  }
</style>
