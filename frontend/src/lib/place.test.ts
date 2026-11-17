import { describe, expect, it } from "vitest";
import { approvalPath, attachmentUrl, byMachine, conversationPath, imageUrl, uploadPath } from "./place";

const ID = "a".repeat(32);

describe("where a conversation is held", () => {
  it("names the local routes for this machine", () => {
    expect(conversationPath("", "0123abcd")).toBe("/conversations/0123abcd");
    expect(approvalPath("", "x1")).toBe("/approvals/x1");
    expect(uploadPath("", "images")).toBe("/images");
    expect(imageUrl("", "i.png")).toBe("/api/v1/images/i.png");
    expect(attachmentUrl("", "d1", "notes du bureau.txt")).toBe("/api/v1/attachments/d1?name=notes%20du%20bureau.txt");
  });

  it("names the relayed routes for a paired machine", () => {
    expect(conversationPath(ID, "0123abcd")).toBe(`/machines/${ID}/conversations/0123abcd`);
    expect(approvalPath(ID, "x1")).toBe(`/machines/${ID}/approvals/x1`);
    expect(uploadPath(ID, "attachments")).toBe(`/machines/${ID}/attachments`);
    expect(imageUrl(ID, "i.png")).toBe(`/api/v1/machines/${ID}/images/i.png`);
    expect(attachmentUrl(ID, "d1", "a.txt")).toBe(`/api/v1/machines/${ID}/attachments/d1?name=a.txt`);
  });

  it("groups the conversations of the other machines under each one's name", () => {
    const entry = (machine: string, name: string, id: string) => ({ id, title: id, pinned: false, machine, machine_name: name });
    expect(byMachine([entry("m1", "Bureau", "c1"), entry("m2", "Salon", "c2"), entry("m1", "Bureau", "c3")]).map((group) => [group.name, group.conversations.map((c) => c.id)]))
      .toEqual([["Bureau", ["c1", "c3"]], ["Salon", ["c2"]]]);
  });
});
