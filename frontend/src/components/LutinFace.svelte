<script lang="ts" module>
  // Lutin's logo with living eyes (maintainer, 2026-11-21: « something fluid, not two dry images, that gives the feeling that Lutin is alive »). The hat
  // and the sparkle are the logo's (src/lutin/web/logo.svg); each eye has a pupil that moves, an upper lid and a lower lid in the colour of the hat.
  // The mood moves them with CSS animations: nothing to download, no script running in a loop, and nothing moves for a person who asked their system
  // to reduce motion.
  export type Mood = "idle" | "thinking" | "happy" | "worried" | "sad" | "angry" | "sleep";
  export const MOODS: readonly Mood[] = ["idle", "thinking", "happy", "worried", "sad", "angry", "sleep"];
  let made = 0;
</script>

<script lang="ts">
  let { mood = "idle", size = 30, label = "" }: { mood?: Mood; size?: number; label?: string } = $props();
  const id = "lutin-face-" + ++made; // each face has its own clipping of the eyes
</script>

<svg class={"lutin-face " + mood} viewBox="20 16 100 102" width={size} height={size} role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : "true"} data-mood={mood}>
  <defs>
    <linearGradient id={id + "-hat"} x1="0.1" y1="0" x2="0.9" y2="1">
      <stop offset="0" stop-color="#7cf0b4" />
      <stop offset="0.55" stop-color="#2fc08f" />
      <stop offset="1" stop-color="#157a66" />
    </linearGradient>
    <linearGradient id={id + "-brim"} x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#1a9477" />
      <stop offset="0.5" stop-color="#5ee0a6" />
      <stop offset="1" stop-color="#1a9477" />
    </linearGradient>
    <clipPath id={id + "-left"}><circle cx="49" cy="108" r="9.5" /></clipPath>
    <clipPath id={id + "-right"}><circle cx="79" cy="108" r="9.5" /></clipPath>
  </defs>
  <g class="body">
    <path d="M28 92 C32 62 46 38 70 30 C84 25 94 28 100 34 C88 36 82 46 84 62 C85 74 90 84 98 92 Z" fill={"url(#" + id + "-hat)"} />
    <path d="M84 62 C85 74 90 84 98 92 L74 92 C80 82 82 72 84 62 Z" fill="#0b3d36" opacity="0.28" />
    <path d="M33 80 C52 86 78 86 94 80 L97 90 C78 97 48 97 30 90 Z" fill="#0e1722" opacity="0.55" />
    <ellipse cx="64" cy="96" rx="44" ry="10" fill={"url(#" + id + "-brim)"} />
    <ellipse cx="64" cy="94.6" rx="40" ry="7" fill="#0b0f14" opacity="0.22" />
  </g>
  {#each [["left", 49], ["right", 79]] as [side, x] (side)}
    <g class={"eye " + side} clip-path={"url(#" + id + "-" + side + ")"}>
      <circle cx={x} cy="108" r="9.5" fill="#f4fff9" />
      <g class="pupil">
        <circle cx={Number(x) + 2.5} cy="109.5" r="4.8" fill="#0b0f14" />
        <circle cx={Number(x) + 4.4} cy="107.4" r="1.7" fill="#ffffff" />
      </g>
      <rect class="lid top" x={Number(x) - 12} y="86" width="24" height="12.5" rx="2" fill="#1a9477" style={"transform-origin: " + x + "px 108px"} />
      <ellipse class="lid bottom" cx={x} cy="124" rx="13" ry="7" fill="#1a9477" style={"transform-origin: " + x + "px 108px"} />
    </g>
  {/each}
  <g class="sparkle">
    <path d="M100 18 L103 28 L113 31 L103 34 L100 44 L97 34 L87 31 L97 28 Z" fill="#fff1c9" />
    <circle cx="100" cy="31" r="4" fill="#ffd98a" />
  </g>
  {#if mood === "sleep"}<text class="zzz" x="104" y="60" font-size="14" font-weight="700" fill="#7cf0b4">z</text>{/if}
</svg>

<style>
  .lutin-face {
    flex: none;
    overflow: visible;
  }

  .pupil,
  .lid,
  .sparkle,
  .body,
  .zzz {
    transform-box: view-box;
    transition: transform 0.45s cubic-bezier(0.3, 0.7, 0.3, 1.2);
  }

  .sparkle {
    transform-origin: 100px 31px;
  }

  .body {
    transform-origin: 64px 100px;
  }

  /* idle: a blink every few seconds, and the eyes look around now and then */
  .idle .lid.top {
    animation: blink 5.2s infinite;
  }

  .idle .pupil {
    animation: glance 11s ease-in-out infinite;
  }

  /* thinking: the eyes go up and search, the sparkle twinkles */
  .thinking .pupil {
    animation: search 2.6s ease-in-out infinite;
  }

  .thinking .lid.top {
    animation: blink 3.1s infinite;
  }

  .thinking .sparkle {
    animation: twinkle 1.3s ease-in-out infinite;
  }

  /* happy: the lower lids rise into smiling eyes, a small hop */
  .happy .lid.bottom {
    transform: translateY(-9px);
  }

  .happy .pupil {
    transform: translateY(-1.5px);
  }

  .happy .body {
    animation: hop 0.9s ease-in-out 2;
  }

  .happy .sparkle {
    animation: twinkle 0.8s ease-in-out 3;
  }

  /* worried: lids a little down on the outside, eyes that move fast */
  .worried .left .lid.top {
    transform: translateY(5px) rotate(-10deg);
  }

  .worried .right .lid.top {
    transform: translateY(5px) rotate(10deg);
  }

  .worried .pupil {
    animation: fidget 1.6s ease-in-out infinite;
  }

  /* sad: lids low on the outside, eyes down */
  .sad .left .lid.top {
    transform: translateY(8px) rotate(-18deg);
  }

  .sad .right .lid.top {
    transform: translateY(8px) rotate(18deg);
  }

  .sad .pupil {
    transform: translate(-1px, 2.5px);
  }

  /* angry: lids low on the inside (a frown) */
  .angry .left .lid.top {
    transform: translateY(8px) rotate(22deg);
  }

  .angry .right .lid.top {
    transform: translateY(8px) rotate(-22deg);
  }

  .angry .sparkle {
    animation: shake 0.5s ease-in-out 3;
  }

  /* asleep (the model is not loaded): eyes closed, slow breathing, a « z » that floats away */
  .sleep .lid.top {
    transform: translateY(19px);
  }

  .sleep .body {
    animation: breathe 3.6s ease-in-out infinite;
  }

  .zzz {
    animation: float 2.4s ease-out infinite;
  }

  @keyframes blink {
    0%,
    92%,
    100% {
      transform: translateY(0);
    }
    95% {
      transform: translateY(19px);
    }
  }

  @keyframes glance {
    0%,
    30%,
    100% {
      transform: translate(0, 0);
    }
    38%,
    52% {
      transform: translate(-3.5px, -0.5px);
    }
    60%,
    74% {
      transform: translate(1.5px, 1px);
    }
  }

  @keyframes search {
    0%,
    100% {
      transform: translate(-2.5px, -3px);
    }
    50% {
      transform: translate(2px, -3.5px);
    }
  }

  @keyframes fidget {
    0%,
    100% {
      transform: translate(-2px, 0);
    }
    50% {
      transform: translate(1.5px, 0.5px);
    }
  }

  @keyframes twinkle {
    0%,
    100% {
      transform: scale(1) rotate(0deg);
      opacity: 1;
    }
    50% {
      transform: scale(1.25) rotate(20deg);
      opacity: 0.75;
    }
  }

  @keyframes hop {
    0%,
    100% {
      transform: translateY(0);
    }
    40% {
      transform: translateY(-4px);
    }
  }

  @keyframes shake {
    0%,
    100% {
      transform: rotate(0deg);
    }
    25% {
      transform: rotate(-12deg);
    }
    75% {
      transform: rotate(12deg);
    }
  }

  @keyframes breathe {
    0%,
    100% {
      transform: scale(1);
    }
    50% {
      transform: scale(1.03);
    }
  }

  @keyframes float {
    0% {
      transform: translate(0, 0);
      opacity: 0;
    }
    20% {
      opacity: 1;
    }
    100% {
      transform: translate(6px, -14px);
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .lutin-face * {
      animation: none !important;
      transition: none !important;
    }
  }
</style>
