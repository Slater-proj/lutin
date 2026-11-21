import { describe, expect, it } from "vitest";
import { canAskDownload, downloadBody, downloadShare, kindCounts, type ComfyPanel } from "./comfy";

const panel = (more: Partial<ComfyPanel> = {}): ComfyPanel => ({
  running: true, error: "", version: "1", gpu: "", folder: "C:/Comfy", folder_set: true, folder_valid: true, folder_problem: "", can_launch: true,
  models: { source: "api", by_kind: {} }, families: {}, family_labels: {}, workflows: [], engines: { image: [], video: [], sound: [] }, unusable_models: [],
  download: { state: "idle", name: "", done_bytes: 0, total_bytes: 0, error: "" }, download_kinds: ["checkpoints", "loras"], ...more,
});

describe("kindCounts", () => {
  it("counts, drops the empty kinds and puts the biggest first", () => {
    expect(kindCounts({ loras: ["a"], checkpoints: ["a", "b"], vae: [], upscale: ["z"] })).toEqual([
      { kind: "checkpoints", count: 2 },
      { kind: "loras", count: 1 },
      { kind: "upscale", count: 1 },
    ]);
    expect(kindCounts({})).toEqual([]);
  });
});

describe("downloadShare", () => {
  it("is null while the size is unknown and capped at 100", () => {
    const base = panel().download;
    expect(downloadShare(base)).toBeNull();
    expect(downloadShare({ ...base, done_bytes: 5, total_bytes: 10 })).toBe(50);
    expect(downloadShare({ ...base, done_bytes: 11, total_bytes: 10 })).toBe(100);
  });
});

describe("canAskDownload", () => {
  const url = "https://huggingface.co/a/b/resolve/main/m.safetensors";
  it("needs a good folder, an https address, a known kind and nothing already downloading", () => {
    expect(canAskDownload(panel(), url, "loras")).toBe(true);
    expect(canAskDownload(panel({ folder_valid: false }), url, "loras")).toBe(false);
    expect(canAskDownload(panel(), "http://x/y", "loras")).toBe(false);
    expect(canAskDownload(panel(), "  ", "loras")).toBe(false);
    expect(canAskDownload(panel(), url, "unknown")).toBe(false);
    expect(canAskDownload(panel({ download: { state: "running", name: "", done_bytes: 0, total_bytes: 0, error: "" } }), url, "loras")).toBe(false);
  });
});

describe("downloadBody", () => {
  it("trims the address and carries the confirmation", () => {
    expect(downloadBody(" https://x/y ", "vae", true)).toEqual({ url: "https://x/y", kind: "vae", confirm: true });
  });
});
