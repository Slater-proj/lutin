// The catalogue of models (GET /api/v1/models/catalog): what each model is for, how it fits this machine, what it is good and less good at.
// Pure functions, tested in model_catalog.test.ts; the texts are in messages.ts under `catalog.*` and `guide.*`.

export type FitLevel = "comfortable" | "good" | "tight" | "too_big";
export const FIT_ORDER: readonly FitLevel[] = ["comfortable", "good", "tight", "too_big"];

export interface CatalogModel {
  id: string;
  name: string;
  summary: string;
  size_gb: number;
  parameters_b: number;
  active_parameters_b: number;
  context_max: number;
  capabilities: string[];
  licence: string;
  /** The editorial rating of the model for each role, out of 10. */
  roles: Record<string, number>;
  advanced: boolean;
  warning: string;
  installed: boolean;
  fit: { level: FitLevel; text: string } | null;
  compatibility: { compatible: boolean; reasons: string[]; warnings: string[]; memory_gb: number | null };
}

export const STRONG = 7; // a rating from which a role is a strength
export const WEAK = 3; // a rating up to which a role is a weakness

/** The roles a model is good at, best first, and those it is weak at. */
export function strengths(roles: Record<string, number>): { strong: string[]; weak: string[] } {
  const entries = Object.entries(roles).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return { strong: entries.filter(([, note]) => note >= STRONG).map(([role]) => role), weak: entries.filter(([, note]) => note <= WEAK).map(([role]) => role) };
}

/** Whether this machine and its engine can run the model (an unknown machine: only the engine decides). */
export function runsHere(model: CatalogModel): boolean {
  return model.compatibility.compatible && model.fit?.level !== "too_big";
}

/** The models to show: those that run here (or all), the most comfortable first, then the best rated. */
export function shown(models: CatalogModel[], only: "fits" | "all"): CatalogModel[] {
  const rank = (model: CatalogModel): number => (model.fit ? FIT_ORDER.indexOf(model.fit.level) : FIT_ORDER.length);
  const best = (model: CatalogModel): number => Math.max(0, ...Object.values(model.roles));
  return models.filter((model) => only === "all" || runsHere(model)).sort((a, b) => rank(a) - rank(b) || best(b) - best(a) || a.name.localeCompare(b.name));
}

/** The family of a model: its name before « · » (« Qwen 3 · 8 billion » → « Qwen 3 »); the models without safeguards make a family of their own. */
export function familyOf(model: CatalogModel): string {
  return model.name.split(" · ")[0].trim() + (model.advanced ? " *" : "");
}

/** The models grouped by family, in the order of `models` (the best first stays first): [{family, advanced, models}]. */
export function byFamily(models: CatalogModel[]): { family: string; advanced: boolean; models: CatalogModel[] }[] {
  const groups = new Map<string, { family: string; advanced: boolean; models: CatalogModel[] }>();
  for (const model of models) {
    const key = familyOf(model);
    if (!groups.has(key)) groups.set(key, { family: model.name.split(" · ")[0].trim(), advanced: model.advanced, models: [] });
    groups.get(key)?.models.push(model);
  }
  return [...groups.values()];
}
