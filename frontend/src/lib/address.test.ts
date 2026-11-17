import { describe, expect, it } from "vitest";
import { pageOf } from "./address";

const TABS = ["tasks", "missions", "addons", "connectors"] as const;

describe("the page named in the address", () => {
  it("reads the segment after the area, and nothing else", () => {
    expect(pageOf("#/agents/missions", TABS)).toBe("missions");
    expect(pageOf("#agents/connectors", TABS)).toBe("connectors");
    expect(pageOf("#/agents", TABS)).toBeNull();
    expect(pageOf("#/agents/", TABS)).toBeNull();
    expect(pageOf("#/agents/elsewhere", TABS)).toBeNull();
    expect(pageOf("#/agents/toString", TABS)).toBeNull();
  });
});
