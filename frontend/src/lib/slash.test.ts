import { describe, expect, it } from "vitest";
import { memoryMode, onOff, parse, suggest } from "./slash";

describe("the commands typed in the Chat", () => {
  it("are known by their name or an old French alias, with their argument", () => {
    expect(parse("/compact")).toEqual({ kind: "command", command: "compact", arg: "" });
    expect(parse("/web off")).toEqual({ kind: "command", command: "web", arg: "off" });
    expect(parse("  /MEMOIRE   fichier ")).toEqual({ kind: "command", command: "memory", arg: "fichier" });
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
    expect(suggest("/co").map((s) => s.name)).toEqual(["compact", "commands"]);
    expect(suggest("/re", ["review"]).map((s) => [s.name, s.project])).toEqual([["retry", false], ["think", false], ["review", true]]); // « reflexion » is an alias of think
    expect(suggest("/web off")).toEqual([]);
    expect(suggest("hello")).toEqual([]);
  });

  it("read on/off and the memory modes in both languages", () => {
    expect([onOff("on"), onOff("NON"), onOff("maybe")]).toEqual([true, false, null]);
    expect([memoryMode("fiche"), memoryMode("summary"), memoryMode("demander"), memoryMode("x")]).toEqual(["sheet", "summary", null, undefined]);
  });
});
