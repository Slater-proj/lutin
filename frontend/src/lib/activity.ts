// What Lutin is downloading or installing, from GET /activity: the bar at the top of every screen follows it, so that a download is seen wherever the person is
// (an engine installing, a model coming down by Ollama or by the engine in use, the model that searches by meaning).

export interface ActivityItem {
  id: string;
  kind: "engine" | "model" | "meaning" | "comfyui" | "copy";
  name: string;
  action: string; // install, reinstall, update, uninstall, start, download, prepare, copy
  state: "running" | "done" | "failed";
  text: string; // the last line of progress, or the result, or the error
  done: number;
  total: number;
  finished_at: number; // seconds since 1970 for what ended, 0 while it runs
}

/** How far a task is, from 0 to 1; null when it does not know its size (the bar then only moves, it does not claim a figure). */
export function fraction(item: Pick<ActivityItem, "done" | "total">): number | null {
  if (!(item.total > 0)) return null;
  return Math.min(1, Math.max(0, item.done / item.total));
}

/** « 21 % », or an empty text when the size is not known. */
export function percent(item: Pick<ActivityItem, "done" | "total">): string {
  const part = fraction(item);
  return part === null ? "" : Math.round(part * 100) + " %";
}

/** The tasks to show: the ones that run, then what ended and was not closed by the person (an error stays until it is closed, a success goes by itself on the server). */
export function visible(items: ActivityItem[], closed: ReadonlySet<string>): ActivityItem[] {
  const key = (item: ActivityItem): string => item.id + "@" + item.finished_at;
  return items.filter((item) => item.state === "running" || !closed.has(key(item))).sort((first, second) => Number(second.state === "running") - Number(first.state === "running"));
}

export function closeKey(item: ActivityItem): string {
  return item.id + "@" + item.finished_at;
}

/** How soon to ask again: quickly while something runs, slowly otherwise (the answer is cheap, but nothing needs a second-by-second watch when nothing happens). */
export function nextDelay(items: ActivityItem[]): number {
  return items.some((item) => item.state === "running") ? 1500 : items.length ? 4000 : 6000;
}
