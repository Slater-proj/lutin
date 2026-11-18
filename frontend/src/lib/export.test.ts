import { describe, expect, it } from "vitest";
import { exportName, toMarkdown } from "./export";

const LABELS = { you: "You", lutin: "Lutin", tool: "Tool" };

describe("the Markdown export of a conversation", () => {
  it("names the file after the title and the day", () => {
    expect(exportName("Réécrire la facturation !", new Date("2026-11-18T10:00:00Z"))).toBe("conversation-reecrire-la-facturation-2026-11-18.md");
    expect(exportName("???", new Date("2026-11-18T10:00:00Z"))).toBe("conversation-conversation-2026-11-18.md");
  });

  it("writes the messages, says which tools were called and cuts their results", () => {
    const text = toMarkdown("Facturation", [
      { role: "user", content: "Lis a.py" },
      { role: "assistant", content: "", tool_calls: [{ function: { name: "lire" } }] },
      { role: "tool", tool_name: "lire", content: "x".repeat(1300) },
      { role: "assistant", content: "Voilà." },
      { role: "system", content: "never shown" },
    ], LABELS);
    expect(text.startsWith("# Facturation\n\n## You\n\nLis a.py")).toBe(true);
    expect(text).toContain("*Tool lire*");
    expect(text).toContain("> **Tool lire**");
    expect(text).toContain(" […]");
    expect(text).toContain("## Lutin\n\nVoilà.");
    expect(text).not.toContain("never shown");
  });
});
