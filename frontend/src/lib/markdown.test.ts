import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown, type Block, type Inline } from "./markdown";

const text = (value: string): Inline => ({ kind: "text", text: value });
const paragraph = (...children: Inline[]): Block => ({ kind: "paragraph", children });

describe("inline Markdown", () => {
  it("reads code, bold, italic and their nesting", () => {
    expect(parseInline("a `b*c*` **d *e* f** _g_")).toEqual([
      text("a "),
      { kind: "code", text: "b*c*" },
      text(" "),
      { kind: "strong", children: [text("d "), { kind: "em", children: [text("e")] }, text(" f")] },
      text(" "),
      { kind: "em", children: [text("g")] },
    ]);
  });

  it("leaves alone what is not emphasis", () => {
    expect(parseInline("2 * 3 * 4, snake_case_name, a ** b, *open")).toEqual([text("2 * 3 * 4, snake_case_name, a ** b, *open")]);
    expect(parseInline("\\*not italic\\* and `unclosed")).toEqual([text("*not italic* and `unclosed")]);
  });

  it("reads formulas between their marks, and leaves prices alone", () => {
    const formula = (value: string, display = false): Inline => ({ kind: "math", text: value, display });
    expect(parseInline("so $x_i^2$ and \\(a*b*c\\), then $$E = mc^2$$ or \\[ \\frac12 \\].")).toEqual([
      text("so "), formula("x_i^2"), text(" and "), formula("a*b*c"), text(", then "), formula("E = mc^2", true), text(" or "), formula("\\frac12", true), text("."),
    ]);
    expect(parseInline("($n+1$) costs \\$5: $a\\$b$")).toEqual([text("("), formula("n+1"), text(") costs $5: "), formula("a\\$b")]);
    for (const plain of ["from $5 to $10", "$5-$10 each", "US$50bn or A$70bn", "$HOME and $PATH", "pay 5$ now and 10$ later", "$ x $", "an open $x and \\(y", "$$", "$$ $$", "\\(\\)"]) {
      expect(parseInline(plain).every((piece) => piece.kind === "text")).toBe(true);
    }
    expect(parseInline("`$x$` stays code")).toEqual([{ kind: "code", text: "$x$" }, text(" stays code")]);
  });

  it("makes links of safe addresses only", () => {
    expect(parseInline("[Lutin](https://example.org/a_b) and https://example.org/x_y.")).toEqual([
      { kind: "link", href: "https://example.org/a_b", children: [text("Lutin")] },
      text(" and "),
      { kind: "link", href: "https://example.org/x_y", children: [text("https://example.org/x_y")] },
      text("."),
    ]);
    for (const unsafe of ["[x](javascript:alert(1))", "[x](data:text/html,hi)", "[x](/api/v1/status)", "[x](file:///etc/passwd)"]) {
      expect(parseInline(unsafe).some((node) => node.kind === "link"), unsafe).toBe(false);
    }
  });

  it("never turns HTML into anything but text", () => {
    expect(parseMarkdown('<img src=x onerror="alert(1)"> <b>bold</b>')).toEqual([paragraph(text('<img src=x onerror="alert(1)"> <b>bold</b>'))]);
  });
});

describe("blocks of Markdown", () => {
  it("reads headings, paragraphs with their line breaks, rules and quotes", () => {
    expect(parseMarkdown("# Title\n\nfirst line\nsecond line\n\n---\n> quoted\n> again\n\n###### deep")).toEqual([
      { kind: "heading", level: 1, children: [text("Title")] },
      paragraph(text("first line\nsecond line")),
      { kind: "rule" },
      { kind: "quote", children: [paragraph(text("quoted\nagain"))] },
      { kind: "heading", level: 4, children: [text("deep")] },
    ]);
  });

  it("keeps a code block exactly as written, with its language", () => {
    expect(parseMarkdown("before\n```python\ndef f():\n    return '**not bold**'\n\n```\nafter")).toEqual([
      paragraph(text("before")),
      { kind: "code", language: "python", text: "def f():\n    return '**not bold**'\n", closed: true },
      paragraph(text("after")),
    ]);
  });

  it("reads a formula on its own lines, and keeps one still being written as text", () => {
    expect(parseMarkdown("Then:\n$$\nx = \\frac{1}{2}\n$$\nand\n\\[ a \\\\ b \\]\n$$E = mc^2$$")).toEqual([
      paragraph(text("Then:")),
      { kind: "math", text: "x = \\frac{1}{2}" },
      paragraph(text("and")),
      { kind: "math", text: "a \\\\ b" },
      { kind: "math", text: "E = mc^2" },
    ]);
    expect(parseMarkdown("$$\nx = 1")).toEqual([paragraph(text("$$\nx = 1"))]);
    expect(parseMarkdown("$$a$$ where a is known")).toEqual([paragraph({ kind: "math", text: "a", display: true }, text(" where a is known"))]);
    expect(parseMarkdown("- item $x$\n  $$y$$")).toEqual([{ kind: "list", ordered: false, start: 1, items: [[paragraph(text("item "), { kind: "math", text: "x", display: false }), { kind: "math", text: "y" }]] }]);
  });

  it("shows an answer still being written: an open code block, a table without rows", () => {
    expect(parseMarkdown("```js\nconst a = 1;")).toEqual([{ kind: "code", language: "js", text: "const a = 1;", closed: false }]);
    expect(parseMarkdown("```mermaid\ngraph TD\n  A --> B\n```")).toEqual([{ kind: "code", language: "mermaid", text: "graph TD\n  A --> B", closed: true }]);
    expect(parseMarkdown("| a | b |\n|---|---|")).toEqual([{ kind: "table", head: [[text("a")], [text("b")]], rows: [] }]);
    expect(parseMarkdown("")).toEqual([]);
  });

  it("reads lists, ordered or not, and what is nested in an item", () => {
    expect(parseMarkdown("- one\n- two\n  - inner\n  - other\n- three\n\n3. third\n4. fourth\n   continued")).toEqual([
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [
          [paragraph(text("one"))],
          [paragraph(text("two")), { kind: "list", ordered: false, start: 1, items: [[paragraph(text("inner"))], [paragraph(text("other"))]] }],
          [paragraph(text("three"))],
        ],
      },
      { kind: "list", ordered: true, start: 3, items: [[paragraph(text("third"))], [paragraph(text("fourth\ncontinued"))]] },
    ]);
  });

  it("keeps a code block inside a list item", () => {
    const [list] = parseMarkdown("1. run:\n   ```\n   lutin start\n   ```\n2. open");
    expect(list).toEqual({
      kind: "list",
      ordered: true,
      start: 1,
      items: [[paragraph(text("run:")), { kind: "code", language: "", text: "lutin start", closed: true }], [paragraph(text("open"))]],
    });
  });

  it("reads a table, with missing cells and an escaped bar", () => {
    expect(parseMarkdown("| Name | Value |\n|:--|--:|\n| `a` | 1 |\n| b \\| c |\nafter")).toEqual([
      { kind: "table", head: [[text("Name")], [text("Value")]], rows: [[[{ kind: "code", text: "a" }], [text("1")]], [[text("b | c")], []]] },
      paragraph(text("after")),
    ]);
  });
});
