<script lang="ts">
  // The layout of a screen in sections (Settings, Agents; docs/modernization/INTERFACE.md, « Layout and widths »): the list of sections on the left,
  // the chosen one on the right, each one an address (`base/<id>`). On a phone (the breakpoint of the shell), the list alone when none is named in
  // the address, then the chosen one alone with a way back. When a section is chosen, the focus goes to it: on a phone the list is gone.
  import { tick, type Snippet } from "svelte";

  let { ids, label, base, navLabel, backLabel, chosen, children }: {
    ids: readonly string[];
    label: (id: string) => string;
    base: string;
    navLabel: string;
    backLabel: string;
    /** The section named in the address, or null: the first one is shown on a wide screen, the list on a phone. */
    chosen: string | null;
    children: Snippet;
  } = $props();

  const NARROW = matchMedia("(max-width: 720px)");
  let narrow = $state(NARROW.matches);
  const marked = $derived(chosen ?? (narrow ? null : ids[0])); // on a phone the list marks none: none is open
  let content = $state<HTMLElement | null>(null);
  let seen: string | null | undefined;

  $effect(() => {
    const onWidth = (): void => void (narrow = NARROW.matches);
    NARROW.addEventListener("change", onWidth);
    return () => NARROW.removeEventListener("change", onWidth);
  });

  $effect(() => {
    if (seen !== undefined && chosen !== null && chosen !== seen) void tick().then(() => content?.focus()); // not on the first drawing
    seen = chosen;
  });
</script>

<div class="layout" class:chosen={chosen !== null}>
  <nav class="sections" aria-label={navLabel}>
    <ul>
      {#each ids as id (id)}
        <li><a href={base + "/" + id} aria-current={marked === id ? "page" : undefined}>{label(id)}</a></li>
      {/each}
    </ul>
  </nav>
  <div class="content" bind:this={content} tabindex="-1">
    <a class="back" href={base}>← {backLabel}</a>
    {@render children()}
  </div>
</div>

<style>
  .layout {
    display: grid;
    grid-template-columns: 13rem minmax(0, 1fr);
    gap: var(--space-5);
    align-items: start;
  }

  .sections {
    position: sticky;
    top: var(--space-4);
  }

  .sections ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .sections a {
    display: flex;
    align-items: center;
    min-height: var(--target);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    color: var(--color-text);
    text-decoration: none;
  }

  .sections a:hover {
    background: var(--color-surface);
  }

  .sections a[aria-current="page"] {
    background: var(--color-accent-soft);
    color: var(--color-accent-text);
    font-weight: 600;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-width: 0;
  }

  .content:focus {
    outline: none;
  }

  .back {
    display: none;
  }

  @media (max-width: 720px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }

    .sections {
      position: static;
    }

    .layout.chosen .sections,
    .layout:not(.chosen) .content {
      display: none;
    }

    .layout.chosen .back {
      display: flex;
      align-items: center;
      min-height: var(--target);
    }
  }
</style>
