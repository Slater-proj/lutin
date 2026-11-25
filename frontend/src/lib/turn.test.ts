import { describe, expect, it } from "vitest";
import { lineParser } from "./stream";
import { catalogue, translate } from "./messages";
import { applyEvent, approvalOf, elsewhereNotice, newTurn, storedToItems, withoutProduced, type LiveTurn } from "./turn";
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
    expect(asked.approval).toEqual({ id: "x1", title: "Change a.py", detail: "", diff: "-1\n+2", reason: "", canRemember: false, suspended: false });
    const answered = applyEvent(asked, { type: "tool_result", name: "modifier", text: "refused" });
    expect(answered.approval).toBeNull();
    expect(answered.blocks).toEqual([{ kind: "tool", name: "modifier", arguments: { chemin: "a.py" }, result: "refused", produced: { media: [], files: [] } }]);
  });

  it("keeps what a tool produced with its result: the generated images and the created files", () => {
    const turn = play([
      { type: "tool_call", name: "generer_image", arguments: {} },
      { type: "tool_result", name: "generer_image", text: "Done.", media: ["i1.png"], media_files: { "i1.png": "C:/out/i1.png" }, attached_files: [{ id: "f1", nom: "r.pdf", taille: 2048, chemin: "C:/w/r.pdf" }] },
    ]);
    expect(turn.blocks).toEqual([{ kind: "tool", name: "generer_image", arguments: {}, result: "Done.", produced: { media: [{ id: "i1.png", path: "C:/out/i1.png" }], files: [{ id: "f1", name: "r.pdf", size: 2048, path: "C:/w/r.pdf" }] } }]);
    const [image] = withoutProduced(turn.blocks, "media", "i1.png");
    expect(image.kind === "tool" && [image.produced.media.length, image.produced.files.length]).toEqual([0, 1]);
    const [file] = withoutProduced(turn.blocks, "files", "f1");
    expect(file.kind === "tool" && [file.produced.media.length, file.produced.files.length]).toEqual([1, 0]);
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
      { type: "end", conversation: { id: "0123abcd", title: "T" } },
    ]);
    expect(turn.blocks).toEqual([{ kind: "error", message: "boom" }]);
    expect([turn.tokens, turn.tokensPerSecond, turn.tasks.length, turn.title, turn.done, turn.status]).toEqual([{ used: 1300, total: 24576 }, 33, 1, "T", true, ""]);
  });
});

describe("the stored conversation", () => {
  it("becomes one item per message of the user and one per answer", () => {
    const items = storedToItems([
      { role: "system", content: "hidden" },
      { role: "user", content: "Change it" },
      { role: "assistant", content: "", thinking: "hm", tool_calls: [{ function: { name: "modifier", arguments: { chemin: "a.py" } } }] },
      { role: "tool", tool_name: "modifier", content: "done", medias: ["i1.png"], fichiers_joints: [{ id: "f1", nom: "r.pdf" }] },
      { role: "assistant", content: "Understood." },
      { role: "user", content: "Thanks", epingle: true, ts: "2026-11-18T10:00:00" },
    ]);
    expect(items).toEqual([
      { role: "user", text: "Change it", index: 1, pinned: false, images: [], files: [] },
      {
        role: "assistant",
        blocks: [
          { kind: "thinking", text: "hm" },
          { kind: "tool", name: "modifier", arguments: { chemin: "a.py" }, result: "done", produced: { media: [{ id: "i1.png", path: "" }], files: [{ id: "f1", name: "r.pdf", size: 0, path: "" }] } },
          { kind: "text", text: "Understood." },
        ],
      },
      { role: "user", text: "Thanks", index: 5, pinned: true, at: "2026-11-18T10:00:00", images: [], files: [] },
    ]);
  });
});

describe("an answer this page did not start", () => {
  it("is described by the state of its turn, and plainly when the server gives none", () => {
    expect(elsewhereNotice(undefined)).toBe("chat.elsewhere");
    expect(elsewhereNotice({ state: "running" })).toBe("chat.elsewhere");
    expect(elsewhereNotice({ state: "waiting_approval" })).toBe("chat.elsewhere.waiting");
    expect(elsewhereNotice({ state: "stalled" })).toBe("chat.elsewhere.stalled");
    expect(elsewhereNotice({ state: "cancelled" })).toBe("chat.elsewhere.stopping");
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

describe("a card read again", () => {
  it("is the card of the stream, with whether the automatic approval was suspended", () => {
    // a page opened again while a card waits reads it from GET /conversations/{id}/approvals (review of plan step 7)
    expect(approvalOf({ id: "a1", title: "Run npm test", detail: "", diff: "", reason: "Web content was read", can_remember: true, auto_approval_suspended: true }))
      .toEqual({ id: "a1", title: "Run npm test", detail: "", diff: "", reason: "Web content was read", canRemember: true, suspended: true });
  });
});
