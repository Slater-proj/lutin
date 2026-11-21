// What the list of conversations says of each one (docs/modernization/PARITY.md, item 4): an answer is being written, it waits for you (an approval),
// or it changed since you last opened it. « Seen » is kept per browser (localStorage), never sent anywhere. Pure functions, tested in marks.test.ts.

export type Mark = "working" | "waiting" | "unread" | null;

/** The mark of one conversation: waiting for you wins, then working, then unread (changed since it was last seen, and not the one open). */
export function markOf(id: string, updated: string, active: readonly string[], waiting: readonly string[], seen: Record<string, string>, open: string | null): Mark {
  if (waiting.includes(id)) return "waiting";
  if (active.includes(id)) return "working";
  if (id !== open && seen[id] !== undefined && updated > seen[id]) return "unread";
  return null;
}

const KEY = "lutin.seen";

export function readSeen(storage: Pick<Storage, "getItem"> | null = safeStorage()): Record<string, string> {
  try {
    const value: unknown = JSON.parse(storage?.getItem(KEY) ?? "{}");
    return value && typeof value === "object" ? (value as Record<string, string>) : {};
  } catch {
    return {};
  }
}

/** Remembers that the conversation was seen as it is now. Only the 500 most recent are kept. */
export function markSeen(id: string, updated: string, storage: Pick<Storage, "getItem" | "setItem"> | null = safeStorage()): Record<string, string> {
  const seen = { ...readSeen(storage), [id]: updated };
  const kept = Object.fromEntries(Object.entries(seen).sort((a, b) => (a[1] < b[1] ? 1 : -1)).slice(0, 500));
  try {
    storage?.setItem(KEY, JSON.stringify(kept));
  } catch {
    /* a private window or blocked storage: the marks are just not remembered */
  }
  return kept;
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The title of the browser tab: « ⏳ » while an answer is being written (or waits for an approval), « ✅ » when one ended while the tab was hidden and
 * has not been seen yet, so that the person sees from another tab that Lutin works or is done (maintainer, 2026-11-21). */
export function tabTitle(base: string, active: readonly string[], waiting: readonly string[], doneUnseen: boolean): string {
  if (waiting.length) return "✋ " + base;
  if (active.length) return "⏳ " + base;
  return doneUnseen ? "✅ " + base : base;
}
