import { describe, expect, it } from "vitest";
import { after, currentEngine, engineStep, working, type EngineView } from "./setup";

function engine(extra: Partial<EngineView> = {}): EngineView {
  const no = { possible: false, reason: "" };
  return {
    id: "ollama",
    name: "Ollama",
    current: true,
    installed: true,
    running: true,
    version: "1",
    actions: { install: no, uninstall: no, reinstall: no, start: no, stop: no, update: no },
    task: null,
    ...extra,
  };
}

describe("the engine step", () => {
  it("has nothing to do when the engine runs", () => {
    expect(engineStep(engine())).toBe("ready");
  });

  it("starts an installed engine that is stopped, and installs one that is missing", () => {
    const yes = { possible: true, reason: "" };
    const no = { possible: false, reason: "" };
    expect(engineStep(engine({ running: false, actions: { ...engine().actions, start: yes } }))).toBe("start");
    expect(engineStep(engine({ running: false, installed: false, actions: { ...engine().actions, install: yes, start: no } }))).toBe("install");
  });

  it("leaves it to the person when the page can do nothing, rather than offering what cannot work", () => {
    expect(engineStep(engine({ running: false }))).toBe("blocked");
    expect(engineStep(engine({ running: false, installed: false }))).toBe("blocked");
    expect(engineStep(undefined)).toBe("blocked");
  });
});

describe("the tasks and the steps", () => {
  it("knows when a task is still going", () => {
    expect(working(engine({ task: { action: "install", state: "running", text: "", done: 0, total: 0, error: "", result: "" } }))).toBe(true);
    expect(working(engine({ task: { action: "install", state: "failed", text: "", done: 0, total: 0, error: "x", result: "" } }))).toBe(false);
    expect(working(engine())).toBe(false);
  });

  it("takes the engine in use, or the first one", () => {
    expect(currentEngine([engine({ id: "a", current: false }), engine({ id: "b", current: true })])?.id).toBe("b");
    expect(currentEngine([engine({ id: "a", current: false })])?.id).toBe("a");
    expect(currentEngine([])).toBeUndefined();
  });

  it("goes forward and stops at the end", () => {
    expect(after("welcome")).toBe("engine");
    expect(after("model")).toBe("done");
    expect(after("done")).toBe("done");
  });
});
