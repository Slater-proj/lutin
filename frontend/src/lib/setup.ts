// The guide of the first launch: what the page decides from the answers of the server. Pure functions (tested in setup.test.ts).

export interface EngineAction {
  possible: boolean;
  reason: string;
}

export interface EngineTask {
  action: string;
  state: "running" | "done" | "failed";
  text: string;
  done: number;
  total: number;
  error: string;
  result: string;
}

export interface EngineView {
  id: string;
  /** What the daily check knows of a newer version (null until it ran). */
  update?: { current: string; latest: string; available: boolean } | null;
  name: string;
  current: boolean;
  installed: boolean;
  running: boolean;
  version: string;
  description: string;
  detail: string;
  strengths: string[];
  weaknesses: string[];
  /** Whether it can run on this machine (system, graphics card, Docker) and, when not, why. */
  runs_here: { possible: boolean; reason: string };
  actions: Record<"install" | "uninstall" | "reinstall" | "start" | "stop" | "update", EngineAction>;
  task: EngineTask | null;
}

export type Step = "welcome" | "engine" | "model" | "done";
export const STEPS: readonly Step[] = ["welcome", "engine", "model", "done"];

/** What the engine step offers: nothing to do, start it, install it, or nothing the page can do (the person does it by hand). */
export type EngineStep = "ready" | "start" | "install" | "blocked";

export function engineStep(engine: EngineView | undefined): EngineStep {
  if (!engine) return "blocked";
  if (engine.running) return "ready";
  if (engine.installed && engine.actions.start.possible) return "start";
  if (!engine.installed && engine.actions.install.possible) return "install";
  return "blocked";
}

/** Whether a task of this engine is still going: the page asks again while it is. */
export function working(engine: EngineView | undefined): boolean {
  return engine?.task?.state === "running";
}

/** The engine the guide is about: the one in use. */
export function currentEngine(engines: EngineView[]): EngineView | undefined {
  return engines.find((engine) => engine.current) ?? engines[0];
}

/** The next step, or the same one at the end. */
export function after(step: Step): Step {
  return STEPS[Math.min(STEPS.indexOf(step) + 1, STEPS.length - 1)];
}
