// The models of an engine as the Models screen asks for them, the same way for every engine (ADR 0020): `/engines/{id}/models*`. Pure functions
// (tested in library.test.ts).

export type FitLevel = "comfortable" | "good" | "tight" | "too_big";
export type Fit = { level: FitLevel | string; text: string } | null;

/** One model, whatever the engine and the list (lutin.model_sources.entry). */
export interface Entry {
  id: string;
  name: string;
  revision: string;
  size_gb: number | null;
  approximate: boolean;
  fit: Fit;
  installed: boolean;
  in_use: boolean;
  summary: string;
  download: { possible: boolean; reason: string };
  has_variants: boolean;
  incomplete: boolean;
  removable: boolean;
  strengths?: string[]; // the roles it is good at, when the source rates them (the catalogue of Lutin)
}

export interface SearchOptions {
  words: string;
  page?: number;
  order?: "recent" | "popular";
  community?: boolean;
  capability?: string;
}

const base = (engine: string): string => `/engines/${encodeURIComponent(engine)}/models`;

export const installedPath = (engine: string): string => base(engine);
export const recommendedPath = (engine: string): string => `${base(engine)}/recommended`;
export const variantsPath = (engine: string, ref: string): string => `${base(engine)}/variants?ref=${encodeURIComponent(ref)}`;
export const downloadPath = (engine: string): string => `${base(engine)}/downloads`;
export const checkPath = (engine: string): string => `${base(engine)}/check`;
export const removePath = (engine: string, name: string): string => `${base(engine)}/${encodeURIComponent(name)}`;

/** The search: only what is asked is sent (the order, the other authors, a capability), so that the server's defaults hold otherwise. */
export function searchPath(engine: string, options: SearchOptions): string {
  const query = new URLSearchParams({ q: options.words.trim(), page: String(options.page ?? 1) });
  if (options.order && options.order !== "recent") query.set("order", options.order);
  if (options.community) query.set("community", "1");
  if (options.capability) query.set("capability", options.capability);
  return `${base(engine)}/search?${query.toString()}`;
}

/** A model is offered for download only when the server says it can be; otherwise its reason is shown instead of the button. */
export function canDownload(entry: Pick<Entry, "download">): boolean {
  return entry.download.possible;
}

/** The body of a download: `confirm` is sent only once the person said yes; `revision` only when there is one to take. */
export function downloadBody(ref: string, revision: string, confirm: boolean): { ref: string; revision?: string; confirm: boolean } {
  return revision ? { ref, revision, confirm } : { ref, confirm };
}

/** What a person reads of a download: the name, then the precision after « @ » when there is one. */
export const downloadLabel = (ref: string, revision: string): string => ref + (revision ? " @ " + revision : "");

/** The part of a repository name that a person reads first: « author/Qwen3-8B-GGUF » → « Qwen3-8B » (the format suffix is noise in a list of GGUF files). */
export function shortName(repo: string): string {
  const name = repo.includes("/") ? repo.slice(repo.indexOf("/") + 1) : repo;
  return name.replace(/[-_.]?gguf$/i, "") || name;
}

/** The words sent to ollama.com: with « uncensored » ticked, the word that the site's uncensored models carry in their name or description. */
export function libraryQuery(words: string, uncensored: boolean): string {
  const typed = words.trim();
  return uncensored ? (typed ? typed + " uncensored" : "uncensored") : typed;
}

/** The models to show: all of them, or (« suited to my machine ») those that are not too big, the tight ones included. */
export function sizesShown<T extends { fit: { level: string } | null }>(sizes: T[], fitsHere: boolean): T[] {
  return fitsHere ? sizes.filter((size) => size.fit?.level !== "too_big") : sizes;
}

/** The key of an entry in a list: the same repository can be offered with several files. */
export const entryKey = (entry: Pick<Entry, "id" | "revision">): string => entry.id + "@" + entry.revision;

/** The precision to take when a model has several (maintainer, 2026-11-22: « je vois des modèles mais pas de bouton pour les télécharger »): the
 *  heaviest that runs « comfortable » or « good » here and can be downloaded, as the recommendations of the server choose (the larger is the more
 *  capable). null when none does: the list is then shown without advice. */
export function bestVariant<T extends Pick<Entry, "size_gb" | "fit" | "download" | "installed">>(variants: readonly T[]): T | null {
  const fitting = variants.filter((variant) => (variant.fit?.level === "comfortable" || variant.fit?.level === "good") && variant.download.possible && !variant.installed);
  return fitting.reduce<T | null>((best, variant) => (best === null || (variant.size_gb ?? 0) > (best.size_gb ?? 0) ? variant : best), null);
}
