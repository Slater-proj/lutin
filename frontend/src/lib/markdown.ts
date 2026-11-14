// Markdown as the models write it, turned into a small tree that components/Markdown.svelte draws with real elements.
// No HTML is ever produced or interpreted here: a tag in an answer stays text. No dependency: the page works offline and under its strict policy.
// Covered: paragraphs, headings, fenced code, lists (nested), quotes, tables, rules; inline code, bold, italic, links (http, https, mailto only).
// An answer is parsed again at each piece that arrives, so an unfinished construct (an open code fence, a half-written table) must still give a tree.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "link"; href: string; children: Inline[] };

export type Block =
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "heading"; level: number; children: Inline[] }
  | { kind: "code"; language: string; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: Block[][] }
  | { kind: "quote"; children: Block[] }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][] }
  | { kind: "rule" };

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
const QUOTE = /^ {0,3}>\s?(.*)$/;
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;
const SAFE_LINK = /^(?:https?:\/\/|mailto:)/i;
const PUNCTUATION = /[!-/:-@[-`{-~]/;

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

function cells(line: string): string[] {
  const inner = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return inner.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function startsBlock(line: string): boolean {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || ITEM.test(line);
}

export function parseMarkdown(source: string): Block[] {
  return parseBlocks(source.replace(/\r\n?/g, "\n").split("\n"));
}

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i].trim().startsWith(fence[1][0].repeat(3)) && /^ {0,3}(`{3,}|~{3,})\s*$/.test(lines[i]))) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // the closing fence, or the end of an answer still being written
      blocks.push({ kind: "code", language: fence[2], text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: Math.min(heading[1].length, 4), children: parseInline(heading[2]) });
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" });
      i += 1;
      continue;
    }
    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        body.push((QUOTE.exec(lines[i]) as RegExpExecArray)[1]);
        i += 1;
      }
      blocks.push({ kind: "quote", children: parseBlocks(body) });
      continue;
    }
    const item = ITEM.exec(line);
    if (item) {
      const base = item[1].length;
      const ordered = /\d/.test(item[2]);
      const items: Block[][] = [];
      while (i < lines.length) {
        const next = ITEM.exec(lines[i]);
        if (!next || next[1].length !== base || /\d/.test(next[2]) !== ordered) break;
        const inside = base + next[2].length + 1; // what belongs to this item is indented at least to its text
        const body = [next[3]];
        i += 1;
        while (i < lines.length) {
          if (!lines[i].trim()) {
            const after = lines.slice(i + 1).find((candidate) => candidate.trim());
            if (after === undefined || indentOf(after) <= base) break;
            body.push("");
          } else if (indentOf(lines[i]) > base) {
            body.push(lines[i].slice(Math.min(indentOf(lines[i]), inside)));
          } else if (!startsBlock(lines[i]) && !TABLE_RULE.test(lines[i])) {
            body.push(lines[i].trim()); // a paragraph that goes on without indentation
          } else {
            break;
          }
          i += 1;
        }
        items.push(parseBlocks(body));
      }
      blocks.push({ kind: "list", ordered, start: ordered ? Number.parseInt(item[2], 10) : 1, items });
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && lines[i + 1].includes("-") && TABLE_RULE.test(lines[i + 1])) {
      const head = cells(line).map(parseInline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        const row = cells(lines[i]).map(parseInline);
        rows.push(head.map((_, column) => row[column] ?? []));
        i += 1;
      }
      blocks.push({ kind: "table", head, rows });
      continue;
    }
    const body = [line.trim()];
    i += 1;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) {
      body.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ kind: "paragraph", children: parseInline(body.join("\n")) });
  }
  return blocks;
}

function isWord(character: string | undefined): boolean {
  return character !== undefined && /[\p{L}\p{N}]/u.test(character);
}

/** The position of the closing delimiter that ends an emphasis opened at `from`, or -1. */
function closing(text: string, delimiter: string, from: number): number {
  let at = text.indexOf(delimiter, from);
  while (at >= 0) {
    const before = text[at - 1];
    const after = text[at + delimiter.length];
    const escaped = before === "\\";
    const tight = before !== undefined && !/\s/.test(before);
    const insideWord = delimiter.startsWith("_") && isWord(after);
    const longer = delimiter.length === 1 && (after === delimiter || before === delimiter);
    if (!escaped && tight && !insideWord && !longer && at > from) return at;
    at = text.indexOf(delimiter, at + 1);
  }
  return -1;
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let plain = "";
  const flush = (): void => {
    if (plain) out.push({ kind: "text", text: plain });
    plain = "";
  };
  let i = 0;
  while (i < text.length) {
    const character = text[i];
    const rest = text.slice(i);
    if (character === "\\" && i + 1 < text.length && PUNCTUATION.test(text[i + 1])) {
      plain += text[i + 1];
      i += 2;
      continue;
    }
    if (character === "`") {
      const ticks = (/^`+/.exec(rest) as RegExpExecArray)[0];
      const end = text.indexOf(ticks, i + ticks.length);
      if (end > 0) {
        flush();
        out.push({ kind: "code", text: text.slice(i + ticks.length, end).replace(/^ (.+) $/, "$1") });
        i = end + ticks.length;
        continue;
      }
    }
    if (character === "[") {
      const link = /^\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/.exec(rest);
      if (link && SAFE_LINK.test(link[2])) {
        flush();
        out.push({ kind: "link", href: link[2], children: parseInline(link[1]) });
        i += link[0].length;
        continue;
      }
    }
    if ((character === "h" || character === "H") && !isWord(text[i - 1])) {
      const address = /^https?:\/\/[^\s<>"'`]+/i.exec(rest);
      if (address) {
        const href = address[0].replace(/[.,;:!?)\]]+$/, "");
        flush();
        out.push({ kind: "link", href, children: [{ kind: "text", text: href }] });
        i += href.length;
        continue;
      }
    }
    if (character === "*" || character === "_") {
      const double = rest.startsWith(character + character);
      const delimiter = double ? character + character : character;
      const opens = text[i + delimiter.length] !== undefined && !/\s/.test(text[i + delimiter.length]) && !(character === "_" && isWord(text[i - 1]));
      const end = opens ? closing(text, delimiter, i + delimiter.length) : -1;
      if (end > 0) {
        flush();
        out.push({ kind: double ? "strong" : "em", children: parseInline(text.slice(i + delimiter.length, end)) });
        i = end + delimiter.length;
        continue;
      }
      plain += delimiter;
      i += delimiter.length;
      continue;
    }
    plain += character;
    i += 1;
  }
  flush();
  return out;
}
