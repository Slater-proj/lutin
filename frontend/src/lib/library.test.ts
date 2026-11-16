import { describe, expect, it } from "vitest";
import { canDownload, downloadBody, downloadPath, filesPath, searchPath, shortName, type LibraryFile } from "./library";

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
