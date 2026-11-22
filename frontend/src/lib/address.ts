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

// The tabs of the old page (`/#modeles`, `/#memoire`…) and its direct link to a conversation (`/#conv=<id>`): a bookmark made before 1.0 still leads
// to the same place in the new interface.
const LEGACY_TABS: Record<string, string> = {
  chat: "#/chat", modeles: "#/models", machines: "#/models/machines", reglages: "#/settings", memoire: "#/settings/knowledge", sante: "#/settings/health",
  acces: "#/settings/devices", auto: "#/agents",
};

/** The address of the new interface for a hash of the old page, or null when it is not one (it is then left as it is). */
export function fromLegacy(hash: string): string | null {
  const name = decodeURIComponent(hash.replace(/^#/, ""));
  if (name.startsWith("/") || !name) return null;
  const conversation = /^conv=([0-9a-f]{8})$/.exec(name);
  if (conversation) return "#/chat/" + conversation[1];
  return LEGACY_TABS[name] ?? null;
}
