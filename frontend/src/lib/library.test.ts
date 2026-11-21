import { describe, expect, it } from "vitest";
import { canDownload, checkPath, downloadBody, downloadLabel, downloadPath, entryKey, installedPath, libraryQuery, recommendedPath, removePath, searchPath, shortName, sizesShown, variantsPath } from "./library";

describe("paths", () => {
  it("encode the engine, the words and the repository", () => {
    expect(searchPath("llamacpp", { words: " qwen 3 " })).toBe("/engines/llamacpp/models/search?q=qwen+3&page=1");
    expect(variantsPath("llamacpp", "author/Qwen3-GGUF")).toBe("/engines/llamacpp/models/variants?ref=author%2FQwen3-GGUF");
    expect(downloadPath("a b")).toBe("/engines/a%20b/models/downloads");
    expect(removePath("ollama", "qwen3:8b")).toBe("/engines/ollama/models/qwen3%3A8b");
    expect([installedPath("colibri"), recommendedPath("colibri"), checkPath("colibri")]).toEqual(["/engines/colibri/models", "/engines/colibri/models/recommended", "/engines/colibri/models/check"]);
  });

  it("send the order, the other authors and a capability only when they are asked", () => {
    expect(searchPath("lmstudio", { words: "", page: 2, order: "recent", community: false })).toBe("/engines/lmstudio/models/search?q=&page=2");
    expect(searchPath("lmstudio", { words: "gemma", order: "popular", community: true })).toBe("/engines/lmstudio/models/search?q=gemma&page=1&order=popular&community=1");
    expect(searchPath("ollama", { words: "", capability: "vision" })).toBe("/engines/ollama/models/search?q=&page=1&capability=vision");
  });
});

describe("canDownload", () => {
  it("refuses only what the server refuses, whatever the fit", () => {
    expect(canDownload({ download: { possible: false, reason: "Too big for this machine." } })).toBe(false);
    expect(canDownload({ download: { possible: true, reason: "" } })).toBe(true);
  });
});

describe("downloadBody", () => {
  it("carries the repository, the file and the confirmation", () => {
    expect(downloadBody("a/b", "m-q4.gguf", false)).toEqual({ ref: "a/b", revision: "m-q4.gguf", confirm: false });
    expect(downloadBody("a/b", "m-q4.gguf", true).confirm).toBe(true);
    expect(downloadBody("qwen3:8b", "", true)).toEqual({ ref: "qwen3:8b", confirm: true });
  });

  it("is said with its precision", () => {
    expect(downloadLabel("a/b", "Q4_K_M")).toBe("a/b @ Q4_K_M");
    expect(downloadLabel("qwen3:8b", "")).toBe("qwen3:8b");
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

describe("entryKey", () => {
  it("tells apart two files of one repository", () => {
    expect(entryKey({ id: "a/b", revision: "q2.gguf" })).not.toBe(entryKey({ id: "a/b", revision: "q8.gguf" }));
  });
});
