import { describe, expect, it } from "vitest";
import { runsHere, shown, strengths, type CatalogModel } from "./model_catalog";

function model(id: string, changes: Partial<CatalogModel> = {}): CatalogModel {
  return {
    id, name: id, summary: "", size_gb: 5, parameters_b: 8, active_parameters_b: 8, context_max: 32768, capabilities: [], licence: "MIT", roles: { general: 5 },
    advanced: false, warning: "", installed: false, fit: { level: "good", text: "" }, compatibility: { compatible: true, reasons: [], warnings: [], memory_gb: 6 }, ...changes,
  };
}

describe("the catalogue of models", () => {
  it("says what a model is good and weak at, best first", () => {
    expect(strengths({ general: 6, code: 9, creative: 2, fast: 7 })).toEqual({ strong: ["code", "fast"], weak: ["creative"] });
    expect(strengths({})).toEqual({ strong: [], weak: [] });
  });

  it("keeps what runs here, the most comfortable first, then the best rated", () => {
    const list = [
      model("tight", { fit: { level: "tight", text: "" } }),
      model("big", { fit: { level: "too_big", text: "" } }),
      model("other-engine", { compatibility: { compatible: false, reasons: ["x"], warnings: [], memory_gb: null } }),
      model("ok", { roles: { code: 9 } }),
      model("ok-low", { roles: { code: 4 } }),
      model("easy", { fit: { level: "comfortable", text: "" } }),
    ];
    expect(shown(list, "fits").map((item) => item.id)).toEqual(["easy", "ok", "ok-low", "tight"]);
    expect(shown(list, "all").map((item) => item.id)).toEqual(["easy", "ok", "other-engine", "ok-low", "tight", "big"]);
    expect(runsHere(model("unknown machine", { fit: null }))).toBe(true);
  });
});
