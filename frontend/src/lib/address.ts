// The part of a screen named in the address after the area: `#/agents/missions` is the tab « missions » of the Agents screen (App.svelte reads
// the first segment, the area). Pure function, tested in address.test.ts.

/** The page named in `hash` if it is one of `pages`, or null (the screen then shows its first one). */
export function pageOf<T extends string>(hash: string, pages: readonly T[]): T | null {
  const name = hash.replace(/^#\/?/, "").split("/")[1] ?? "";
  return (pages as readonly string[]).includes(name) ? (name as T) : null;
}
