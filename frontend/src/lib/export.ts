// A conversation written out as Markdown, for « Export as Markdown » (docs/modernization/PARITY.md, item 12): the person's messages and the answers,
// the tool results folded in a short quote, nothing hidden (no reasoning, no internal markers). Pure functions, tested in export.test.ts.

export type ExportedMessage = { role: string; content?: string | null; tool_name?: string; tool_calls?: { function?: { name?: string } }[] };

const TOOL_MAX = 1200;

/** The file name of the export: `conversation-<title>-<date>.md`, the title reduced to letters, digits and dashes. */
export function exportName(title: string, date: Date): string {
  const clean = title.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).toLowerCase() || "conversation";
  const day = date.toISOString().slice(0, 10);
  return `conversation-${clean}-${day}.md`;
}

/** The Markdown text: a title, then each message under « You » or « Lutin »; a tool result as a quote cut at 1,200 characters. */
export function toMarkdown(title: string, messages: ExportedMessage[], labels: { you: string; lutin: string; tool: string }): string {
  const parts = [`# ${title}`];
  for (const message of messages) {
    const text = (message.content ?? "").trim();
    if (message.role === "user" && text) parts.push(`## ${labels.you}\n\n${text}`);
    else if (message.role === "assistant") {
      const called = (message.tool_calls ?? []).map((call) => call.function?.name ?? "?");
      if (text) parts.push(`## ${labels.lutin}\n\n${text}`);
      else if (called.length) parts.push(`*${labels.tool} ${called.join(", ")}*`);
    } else if (message.role === "tool" && text) {
      const cut = text.length > TOOL_MAX ? text.slice(0, TOOL_MAX) + " […]" : text;
      parts.push(`> **${labels.tool} ${message.tool_name ?? ""}**\n>\n` + cut.split("\n").map((line) => "> " + line).join("\n"));
    }
  }
  return parts.join("\n\n") + "\n";
}
