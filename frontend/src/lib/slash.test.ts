import { describe, expect, it } from "vitest";
import { onOff, parse, suggest } from "./slash";

describe("the commands typed in the Chat", () => {
  it("are known by their name or an old French alias, with their argument", () => {
    expect(parse("/compact")).toEqual({ kind: "command", command: "compact", arg: "" });
    expect(parse("/web off")).toEqual({ kind: "command", command: "web", arg: "off" });
    expect(parse("  /MODELE   qwen3:8b ")).toEqual({ kind: "command", command: "model", arg: "qwen3:8b" });
    expect(parse("/nouveau")).toEqual({ kind: "command", command: "new", arg: "" });
  });

  it("leave an ordinary message alone, and « // » sends a slash on purpose", () => {
    expect(parse("bonjour")).toBeNull();
    expect(parse("//etc/hosts est-il lisible ?")).toBeNull();
    expect(parse("/")).toBeNull();
  });

  it("find the commands of a Claude project, and say when a command is unknown", () => {
    expect(parse("/review fichier.py", ["review", "git:commit"])).toEqual({ kind: "project", name: "review", arg: "fichier.py" });
    expect(parse("/git:commit", ["git:commit"])).toEqual({ kind: "project", name: "git:commit", arg: "" });
    expect(parse("/frobnicate")).toEqual({ kind: "unknown", name: "frobnicate" });
  });

  it("are suggested while the name is typed", () => {
    expect(suggest("/co").map((s) => s.name)).toEqual(["compact", "commands", "context"]);
    expect(suggest("/ret", ["review"]).map((s) => [s.name, s.project])).toEqual([["retry", false]]);
    expect(suggest("/ref", ["refactor"]).map((s) => [s.name, s.project])).toEqual([["think", false], ["refactor", true]]); // « reflexion » is an alias of think
    expect(suggest("/web off")).toEqual([]);
    expect(suggest("hello")).toEqual([]);
  });

  it("give way to a command of the Claude project with the same name when they are only a shortcut of the old page", () => {
    expect(parse("/test", ["test"])).toEqual({ kind: "project", name: "test", arg: "" });
    expect(parse("/test")).toEqual({ kind: "command", command: "test", arg: "" });
    expect(parse("/compact", ["compact"])).toEqual({ kind: "command", command: "compact", arg: "" }); // a command of Lutin itself still wins
    expect(parse("/rappeler budget 2027")).toEqual({ kind: "command", command: "recall", arg: "budget 2027" });
    expect(parse("/revue")).toEqual({ kind: "command", command: "changes", arg: "" });
  });

  it("read on/off in both languages", () => {
    expect([onOff("on"), onOff("NON"), onOff("maybe")]).toEqual([true, false, null]);
  });

  it("no longer offer to choose how a conversation keeps its thread: the progress sheet for every conversation (ADR 0019)", () => {
    expect(parse("/memoire fichier")).toEqual({ kind: "unknown", name: "memoire" });
  });
});
