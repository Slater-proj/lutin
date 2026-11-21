import { describe, expect, it } from "vitest";
import { formatBytes, percent } from "./format";

describe("sizes", () => {
  it("are shown in the unit and with the decimal mark of the language", () => {
    expect(formatBytes(4_700_000_000, "en")).toBe("4.7 GB");
    expect(formatBytes(4_700_000_000, "fr")).toBe("4,7 Go");
    expect(formatBytes(512, "fr")).toBe("512 o");
    expect(formatBytes(27_000_000, "en")).toBe("27.0 MB");
    expect(formatBytes(120_000_000_000, "fr")).toBe("120 Go");
  });

  it("are empty when the size is not known", () => {
    for (const unknown of [null, undefined, -1, Number.NaN, Number.POSITIVE_INFINITY]) expect(formatBytes(unknown, "en")).toBe("");
  });
});

describe("progress", () => {
  it("is a share between 0 and 100, and unknown while the total is", () => {
    expect(percent(50, 100)).toBe(50);
    expect(percent(150, 100)).toBe(100);
    expect(percent(-5, 100)).toBe(0);
    expect(percent(0, 0)).toBeNull();
    expect(percent(10, 0)).toBeNull();
  });
});
