// Third-party skills as the Settings screen sends them. Pure functions (tested in thirdskills.test.ts).

export type Severity = "none" | "attention" | "danger";

export interface Finding {
  severity: Severity;
  pattern: string;
  explanation: string;
  file: string;
  line: number;
  excerpt: string;
}

export interface SkillCard {
  repo: string;
  dir: string;
  name: string;
  description: string;
  license: string;
  license_file: boolean;
  license_repo: boolean;
  text: string;
  text_truncated: boolean;
  files: { path: string; bytes: number }[];
  file_count: number;
  bytes: number;
  scripts: string[];
  tokens: number;
  heavy: boolean;
  findings: Finding[];
  severity: Severity;
  too_big: string[];
  installable: boolean;
}

export interface Indexing {
  done: number;
  total: number;
  finished: boolean;
  error: string;
}

/** What the person has ticked: each risk has its own acceptance, one never covers the other. */
export interface Accepted {
  danger: boolean;
  noLicense: boolean;
}

/** A skill with no licence anywhere (neither in its header, nor beside it, nor at the root of its repository) is not free to reuse: installing it asks for its own acceptance. */
export function lacksLicense(card: Pick<SkillCard, "license" | "license_file" | "license_repo">): boolean {
  return !card.license && !card.license_file && !card.license_repo;
}

/** Whether the install button may be pressed: the size is allowed and every risk that was found has been accepted. */
export function canInstall(card: SkillCard, accepted: Accepted): boolean {
  if (!card.installable) return false;
  if (card.severity === "danger" && !accepted.danger) return false;
  if (lacksLicense(card) && !accepted.noLicense) return false;
  return true;
}

/** The body of an installation or an update. `confirm` is sent only once the person said yes; an empty project is left out (the server takes the current one). */
export function installBody(card: SkillCard, project: string, accepted: Accepted, confirm: boolean): Record<string, string | boolean> {
  const body: Record<string, string | boolean> = { repo: card.repo, dir: card.dir, confirm, accept_danger: accepted.danger && card.severity === "danger", accept_no_license: accepted.noLicense && lacksLicense(card) };
  if (project) body.project = project;
  return body;
}

/** The address of a search: only what was filled in is sent. */
export function searchPath(query: string, repos: string[], page: number): string {
  const parts: string[] = [];
  if (query.trim()) parts.push("q=" + encodeURIComponent(query.trim()));
  if (repos.length > 0) parts.push("repos=" + repos.map(encodeURIComponent).join(","));
  if (page > 1) parts.push("page=" + page);
  return "/third-party-skills/search" + (parts.length > 0 ? "?" + parts.join("&") : "");
}

/** The reading of the descriptions as one figure for all the sources: whether one is still running, and how far it is. */
export function indexingProgress(indexing: Record<string, Indexing>): { running: boolean; done: number; total: number; error: string } {
  let done = 0;
  let total = 0;
  let running = false;
  let error = "";
  for (const state of Object.values(indexing)) {
    done += state.done;
    total += state.total;
    if (!state.finished) running = true;
    if (state.error && !error) error = state.error;
  }
  return { running, done, total, error };
}
