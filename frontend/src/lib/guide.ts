// The guided choice of a model: what the page decides from the answers of the server. Pure functions (tested in guide.test.ts).
// The verdicts themselves come from the server (model_fit, model_compat); the page only says them, and refuses what they refuse.

export type Fit = "comfortable" | "good" | "tight" | "too_big";
export type Use = "chat" | "code" | "documents" | "unsure";
export const USES: readonly Use[] = ["chat", "code", "documents", "unsure"];

export interface Machine {
  detected: boolean;
  summary?: string;
  ram_gb?: number;
  budget_gb?: number;
  class?: "no_gpu" | "small" | "medium" | "large" | "very_large";
  gpus?: { name: string; vendor: string; memory_gb: number; integrated: boolean }[];
}

export interface CatalogModel {
  id: string;
  name: string;
  summary: string;
  size_gb: number;
  capabilities: string[];
  licence: string;
  warning: string;
  installed: boolean;
  fit: { level: Fit; text: string } | null;
  compatibility: { compatible: boolean; reasons: string[]; warnings: string[]; memory_gb: number | null };
}

export interface Choice {
  role: string;
  model: CatalogModel;
  context_tokens: number;
  memory_gb: number;
  runs_on: "gpu" | "partial" | "cpu";
}

export interface Recommendation {
  detected: boolean;
  use: Use;
  recommended?: Choice | null;
  alternatives?: Choice[];
  download?: { models: string[]; size_gb: number; free_gb: number | null; fits_on_disk: boolean | null };
  engine?: { id: string; name: string; running: boolean };
  offline?: boolean;
}

/** Why a download cannot start now, or null if it can. The order is the one a person would fix them in. */
export type Blocker = "offline" | "engine_stopped" | "incompatible" | "too_big" | "no_space" | null;

export function blocker(choice: Choice, recommendation: Recommendation): Blocker {
  if (recommendation.offline) return "offline";
  if (!choice.model.compatibility.compatible) return "incompatible";
  if (choice.model.fit?.level === "too_big") return "too_big";
  if (recommendation.engine && !recommendation.engine.running) return "engine_stopped";
  const space = freeAfter(choice, recommendation);
  if (space !== null && space < 0) return "no_space";
  return null;
}

/** The space left on the disk once this model is downloaded, or null when the disk could not be read (it is said, not guessed). */
export function freeAfter(choice: Choice, recommendation: Recommendation): number | null {
  const free = recommendation.download?.free_gb;
  if (free === null || free === undefined) return null;
  return choice.model.installed ? free : Math.round((free - choice.model.size_gb) * 10) / 10;
}

/** The verdict as one sentence: the label of the level in bold, then what the server says. The server's sentence often starts with the same words as the label
 * (« Très à l'aise sur ta machine… »): they are not said twice. */
export function splitFit(label: string, text: string): { head: string; rest: string } {
  if (text.toLowerCase().startsWith(label.toLowerCase())) return { head: text.slice(0, label.length), rest: text.slice(label.length) };
  return { head: label, rest: text ? " — " + text : "" };
}

/** Whether the model is not on the machine yet: only then does a download (and its size) make sense. */
export function needsDownload(choice: Choice): boolean {
  return !choice.model.installed;
}

/** One list for the page: the recommended model first, then the other fitting choices, each model once. */
export function choices(recommendation: Recommendation): Choice[] {
  const seen = new Set<string>();
  const out: Choice[] = [];
  for (const choice of [recommendation.recommended, ...(recommendation.alternatives ?? [])]) {
    if (choice && !seen.has(choice.model.id)) {
      seen.add(choice.model.id);
      out.push(choice);
    }
  }
  return out;
}
