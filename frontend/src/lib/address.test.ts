import { describe, expect, it } from "vitest";
import { conversationOf, fromLegacy, pageOf } from "./address";

describe("the conversation named in the address", () => {
  it("reads an identifier of this machine, and nothing else", () => {
    expect(conversationOf("#/chat/0123abcd")).toBe("0123abcd");
    expect(conversationOf("#chat/0123abcd")).toBe("0123abcd");
    expect(conversationOf("#/chat")).toBeNull();
    expect(conversationOf("#/chat/0123ABCD")).toBeNull();
    expect(conversationOf("#/chat/0123abcd/x")).toBeNull();
    expect(conversationOf("#/chat/../settings")).toBeNull();
  });
});

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

describe("the direct links of the old page", () => {
  it("lead to the same place in the new interface", () => {
    expect(fromLegacy("#conv=0123abcd")).toBe("#/chat/0123abcd");
    expect(fromLegacy("#modeles")).toBe("#/models");
    expect(fromLegacy("#memoire")).toBe("#/settings/knowledge");
    expect(fromLegacy("#/settings/health")).toBeNull();
    expect(fromLegacy("")).toBeNull();
    expect(fromLegacy("#unknown")).toBeNull();
  });
});
