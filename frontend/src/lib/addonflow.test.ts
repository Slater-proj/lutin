import { describe, expect, it } from "vitest";
import { canPropose, flowText, isChanged, parseFlow } from "./addonflow";

describe("parseFlow", () => {
  it("accepts a JSON object and nothing else", () => {
    expect(parseFlow('{"version": 1, "appels": {}}')).toEqual({ ok: true, flow: { version: 1, appels: {} } });
    for (const text of ["", "nonsense", "[1]", "3", "null", '{"a": ']) expect(parseFlow(text).ok).toBe(false);
  });
});

describe("isChanged", () => {
  const flow = { version: 1, appels: { a: { url: "x" } } };
  it("is false for the same flow however it is written", () => {
    expect(isChanged(flowText(flow), flow)).toBe(false);
    expect(isChanged(JSON.stringify(flow), flow)).toBe(false);
  });
  it("is true for another flow and for text that is not a flow", () => {
    expect(isChanged(JSON.stringify({ version: 2, appels: {} }), flow)).toBe(true);
    expect(isChanged("oops", flow)).toBe(true);
  });
});

describe("canPropose", () => {
  it("only after a failed check", () => {
    expect(canPropose(null)).toBe(false);
    expect(canPropose({ ok: true })).toBe(false);
    expect(canPropose({ ok: false })).toBe(true);
  });
});
