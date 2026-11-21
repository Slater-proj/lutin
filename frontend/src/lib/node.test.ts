import { describe, expect, it } from "vitest";
import { requestPath, waiting, type NodeView } from "./node";

function node(changes: Partial<NodeView> = {}): NodeView {
  return {
    lending: true, id: "a".repeat(32), shares: { skills: false, memory: false }, allow: { lead: false, update: false, shutdown: false },
    pending_shutdown: null, requests: [], authorized: [], startup: { installed: false, possible: true, limits: "" }, ...changes,
  };
}

describe("this machine as a node", () => {
  it("counts what waits for the owner: requests and a shutdown asked by another machine", () => {
    expect(waiting(null)).toBe(0);
    expect(waiting(node())).toBe(0);
    expect(waiting(node({ requests: [{ machine: "Bureau", right: "lead", date: "" }], pending_shutdown: { in_s: 20, by: "Bureau" } }))).toBe(2);
  });

  it("names the request in its path, spaces and accents included", () => {
    expect(requestPath({ machine: "Poste du salon é", right: "update" })).toBe("/node/requests/Poste%20du%20salon%20%C3%A9/update");
  });
});
