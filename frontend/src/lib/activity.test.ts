import { describe, expect, it } from "vitest";
import { closeKey, fraction, nextDelay, percent, visible, type ActivityItem } from "./activity";

function item(over: Partial<ActivityItem> = {}): ActivityItem {
  return { id: "engine:x", kind: "engine", name: "X", action: "install", state: "running", text: "", done: 0, total: 0, finished_at: 0, ...over };
}

describe("fraction and percent", () => {
  it("reads how far a task is, and says nothing when its size is unknown", () => {
    expect(fraction(item({ done: 3, total: 12 }))).toBe(0.25);
    expect(percent(item({ done: 3, total: 12 }))).toBe("25 %");
    expect(fraction(item({ done: 0, total: 0 }))).toBeNull();
    expect(percent(item({ done: 5, total: 0 }))).toBe("");
  });

  it("never goes past the ends", () => {
    expect(fraction(item({ done: 20, total: 10 }))).toBe(1);
    expect(fraction(item({ done: -4, total: 10 }))).toBe(0);
  });
});

describe("visible", () => {
  it("puts what runs first and hides only what the person closed", () => {
    const failed = item({ id: "engine:a", state: "failed", finished_at: 100, text: "no space" });
    const running = item({ id: "model:b", kind: "model", state: "running" });
    const done = item({ id: "engine:c", state: "done", finished_at: 200 });
    expect(visible([failed, running, done], new Set()).map((entry) => entry.id)).toEqual(["model:b", "engine:a", "engine:c"]);
    expect(visible([failed, running, done], new Set([closeKey(failed)])).map((entry) => entry.id)).toEqual(["model:b", "engine:c"]);
  });

  it("shows a task that fails again after the error was closed", () => {
    const first = item({ state: "failed", finished_at: 100 });
    const again = item({ state: "failed", finished_at: 300 });
    expect(visible([again], new Set([closeKey(first)]))).toHaveLength(1);
  });

  it("never hides a task that runs, even when the same id was closed before", () => {
    const old = item({ state: "failed", finished_at: 100 });
    expect(visible([item()], new Set([closeKey(old), closeKey(item())]))).toHaveLength(1);
  });
});

describe("nextDelay", () => {
  it("asks quickly while something runs and slowly when nothing does", () => {
    expect(nextDelay([item()])).toBe(1500);
    expect(nextDelay([item({ state: "done", finished_at: 1 })])).toBe(4000);
    expect(nextDelay([])).toBe(6000);
  });
});
