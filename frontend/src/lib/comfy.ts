// The ComfyUI panel as the Agents screen sends it. Pure functions (tested in comfy.test.ts).

export type DownloadState = "idle" | "running" | "done" | "failed";

export interface ComfyPanel {
  running: boolean;
  error: string;
  version: string;
  gpu: string;
  folder: string;
  folder_set: boolean;
  folder_valid: boolean;
  folder_problem: string;
  can_launch: boolean;
  models: { source: "api" | "folder" | "none"; by_kind: Record<string, string[]> };
  families: Record<string, string>;
  family_labels: Record<string, string>;
  workflows: string[];
  engines: { image: string[]; video: string[]; sound: string[] };
  unusable_models: string[];
  download: { state: DownloadState; name: string; done_bytes: number; total_bytes: number; error: string };
  download_kinds: string[];
}

/** How many models of each kind, the kinds with none left out and the biggest first. */
export function kindCounts(byKind: Record<string, string[]>): { kind: string; count: number }[] {
  return Object.entries(byKind)
    .map(([kind, names]) => ({ kind, count: names.length }))
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind));
}

/** The share of the download that is done, 0 to 100, or null while its size is not known. */
export function downloadShare(download: ComfyPanel["download"]): number | null {
  if (!(download.total_bytes > 0)) return null;
  return Math.min(100, Math.round((download.done_bytes / download.total_bytes) * 100));
}

/** A download can be asked for when ComfyUI's folder is known and good, nothing is downloading, and an https address and a kind are given. The server checks the host. */
export function canAskDownload(panel: ComfyPanel, url: string, kind: string): boolean {
  return panel.folder_valid && panel.download.state !== "running" && /^https:\/\/\S+$/.test(url.trim()) && panel.download_kinds.includes(kind);
}

/** The body of a download; `confirm` is sent only once the person said yes. */
export function downloadBody(url: string, kind: string, confirm: boolean): { url: string; kind: string; confirm: boolean } {
  return { url: url.trim(), kind, confirm };
}
