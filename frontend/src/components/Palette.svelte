<script lang="ts">
  // The Ctrl+K palette (docs/modernization/PARITY.md, item 15): a box to type where to go — an area, a section of Settings, a tab of Models or Agents,
  // a new conversation — chosen with the arrows and Enter. Opened from anywhere with Ctrl+K (⌘K on a Mac), closed with Escape.
  import { onMount, tick } from "svelte";
  import { t, type MessageKey } from "../lib/messages";
  import { SECTION_IDS } from "../lib/settings";

  type Entry = { label: string; group: string; hash: string };

  const AGENTS = ["tasks", "missions", "jobs", "addons", "connectors"];
  const ENTRIES: Entry[] = [
    { label: t("palette.new_conversation"), group: t("nav.chat"), hash: "#/chat" },
    ...(["chat", "agents", "projects", "models", "settings"] as const).map((area) => ({ label: t(("nav." + area) as MessageKey), group: t("palette.areas"), hash: "#/" + area })),
    ...SECTION_IDS.map((id) => ({ label: t(("settings.s." + id) as MessageKey), group: t("nav.settings"), hash: "#/settings/" + id })),
    ...AGENTS.map((id) => ({ label: t(("agents.tab." + id) as MessageKey), group: t("nav.agents"), hash: "#/agents/" + id })),
  ];

  let open = $state(false);
  let typed = $state("");
  let index = $state(0);
  let box = $state<HTMLInputElement | null>(null);

  const fold = (text: string): string => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const shown = $derived(ENTRIES.filter((entry) => fold(entry.label + " " + entry.group).includes(fold(typed.trim()))).slice(0, 12));

  async function show(): Promise<void> {
    open = true;
    typed = "";
    index = 0;
    await tick();
    box?.focus();
  }

  function go(entry: Entry | undefined): void {
    if (!entry) return;
    open = false;
    if (entry.hash === "#/chat" && location.hash.startsWith("#/chat")) dispatchEvent(new CustomEvent("lutin-new-conversation"));
    location.hash = entry.hash;
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      index = Math.min(index + 1, shown.length - 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      index = Math.max(index - 1, 0);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(shown[index]);
    } else if (event.key === "Escape") {
      open = false;
    }
  }

  onMount(() => {
    const onGlobal = (event: KeyboardEvent): void => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        void show();
      }
    };
    addEventListener("keydown", onGlobal);
    return () => removeEventListener("keydown", onGlobal);
  });
</script>

{#if open}
  <div class="backdrop" role="presentation" onclick={() => (open = false)}></div>
  <div class="palette" role="dialog" aria-modal="true" aria-label={t("palette.title")}>
    <label class="visually-hidden" for="palette-box">{t("palette.title")}</label>
    <input id="palette-box" type="text" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={shown[index] ? "palette-" + index : undefined}
      placeholder={t("palette.placeholder")} autocomplete="off" bind:value={typed} bind:this={box} oninput={() => (index = 0)} onkeydown={onKey} />
    <ul id="palette-list" role="listbox" aria-label={t("palette.title")}>
      {#each shown as entry, position (entry.hash + entry.label)}
        <li id={"palette-" + position} role="option" aria-selected={position === index} tabindex="-1" onclick={() => go(entry)} onkeydown={onKey} onmouseenter={() => (index = position)}>
          {entry.label} <span class="group">{entry.group}</span>
        </li>
      {/each}
      {#if shown.length === 0}<li class="none">{t("olib.none")}</li>{/if}
    </ul>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgb(0 0 0 / 0.35);
  }

  .palette {
    position: fixed;
    top: 12vh;
    left: 50%;
    z-index: 21;
    width: min(36rem, calc(100% - 2 * var(--space-4)));
    transform: translateX(-50%);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    box-shadow: 0 12px 32px rgb(0 0 0 / 0.25);
  }

  input {
    width: 100%;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }

  ul {
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
    max-height: 50vh;
    overflow-y: auto;
  }

  li[role="option"] {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    width: 100%;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    cursor: pointer;
  }

  li[aria-selected="true"] {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
  }

  .group {
    color: var(--color-text-muted);
    font-size: var(--text-sm);
  }

  li[aria-selected="true"] .group {
    color: inherit;
  }

  .none {
    padding: var(--space-2) var(--space-3);
    color: var(--color-text-muted);
  }
</style>
