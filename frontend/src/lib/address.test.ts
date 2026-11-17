import { describe, expect, it } from "vitest";
import { conversationOf, pageOf } from "./address";

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
