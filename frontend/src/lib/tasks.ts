// The scheduled tasks as the Agents screen says them. Pure functions (tested in tasks.test.ts).

export type RunState = "never" | "running" | "ok" | "failed" | "stopped" | "interrupted";

export interface ScheduledTask {
  id: string;
  name: string;
  request: string;
  time: string;
  days: number[];
  date: string;
  notify: string;
  active: boolean;
  next_run: string;
  running: boolean;
  last_run_at: string;
  last_state: RunState;
  last_error: string;
  conversation: string;
  history: { at: string; state: RunState; seconds: number; error: string }[];
}

/** Monday is 0, as the server says it. The names come from the browser, in the language of the page. */
export function dayName(day: number, lang: string): string {
  return new Date(2024, 0, 1 + day).toLocaleDateString(lang, { weekday: "short" });
}

/** « Mon, Tue, Wed » ; « every day » when all seven are chosen is left to the caller (it has the word in its language). */
export function dayList(days: number[], lang: string): string {
  return [...days].sort((a, b) => a - b).map((day) => dayName(day, lang)).join(", ");
}

export function isEveryDay(days: number[]): boolean {
  return new Set(days).size === 7;
}

/** The days a form sends: the checked ones, in order, without doubles. */
export function chosenDays(checked: boolean[]): number[] {
  return checked.flatMap((on, day) => (on ? [day] : []));
}

/** « 2026-12-31T07:00 » → « 2026-12-31 07:00 ». */
export function shownMoment(iso: string): string {
  return iso.replace("T", " ").slice(0, 16);
}
