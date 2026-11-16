import { describe, expect, it } from "vitest";
import { isDiagram, Kept, readReply, sized } from "./diagram";

describe("diagrams", () => {
  it("knows which code blocks are diagrams", () => {
    expect([isDiagram("mermaid"), isDiagram("Mermaid"), isDiagram("python"), isDiagram("")]).toEqual([true, true, false, false]);
  });

  it("believes a message of the frame only in the expected shapes", () => {
    expect(readReply({ type: "ready", anything: 1 })).toEqual({ type: "ready" });
    expect(readReply({ type: "drawn", id: "d1", svg: "<svg></svg>", extra: "x" })).toEqual({ type: "drawn", id: "d1", svg: "<svg></svg>" });
    expect(readReply({ type: "failed", id: "d2", error: "e".repeat(500) })).toEqual({ type: "failed", id: "d2", error: "e".repeat(300) });
    expect(readReply({ type: "failed", id: "d2", error: { toString: () => "x" } })).toEqual({ type: "failed", id: "d2", error: "" });
    for (const wrong of [null, undefined, "drawn", 3, [], {}, { type: "drawn" }, { type: "drawn", id: 1, svg: "<svg/>" }, { type: "drawn", id: "d1", svg: 3 }, { type: "other", id: "d1" },
      { type: "drawn", id: "d1", svg: "x".repeat(4_000_001) }]) {
      expect(readReply(wrong)).toBeNull();
    }
  });

  it("writes on a drawing the size of its viewBox, whatever size it claimed", () => {
    expect(sized('<svg id="d1" width="100%" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 547.08 450" style="max-width: 547.08px;" role="img"><g/></svg>')).toEqual({
      svg: '<svg id="d1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 547.08 450" role="img" width="548" height="450"><g/></svg>',
      width: 548,
      height: 450,
    });
    // Whole pixels on the drawing itself, both ways: a browser rounds the size of an image to the nearest pixel, and the page would stretch it to its own rounding.
    expect(sized('<svg viewBox="0 0 300.6 120.2"><g/></svg>')).toEqual({ svg: '<svg viewBox="0 0 300.6 120.2" width="301" height="121"><g/></svg>', width: 301, height: 121 });
    expect(sized('<svg viewBox="-50,-10,550,308" height="1" width="1" aria-label="a > b"><g/></svg>')).toEqual({
      svg: '<svg viewBox="-50,-10,550,308" aria-label="a > b" width="550" height="308"><g/></svg>',
      width: 550,
      height: 308,
    });
    expect(sized("<svg width='120' height='40'></svg>")).toEqual({ svg: '<svg width="120" height="40"></svg>', width: 120, height: 40 });
  });

  it("refuses what is not a drawing with a size", () => {
    for (const wrong of ["", "<p>text</p>", "text <svg viewBox='0 0 1 1'></svg>", "<svg></svg>", '<svg width="100%" height="100%"></svg>', '<svg viewBox="0 0 0 10"></svg>',
      '<svg viewBox="0 0 a b"></svg>', '<svg viewBox="0 0 30000 10"></svg>', "<svg viewBox='0 0 10 10'"]) {
      expect(sized(wrong)).toBeNull();
    }
  });

  it("keeps the newest drawings and says which ones leave", () => {
    const gone: string[] = [];
    const kept = new Kept<string>(2, (value) => gone.push(value));
    kept.set("a", "A");
    kept.set("b", "B");
    expect(kept.get("a")).toBe("A"); // read again: « b » is now the oldest
    kept.set("c", "C");
    expect([kept.get("a"), kept.get("b"), kept.get("c"), gone]).toEqual(["A", undefined, "C", ["B"]]);
    kept.delete("a");
    expect([kept.get("a"), gone]).toEqual([undefined, ["B"]]);
  });
});
