import { describe, expect, it } from "vitest";
import { qrPath } from "./qr";

describe("qrPath", () => {
  it("draws one square per dark cell, inside the quiet zone", () => {
    expect(qrPath(["10", "01"], 4)).toBe("M4 4h1v1h-1zM5 5h1v1h-1z");
    expect(qrPath(["00"], 4)).toBe("");
  });
});
