import { describe, expect, it } from "vitest";
import { answerMood, moodOf } from "./lutin_mood";

const calm = { engineRunning: true, activeTurns: 0, health: "ok" as const, passing: null };

describe("moodOf", () => {
  it("follows the state of the application", () => {
    expect(moodOf(calm)).toBe("idle");
    expect(moodOf({ ...calm, engineRunning: false })).toBe("sleep");
    expect(moodOf({ ...calm, activeTurns: 1 })).toBe("thinking");
    expect(moodOf({ ...calm, health: "warning" })).toBe("worried");
    expect(moodOf({ ...calm, health: "critical" })).toBe("sad");
    expect(moodOf({ ...calm, engineRunning: null })).toBe("idle");
  });

  it("lets a moment win: an answer that ended, a failure", () => {
    expect(moodOf({ ...calm, activeTurns: 1, passing: "happy" })).toBe("happy");
    expect(moodOf({ ...calm, engineRunning: false, passing: "angry" })).toBe("angry");
  });
});

describe("answerMood", () => {
  it("sleeps while the model is loaded, thinks while it writes, stays still once done", () => {
    expect(answerMood(true, true, false)).toBe("sleep");
    expect(answerMood(true, false, false)).toBe("thinking");
    expect(answerMood(true, true, null)).toBe("thinking");
    expect(answerMood(false, false, true)).toBe("still");
  });
});
