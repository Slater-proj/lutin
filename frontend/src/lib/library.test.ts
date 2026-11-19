import { describe, expect, it } from "vitest";
import { canDownload, downloadBody, downloadPath, filesPath, libraryQuery, searchPath, shortName, sizesShown, type LibraryFile } from "./library";

const file = (fit: LibraryFile["fit"]): LibraryFile => ({ file: "m-q4.gguf", size_bytes: 1000, fit });

describe("paths", () => {
  it("encode the engine, the words and the repository", () => {
    expect(searchPath("llamacpp", " qwen 3 ")).toBe("/engines/llamacpp/library?q=qwen%203");
    expect(filesPath("llamacpp", "author/Qwen3-GGUF")).toBe("/engines/llamacpp/library/files?repo=author%2FQwen3-GGUF");
    expect(downloadPath("a b")).toBe("/engines/a%20b/library/download");
  });
});

describe("canDownload", () => {
  it("refuses only what the machine cannot hold", () => {
    expect(canDownload(file({ level: "too_big", text: "" }))).toBe(false);
    for (const level of ["comfortable", "good", "tight"] as const) expect(canDownload(file({ level, text: "" }))).toBe(true);
    expect(canDownload(file(null))).toBe(true);
  });
});

describe("downloadBody", () => {
  it("carries the repository, the file and the confirmation", () => {
    expect(downloadBody("a/b", file(null), false)).toEqual({ repo: "a/b", file: "m-q4.gguf", confirm: false });
    expect(downloadBody("a/b", file(null), true).confirm).toBe(true);
  });
});

describe("shortName", () => {
  it("drops the author and the GGUF suffix", () => {
    expect(shortName("author/Qwen3-8B-GGUF")).toBe("Qwen3-8B");
    expect(shortName("bartowski/gemma_gguf")).toBe("gemma");
    expect(shortName("noauthor")).toBe("noauthor");
    expect(shortName("a/GGUF")).toBe("GGUF");
  });
});

describe("the Ollama library filters", () => {
  it("adds the word the uncensored models carry, alone or after the typed words", () => {
    expect(libraryQuery("  qwen ", false)).toBe("qwen");
    expect(libraryQuery("", true)).toBe("uncensored");
    expect(libraryQuery("qwen", true)).toBe("qwen uncensored");
  });

  it("keeps the tight sizes and hides the too big ones only when asked", () => {
    const sizes = [{ size: "4b", fit: { level: "good" } }, { size: "27b", fit: { level: "tight" } }, { size: "70b", fit: { level: "too_big" } }, { size: "1b", fit: null }];
    expect(sizesShown(sizes, true).map((s) => s.size)).toEqual(["4b", "27b", "1b"]);
    expect(sizesShown(sizes, false)).toHaveLength(4);
  });
});
