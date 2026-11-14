import { describe, expect, it } from "vitest";
import { lineParser } from "./stream";
import { catalogue, translate } from "./messages";
import { applyEvent, newTurn, storedToItems, type LiveTurn } from "./turn";
import type { TurnEvent } from "./types";

function play(events: TurnEvent[]): LiveTurn {
  return events.reduce(applyEvent, newTurn());
}

describe("the answer stream", () => {
  it("is read line by line whatever the cuts, ignoring the heartbeat and broken lines", () => {
    const seen: TurnEvent[] = [];
    const parser = lineParser((event) => seen.push(event));
    parser.push('{"type":"start","conversation_id":"0123abcd"}\n\n{"type":"te');
    parser.push('xt","text":"Good "}\n{"type":"text","text":"morning"}\nnot json\n[1]\n{"no":"type"}\n');
    parser.push('{"type":"end","conversation":{"id":"0123abcd","title":"T"}}');
    expect(seen.map((event) => event.type)).toEqual(["start", "text", "text"]);
    parser.end();
    expect(seen.map((event) => event.type)).toEqual(["start", "text", "text", "end"]);
  });
});

describe("the turn being written", () => {
  it("joins the pieces of text and keeps reasoning apart", () => {
    const turn = play([
      { type: "thinking", text: "let me " },
      { type: "thinking", text: "think" },
      { type: "text", text: "Good " },
      { type: "text", text: "morning" },
    ]);
    expect(turn.blocks).toEqual([
      { kind: "thinking", text: "let me think" },
      { kind: "text", text: "Good morning" },
    ]);
  });

  it("puts the result of a tool with its call, and asks for the approval in between", () => {
    const asked = play([
      { type: "tool_call", name: "modifier", arguments: { chemin: "a.py" } },
      { type: "approval_request", id: "x1", title: "Change a.py", detail: "", diff: "-1\n+2" },
    ]);
    expect(asked.approval).toEqual({ id: "x1", title: "Change a.py", detail: "", diff: "-1\n+2", reason: "" });
    const answered = applyEvent(asked, { type: "tool_result", name: "modifier", text: "refused" });
    expect(answered.approval).toBeNull();
    expect(answered.blocks).toEqual([{ kind: "tool", name: "modifier", arguments: { chemin: "a.py" }, result: "refused" }]);
  });

  it("never changes the turn it was given, and ignores an event it does not know", () => {
    const before = play([{ type: "text", text: "a" }]);
    const copy = JSON.stringify(before);
    const after = applyEvent(before, { type: "text", text: "b" });
    expect(JSON.stringify(before)).toBe(copy);
    expect(after.blocks).toEqual([{ kind: "text", text: "ab" }]);
    expect(applyEvent(before, { type: "something_new" } as unknown as TurnEvent)).toBe(before);
  });

  it("shows an error, the figures, the tasks, and ends", () => {
    const turn = play([
      { type: "status", text: "reading" },
      { type: "tasks", tasks: [{ text: "a", state: "done" }] },
      { type: "error", error: { code: "turn_failed", message: "boom" } },
      { type: "tokens", used: 1300, total: 24576, measured: true },
      { type: "speed", write_tokens_per_s: 33, read_tokens_per_s: null, load_s: 1.5, total_s: 4, tokens: 66 },
      { type: "memory_choice", conversation_id: "0123abcd" },
      { type: "end", conversation: { id: "0123abcd", title: "T" } },
    ]);
    expect(turn.blocks).toEqual([{ kind: "error", message: "boom" }]);
    expect([turn.tokens, turn.tokensPerSecond, turn.tasks.length, turn.title, turn.done, turn.memoryChoice, turn.status]).toEqual([{ used: 1300, total: 24576 }, 33, 1, "T", true, false, ""]);
  });
});

describe("the stored conversation", () => {
  it("becomes one item per message of the user and one per answer", () => {
    const items = storedToItems([
      { role: "system", content: "hidden" },
      { role: "user", content: "Change it" },
      { role: "assistant", content: "", thinking: "hm", tool_calls: [{ function: { name: "modifier", arguments: { chemin: "a.py" } } }] },
      { role: "tool", tool_name: "modifier", content: "done" },
      { role: "assistant", content: "Understood." },
      { role: "user", content: "Thanks" },
    ]);
    expect(items).toEqual([
      { role: "user", text: "Change it", index: 1 },
      {
        role: "assistant",
        blocks: [
          { kind: "thinking", text: "hm" },
          { kind: "tool", name: "modifier", arguments: { chemin: "a.py" }, result: "done" },
          { kind: "text", text: "Understood." },
        ],
      },
      { role: "user", text: "Thanks", index: 5 },
    ]);
  });
});

describe("the texts", () => {
  it("exist in French for every English key, with the same marks", () => {
    for (const [key, english] of Object.entries(catalogue.en)) {
      const french = (catalogue.fr as Record<string, string | undefined>)[key];
      expect(french, key).toBeTypeOf("string");
      expect((french ?? "").split("{}").length, key).toBe(english.split("{}").length);
    }
    expect(Object.keys(catalogue.fr).filter((key) => !(key in catalogue.en))).toEqual([]);
  });

  it("fill their marks in order", () => {
    expect(translate("en", "chat.tokens", 1300, 24576)).toBe("Context: 1300 of 24576 tokens");
    expect(translate("fr", "chat.tokens", 1300, 24576)).toBe("Contexte : 1300 jetons sur 24576");
  });
});
