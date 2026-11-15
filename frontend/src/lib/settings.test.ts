import { describe, expect, it } from "vitest";
import { FIELDS, GROUPS, fieldsOf, parseTyped, shown } from "./settings";

const field = (name: string) => FIELDS.find((item) => item.name === name)!;

describe("settings", () => {
  it("puts every field in a known group, once", () => {
    expect(new Set(FIELDS.map((item) => item.name)).size).toBe(FIELDS.length);
    for (const item of FIELDS) expect(GROUPS).toContain(item.group);
    for (const group of GROUPS) expect(fieldsOf(group).length).toBeGreaterThan(0);
  });

  it("reads numbers with a comma, refuses words and values out of their range", () => {
    expect(parseTyped(field("temperature"), "0,7")).toEqual({ ok: true, value: 0.7 });
    expect(parseTyped(field("temperature"), "warm")).toEqual({ ok: false, error: "number" });
    expect(parseTyped(field("temperature"), "5")).toEqual({ ok: false, error: "range" });
    expect(parseTyped(field("max_steps"), "7.5")).toEqual({ ok: false, error: "number" });
    expect(parseTyped(field("max_steps"), "12")).toEqual({ ok: true, value: 12 });
  });

  it("takes an empty box as « chosen by Lutin » only where that is allowed", () => {
    expect(parseTyped(field("top_p"), "")).toEqual({ ok: true, value: null });
    expect(parseTyped(field("temperature"), " ")).toEqual({ ok: false, error: "number" });
  });

  it("turns lines into a list, without empty lines or spaces around", () => {
    expect(parseTyped(field("disabled_tools"), " shell \n\nweb_search\n")).toEqual({ ok: true, value: ["shell", "web_search"] });
    expect(shown(field("disabled_tools"), ["a", "b"])).toBe("a\nb");
    expect(shown(field("top_p"), null)).toBe("");
  });
});
