import { describe, expect, it } from "vitest";
import { highlight, supports } from "./highlight";

const kinds = (code: string, language: string) => highlight(code, language).filter((r) => r.kind !== "plain").map((r) => [r.kind, r.text]);

describe("highlight", () => {
  it("colours the keywords, strings, numbers and comments of Python", () => {
    expect(kinds('def f(x):  # note\n    return "a" + 42', "python")).toEqual([
      ["keyword", "def"], ["comment", "# note"], ["keyword", "return"], ["string", '"a"'], ["number", "42"],
    ]);
  });

  it("never loses a character: the runs put back give the code", () => {
    const code = "const a = `x\ny`; // end\nif (a) { return 1.5e3 }";
    expect(highlight(code, "ts").map((r) => r.text).join("")).toBe(code);
  });

  it("does not take a comment marker inside a string for a comment", () => {
    expect(kinds('const url = "http://x.org"', "js")).toEqual([["keyword", "const"], ["string", '"http://x.org"']]);
  });

  it("lets an unfinished string or comment run to the end", () => {
    expect(kinds('x = "abc', "python")).toEqual([["string", '"abc']]);
    expect(kinds("a /* open", "c")).toEqual([["comment", "/* open"]]);
  });

  it("leaves an unknown language and a very long code plain", () => {
    expect(highlight("def f(): pass", "brainfuck")).toEqual([{ kind: "plain", text: "def f(): pass" }]);
    expect(highlight("a".repeat(30000), "python")).toHaveLength(1);
    expect(supports("Python")).toBe(true);
    expect(supports("")).toBe(false);
  });

  it("does not cut a number out of a word", () => {
    expect(kinds("var x1 = 2", "js")).toEqual([["keyword", "var"], ["number", "2"]]);
  });
});
