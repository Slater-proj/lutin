import { describe, expect, it } from "vitest";
import { markOf, markSeen, readSeen } from "./marks";

function memory(): Pick<Storage, "getItem" | "setItem"> {
  const kept = new Map<string, string>();
  return { getItem: (key) => kept.get(key) ?? null, setItem: (key, value) => void kept.set(key, value) };
}

describe("the marks of the list of conversations", () => {
  it("says waiting, then working, then unread", () => {
    const seen = { a: "2026-01-01T10:00", b: "2026-01-01T10:00" };
    expect(markOf("a", "2026-01-01T11:00", ["a"], ["a"], seen, null)).toBe("waiting");
    expect(markOf("a", "2026-01-01T11:00", ["a"], [], seen, null)).toBe("working");
    expect(markOf("a", "2026-01-01T11:00", [], [], seen, null)).toBe("unread");
    expect(markOf("a", "2026-01-01T11:00", [], [], seen, "a")).toBeNull();
    expect(markOf("b", "2026-01-01T10:00", [], [], seen, null)).toBeNull();
    expect(markOf("never-seen", "2026-01-01T11:00", [], [], seen, null)).toBeNull();
  });

  it("remembers what was seen, in this browser only", () => {
    const storage = memory();
    markSeen("a", "2026-01-01T10:00", storage);
    expect(readSeen(storage)).toEqual({ a: "2026-01-01T10:00" });
    expect(readSeen({ getItem: () => "not json" })).toEqual({});
    expect(markSeen("b", "x", null)).toEqual({ b: "x" });
  });
});
