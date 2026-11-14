<script lang="ts" module>
  // The icons of the interface, drawn here as outlines: no icon font, no file to fetch. Always decorative: the text next to an icon
  // (visible, or hidden for screen readers only) says what the control does.
  const SHAPES = {
    chat: ["M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"],
    agents: ["M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z", "M18.5 15l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"],
    projects: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
    models: ["M12 3l9 4.5-9 4.5-9-4.5z", "M3 12l9 4.5 9-4.5", "M3 16.5l9 4.5 9-4.5"],
    settings: ["M4 7h8", "M18 7h2", "M4 17h2", "M12 17h8", "M12 7a3 3 0 1 0 6 0a3 3 0 1 0-6 0", "M6 17a3 3 0 1 0 6 0a3 3 0 1 0-6 0"],
    plus: ["M12 5v14", "M5 12h14"],
    send: ["M12 19V5", "M6 11l6-6 6 6"],
    stop: ["M8 7h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"],
    light: ["M8 12a4 4 0 1 0 8 0a4 4 0 1 0-8 0", "M12 2v2", "M12 20v2", "M2 12h2", "M20 12h2", "M4.9 4.9l1.4 1.4", "M17.7 17.7l1.4 1.4", "M4.9 19.1l1.4-1.4", "M17.7 6.3l1.4-1.4"],
    dark: ["M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"],
    system: ["M5 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M8 20h8", "M12 16v4"],
    trash: ["M4 7h16", "M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2", "M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12"],
    menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
    close: ["M6 6l12 12", "M18 6L6 18"],
  } as const;

  export type IconName = keyof typeof SHAPES;
</script>

<script lang="ts">
  let { name, size = 20 }: { name: IconName; size?: number } = $props();
</script>

<svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
  {#each SHAPES[name] as d (d)}<path {d} />{/each}
</svg>

<style>
  svg {
    flex: none;
  }
</style>
