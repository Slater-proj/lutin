// The part of a screen named in the address after the area: `#/agents/missions` is the tab « missions » of the Agents screen (App.svelte reads
// the first segment, the area). Pure function, tested in address.test.ts.

/** The conversation of this machine named in the address (`#/chat/0123abcd`), or null: the Chat opens it, and keeps the open one there. */
export function conversationOf(hash: string): string | null {
  const match = /^#\/?chat\/([0-9a-f]{8})$/.exec(hash);
  return match ? match[1] : null;
}

/** The page named in `hash` if it is one of `pages`, or null (the screen then shows its first one). */
export function pageOf<T extends string>(hash: string, pages: readonly T[]): T | null {
  const name = hash.replace(/^#\/?/, "").split("/")[1] ?? "";
  return (pages as readonly string[]).includes(name) ? (name as T) : null;
}
