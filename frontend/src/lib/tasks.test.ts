import { describe, expect, it } from "vitest";
import { chosenDays, dayList, dayName, isEveryDay, shownMoment } from "./tasks";

describe("tasks", () => {
  it("names the days from Monday, in the language asked", () => {
    expect(dayName(0, "en").toLowerCase()).toContain("mon");
    expect(dayName(6, "en").toLowerCase()).toContain("sun");
    expect(dayName(0, "fr").toLowerCase()).toContain("lun");
    expect(dayList([2, 0], "en").toLowerCase()).toMatch(/^mon.*wed/);
  });

  it("knows a task of every day and turns checkboxes into the days to send", () => {
    expect(isEveryDay([0, 1, 2, 3, 4, 5, 6])).toBe(true);
    expect(isEveryDay([0, 1, 2])).toBe(false);
    expect(chosenDays([true, false, true, false, false, false, true])).toEqual([0, 2, 6]);
    expect(chosenDays([false, false, false, false, false, false, false])).toEqual([]);
  });

  it("shows a moment without the T", () => {
    expect(shownMoment("2026-12-31T07:00")).toBe("2026-12-31 07:00");
    expect(shownMoment("")).toBe("");
  });
});
