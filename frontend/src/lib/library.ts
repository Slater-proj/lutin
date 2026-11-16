// The library of an engine (Hugging Face for llama.cpp) as the Models screen sends it. Pure functions (tested in library.test.ts).

export type FitLevel = "comfortable" | "good" | "tight" | "too_big";

export interface LibraryFile {
  file: string;
  size_bytes: number;
  fit: { level: FitLevel; text: string } | null;
}

const base = (engine: string): string => `/engines/${encodeURIComponent(engine)}/library`;

export const searchPath = (engine: string, query: string): string => `${base(engine)}?q=${encodeURIComponent(query.trim())}`;
export const filesPath = (engine: string, repo: string): string => `${base(engine)}/files?repo=${encodeURIComponent(repo)}`;
export const downloadPath = (engine: string): string => `${base(engine)}/download`;

/** A quantisation the machine cannot hold is not offered for download; one whose size or fit is unknown still is (the person decides). */
export function canDownload(file: LibraryFile): boolean {
  return file.fit?.level !== "too_big";
}

/** The body of a download: `confirm` is sent only once the person said yes. */
export function downloadBody(repo: string, file: LibraryFile, confirm: boolean): { repo: string; file: string; confirm: boolean } {
  return { repo, file: file.file, confirm };
}

/** The part of a repository name that a person reads first: « author/Qwen3-8B-GGUF » → « Qwen3-8B » (the format suffix is noise in a list of GGUF files). */
export function shortName(repo: string): string {
  const name = repo.includes("/") ? repo.slice(repo.indexOf("/") + 1) : repo;
  return name.replace(/[-_.]?gguf$/i, "") || name;
}
