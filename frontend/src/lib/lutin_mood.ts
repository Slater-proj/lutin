// How Lutin's eyes look, from what the page knows of the application (components/LutinFace.svelte draws them).
import type { Mood } from "../components/LutinFace.svelte";

export interface MoodFacts {
  engineRunning: boolean | null; // null: not known yet
  activeTurns: number; // answers being written on this machine
  health: "ok" | "warning" | "critical" | "";
  passing: Mood | null; // a mood of a moment: happy when an answer ended, angry when the engine failed
}

/** The most telling first: a moment (an answer that ended, a failure), then the engine asleep, then an answer being written, then the health. */
export function moodOf(facts: MoodFacts): Mood {
  if (facts.passing) return facts.passing;
  if (facts.engineRunning === false) return "sleep";
  if (facts.activeTurns > 0) return "thinking";
  if (facts.health === "critical") return "sad";
  if (facts.health === "warning") return "worried";
  return "idle";
}

/** The face of an answer in the thread: asleep while the model is being loaded and nothing is written yet, thinking while it writes, still once done. */
export function answerMood(writing: boolean, nothingYet: boolean, modelLoaded: boolean | null): Mood | "still" {
  if (!writing) return "still";
  if (nothingYet && modelLoaded === false) return "sleep";
  return "thinking";
}

/** Tells the logo of the page a mood of a moment (window event « lutin-mood »). */
export function passMood(mood: Mood): void {
  dispatchEvent(new CustomEvent("lutin-mood", { detail: mood }));
}
