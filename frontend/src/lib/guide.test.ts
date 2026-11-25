import { describe, expect, it } from "vitest";
import { blocker, choices, freeAfter, needsDownload, splitFit, type CatalogModel, type Choice, type Recommendation } from "./guide";

function model(id: string, extra: Partial<CatalogModel> = {}): CatalogModel {
  return {
    id,
    name: id,
    summary: "",
    size_gb: 5,
    capabilities: ["tools"],
    licence: "MIT",
    warning: "",
    installed: false,
    fit: { level: "good", text: "" },
    compatibility: { compatible: true, reasons: [], warnings: [], memory_gb: 6 },
    ...extra,
  };
}

function choice(id: string, extra: Partial<CatalogModel> = {}): Choice {
  return { role: "general", model: model(id, extra), context_tokens: 8192, memory_gb: 6, runs_on: "gpu" };
}

function recommendation(extra: Partial<Recommendation> = {}): Recommendation {
  return {
    detected: true,
    use: "chat",
    recommended: choice("a"),
    alternatives: [],
    download: { models: ["a"], size_gb: 5, free_gb: 100, fits_on_disk: true },
    engine: { id: "ollama", name: "Ollama", running: true },
    offline: false,
    ...extra,
  };
}

describe("what stops a download", () => {
  it("is nothing when the engine runs, the model is compatible and fits, and the disk has room", () => {
    const rec = recommendation();
    expect(blocker(rec.recommended as Choice, rec)).toBeNull();
  });

  it("names the first thing to fix, in the order a person would fix it", () => {
    const rec = recommendation({ offline: true, engine: { id: "ollama", name: "Ollama", running: false } });
    expect(blocker(rec.recommended as Choice, rec)).toBe("offline");
    expect(blocker(rec.recommended as Choice, { ...rec, offline: false })).toBe("engine_stopped");
    const incompatible = choice("b", { compatibility: { compatible: false, reasons: ["no"], warnings: [], memory_gb: null } });
    expect(blocker(incompatible, recommendation())).toBe("incompatible");
    expect(blocker(choice("c", { fit: { level: "too_big", text: "" } }), recommendation())).toBe("too_big");
  });

  it("refuses a model that would not fit on the disk, and says nothing when the disk could not be read", () => {
    const tight = recommendation({ download: { models: ["a"], size_gb: 5, free_gb: 4, fits_on_disk: false } });
    expect(freeAfter(tight.recommended as Choice, tight)).toBe(-1);
    expect(blocker(tight.recommended as Choice, tight)).toBe("no_space");
    const unknown = recommendation({ download: { models: ["a"], size_gb: 5, free_gb: null, fits_on_disk: null } });
    expect(freeAfter(unknown.recommended as Choice, unknown)).toBeNull();
    expect(blocker(unknown.recommended as Choice, unknown)).toBeNull();
  });

  it("does not take disk space for a model already installed", () => {
    const rec = recommendation({ recommended: choice("a", { installed: true }) });
    expect(needsDownload(rec.recommended as Choice)).toBe(false);
    expect(freeAfter(rec.recommended as Choice, rec)).toBe(100);
  });
});

describe("the verdict sentence", () => {
  it("does not say the label twice when the server's sentence starts with it", () => {
    expect(splitFit("Très à l'aise", "Très à l'aise sur ta machine : de la marge.")).toEqual({ head: "Très à l'aise", rest: " sur ta machine : de la marge." });
    expect(splitFit("Convient", "convient à ta machine (5 Go sur 10).")).toEqual({ head: "convient", rest: " à ta machine (5 Go sur 10)." });
  });

  it("puts the label first and the sentence after it otherwise", () => {
    expect(splitFit("Juste", "Tient à peine : la mémoire ne laisse que 4096 jetons.")).toEqual({ head: "Juste", rest: " — Tient à peine : la mémoire ne laisse que 4096 jetons." });
    expect(splitFit("Juste", "")).toEqual({ head: "Juste", rest: "" });
  });
});

describe("the choices shown", () => {
  it("put the recommendation first and show each model once", () => {
    const rec = recommendation({ alternatives: [choice("b"), choice("a"), choice("c")] });
    expect(choices(rec).map((item) => item.model.id)).toEqual(["a", "b", "c"]);
    expect(choices({ detected: true, use: "code", recommended: null })).toEqual([]);
  });
});
