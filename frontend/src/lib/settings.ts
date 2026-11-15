// The settings of Lutin on the Settings screen: which ones, in which groups, and how a typed value becomes what the server takes.
// The names are the ones of /api/v1/settings. Pure functions (tested in settings.test.ts); the texts are in messages.ts under `settings.*`.

export type GroupId = "answers" | "safety" | "knowledge" | "machine" | "tools" | "sampling";
export const GROUPS: readonly GroupId[] = ["answers", "safety", "knowledge", "machine", "tools", "sampling"];

export type Field = {
  name: string;
  group: GroupId;
  kind: "boolean" | "number" | "integer" | "select" | "strings" | "text";
  options?: readonly string[];
  min?: number;
  max?: number;
  step?: number;
  /** An empty box means « chosen by Lutin » (the server takes null). */
  nullable?: boolean;
  /** Something that changes what Lutin may do without asking: shown with a warning. */
  risky?: boolean;
};

export const FIELDS: readonly Field[] = [
  { name: "mode", group: "answers", kind: "select", options: ["general", "technical", "scenario", "research", "chat"] },
  { name: "thinking", group: "answers", kind: "boolean" },
  { name: "thinking_steps", group: "answers", kind: "select", options: ["always", "first"] },
  { name: "max_steps", group: "answers", kind: "integer", min: 4, max: 40 },
  { name: "num_ctx", group: "answers", kind: "integer", min: 4096, max: 131072, step: 1024 },
  { name: "num_predict", group: "answers", kind: "integer", min: 0, max: 32768, step: 256 },
  { name: "temperature", group: "answers", kind: "number", min: 0, max: 2, step: 0.1 },
  { name: "advanced", group: "answers", kind: "boolean" },

  { name: "auto_approve_writes", group: "safety", kind: "boolean", risky: true },
  { name: "auto_approve_commands", group: "safety", kind: "boolean", risky: true },
  { name: "dry_run", group: "safety", kind: "boolean" },
  { name: "commands_without_approval", group: "safety", kind: "strings", risky: true },
  { name: "disabled_tools", group: "safety", kind: "strings" },

  { name: "web", group: "knowledge", kind: "boolean" },
  { name: "long_memory", group: "knowledge", kind: "select", options: ["ask", "summary", "file"] },
  { name: "auto_recall", group: "knowledge", kind: "select", options: ["scenario", "always", "never"] },
  { name: "semantic_search", group: "knowledge", kind: "boolean" },
  { name: "embedding_model", group: "knowledge", kind: "text" },
  { name: "conversation_backup", group: "knowledge", kind: "boolean" },

  { name: "memory_budget_gb", group: "machine", kind: "number", min: 0, max: 4096, step: 0.5 },
  { name: "resource_guard", group: "machine", kind: "boolean" },
  { name: "ram_threshold_gb", group: "machine", kind: "number", min: 0.5, max: 64, step: 0.5 },
  { name: "disk_threshold_gb", group: "machine", kind: "number", min: 1, max: 2000, step: 1 },
  { name: "data_cap_gb", group: "machine", kind: "number", min: 0.2, max: 500, step: 0.1 },
  { name: "command_ram_limit_gb", group: "machine", kind: "number", min: 0, max: 256, step: 0.5 },
  { name: "free_for_comfyui", group: "machine", kind: "boolean" },
  { name: "machine_advice", group: "machine", kind: "boolean" },
  { name: "routing", group: "machine", kind: "boolean" },
  { name: "num_thread", group: "machine", kind: "integer", min: 1, max: 256, nullable: true },
  { name: "keep_alive_min", group: "machine", kind: "integer", min: 0, max: 240, nullable: true },

  { name: "tool_command_timeout_s", group: "tools", kind: "integer", min: 10, max: 3600 },
  { name: "tool_search_timeout_s", group: "tools", kind: "integer", min: 1, max: 600 },
  { name: "tool_output_max", group: "tools", kind: "integer", min: 1000, max: 1000000 },
  { name: "tool_read_max", group: "tools", kind: "integer", min: 1000, max: 1000000 },
  { name: "extra_ignored_folders", group: "tools", kind: "strings" },

  { name: "top_p", group: "sampling", kind: "number", min: 0, max: 1, step: 0.05, nullable: true },
  { name: "top_k", group: "sampling", kind: "number", min: 0, max: 1000, step: 1, nullable: true },
  { name: "min_p", group: "sampling", kind: "number", min: 0, max: 1, step: 0.01, nullable: true },
  { name: "repeat_penalty", group: "sampling", kind: "number", min: 0.5, max: 2, step: 0.05, nullable: true },
];

export type Value = boolean | number | string | string[] | null;

export function fieldsOf(group: GroupId): Field[] {
  return FIELDS.filter((field) => field.group === group);
}

/** What the server takes for what was typed, or an error key when it cannot be a value of this field. Empty = null for a field that allows it. */
export function parseTyped(field: Field, raw: string): { ok: true; value: Value } | { ok: false; error: "number" | "range" } {
  if (field.kind === "strings") {
    return { ok: true, value: raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) };
  }
  if (field.kind === "text") {
    return { ok: true, value: raw.trim() };
  }
  if (field.kind !== "number" && field.kind !== "integer") {
    return { ok: true, value: raw };
  }
  if (raw.trim() === "") {
    return field.nullable ? { ok: true, value: null } : { ok: false, error: "number" };
  }
  const value = Number(raw.replace(",", "."));
  if (!Number.isFinite(value) || (field.kind === "integer" && !Number.isInteger(value))) return { ok: false, error: "number" };
  if ((field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max)) return { ok: false, error: "range" };
  return { ok: true, value };
}

/** What a box shows for a stored value. */
export function shown(field: Field, value: Value | undefined): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join("\n");
  return String(value);
}
