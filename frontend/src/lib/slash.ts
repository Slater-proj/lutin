// The commands typed in the Chat (« /compact », « /web off »…) and those of a Claude project (docs/modernization/PARITY.md, item 15). Pure functions,
// tested in slash.test.ts: what is typed becomes a known command with its argument, or a command of the project, or nothing. The French names of the
// old page are kept as aliases, so a habit does not break.

export type CommandName = "help" | "new" | "compact" | "stop" | "retry" | "git" | "health" | "model" | "mode" | "memory" | "think" | "web" | "files" | "commands";

export type Command = { name: CommandName; aliases: readonly string[]; arg?: string };

export const COMMANDS: readonly Command[] = [
  { name: "help", aliases: ["aide", "?"] },
  { name: "new", aliases: ["clear", "nouveau"] },
  { name: "compact", aliases: [] },
  { name: "stop", aliases: [] },
  { name: "retry", aliases: ["regenerer"] },
  { name: "git", aliases: [] },
  { name: "health", aliases: ["sante"] },
  { name: "model", aliases: ["modele"], arg: "name" },
  { name: "mode", aliases: [], arg: "general|technical|scenario|research|chat" },
  { name: "memory", aliases: ["memoire"], arg: "summary|sheet|general" },
  { name: "think", aliases: ["reflexion"], arg: "on|off" },
  { name: "web", aliases: [], arg: "on|off" },
  { name: "files", aliases: ["fichiers", "accord"], arg: "on|off" },
  { name: "commands", aliases: ["commandes"], arg: "on|off" },
];

/** The French mode names of the old page, and the v1 ones. */
export const MODE_NAMES: Record<string, string> = {
  general: "general", polyvalent: "general", technical: "technical", code: "technical", scenario: "scenario", ecriture: "scenario", research: "research", recherche: "research",
  chat: "chat", discussion: "chat",
};

/** `summary`, `sheet` or null (the general setting), from the v1 or French names; undefined when it is none of them. */
export function memoryMode(arg: string): "summary" | "sheet" | null | undefined {
  const value = arg.trim().toLowerCase();
  if (["summary", "resume", "résumé"].includes(value)) return "summary";
  if (["sheet", "fichier", "fiche"].includes(value)) return "sheet";
  if (["general", "demander", "ask", ""].includes(value)) return null;
  return undefined;
}

/** true for on/oui/yes/1, false for off/non/no/0, null otherwise. */
export function onOff(arg: string): boolean | null {
  const value = arg.trim().toLowerCase();
  if (["on", "oui", "yes", "1"].includes(value)) return true;
  if (["off", "non", "no", "0"].includes(value)) return false;
  return null;
}

export type Parsed = { kind: "command"; command: CommandName; arg: string } | { kind: "project"; name: string; arg: string } | { kind: "unknown"; name: string };

/** What a message that starts with « / » asks for; null for an ordinary message (or « // », which sends a slash on purpose). */
export function parse(text: string, projectCommands: readonly string[] = []): Parsed | null {
  const typed = text.trim();
  if (!typed.startsWith("/") || typed.startsWith("//") || typed.length === 1) return null;
  const space = typed.search(/\s/);
  const name = (space < 0 ? typed.slice(1) : typed.slice(1, space)).toLowerCase();
  const arg = space < 0 ? "" : typed.slice(space + 1).trim();
  const known = COMMANDS.find((command) => command.name === name || command.aliases.includes(name));
  if (known) return { kind: "command", command: known.name, arg };
  const project = projectCommands.find((command) => command.toLowerCase() === name);
  if (project) return { kind: "project", name: project, arg };
  return { kind: "unknown", name };
}

/** The commands that begin with what is typed after « / » (before any space), known ones first, then the project's. */
export function suggest(text: string, projectCommands: readonly string[] = []): { name: string; project: boolean; arg?: string }[] {
  const typed = text.trimStart();
  if (!typed.startsWith("/") || /\s/.test(typed)) return [];
  const start = typed.slice(1).toLowerCase();
  const known = COMMANDS.filter((command) => command.name.startsWith(start) || command.aliases.some((alias) => alias.startsWith(start))).map((command) => ({ name: command.name, project: false, arg: command.arg }));
  const project = projectCommands.filter((name) => name.toLowerCase().startsWith(start)).map((name) => ({ name, project: true }));
  return [...known, ...project].slice(0, 12);
}
