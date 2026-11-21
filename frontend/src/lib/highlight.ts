// Colours for code in answers, without a dependency: a small scanner that cuts a piece of code into runs of text, each with a kind
// (comment, string, number, keyword, plain). It never produces HTML: components/Markdown.svelte draws each run as a <span class>.
// It is not a parser: it only needs to be right about quotes and comments, and to leave the rest alone. An unknown language is left plain.
// Called again at each piece of an answer that arrives, so an unfinished string or comment must simply run to the end.

export type Kind = "plain" | "comment" | "string" | "number" | "keyword" | "literal";
export type Run = { kind: Kind; text: string };

type Family = {
  line: string[]; // markers that start a comment up to the end of the line
  block?: [string, string]; // a comment between two markers
  quotes: string[];
  keywords: Set<string>;
  literals: Set<string>;
  nocase?: boolean;
};

const words = (list: string): Set<string> => new Set(list.split(/\s+/).filter(Boolean));

const C_LIKE = "break case catch class const continue default do else enum export extends finally for function if implements import in instanceof interface let new of private protected public return static super switch this throw try type typeof var void while with yield async await from as";
const FAMILIES: Record<string, Family> = {
  script: { line: ["//"], block: ["/*", "*/"], quotes: ['"', "'", "`"], keywords: words(C_LIKE + " declare namespace readonly abstract delete"), literals: words("true false null undefined NaN Infinity") },
  python: {
    line: ["#"],
    quotes: ['"""', "'''", '"', "'"],
    keywords: words("and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case"),
    literals: words("True False None self cls"),
  },
  json: { line: [], quotes: ['"'], keywords: words(""), literals: words("true false null") },
  shell: {
    line: ["#"],
    quotes: ['"', "'"],
    keywords: words("if then else elif fi for while until do done case esac in function select time return exit export local readonly set unset source alias cd echo"),
    literals: words("true false"),
  },
  yaml: { line: ["#"], quotes: ['"', "'"], keywords: words(""), literals: words("true false null yes no on off") },
  sql: {
    line: ["--"],
    block: ["/*", "*/"],
    quotes: ["'", '"'],
    keywords: words("select from where insert into values update set delete create table drop alter add index primary key foreign references join left right inner outer on group by order having limit offset union all distinct as and or not in is like between exists case when then else end"),
    literals: words("null true false"),
    nocase: true,
  },
  css: { line: [], block: ["/*", "*/"], quotes: ['"', "'"], keywords: words("important media import font-face keyframes supports"), literals: words("") },
  markup: { line: [], block: ["<!--", "-->"], quotes: ['"', "'"], keywords: words(""), literals: words("") },
  c: {
    line: ["//"],
    block: ["/*", "*/"],
    quotes: ['"', "'"],
    keywords: words("auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while class namespace template typename public private protected virtual new delete using this try catch throw bool final override fn let mut impl trait pub use mod match loop where move ref crate func go defer chan map package interface range select var string byte rune error"),
    literals: words("true false null nullptr NULL nil None"),
  },
};

const ALIASES: Record<string, string> = {
  js: "script", javascript: "script", jsx: "script", ts: "script", typescript: "script", tsx: "script", mjs: "script", svelte: "script", java: "c", kotlin: "c", swift: "c", scala: "c", dart: "script", php: "c",
  py: "python", python3: "python", json: "json", jsonc: "json", sh: "shell", bash: "shell", zsh: "shell", shell: "shell", console: "shell", powershell: "shell", ps1: "shell",
  yml: "yaml", yaml: "yaml", toml: "yaml", ini: "yaml", sql: "sql", css: "css", scss: "css", less: "css", html: "markup", xml: "markup", svg: "markup",
  c: "c", cpp: "c", "c++": "c", h: "c", cs: "c", csharp: "c", rust: "c", rs: "c", go: "c", golang: "c",
};

for (const name of Object.keys(FAMILIES)) ALIASES[name] = name;

export const MAX_LENGTH = 20000; // beyond that, plain: the scan is run again at every piece of an answer being written

export function supports(language: string): boolean {
  return (language.toLowerCase() in ALIASES);
}

const NUMBER = /^(?:0[xX][\da-fA-F_]+|0[bB][01_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)/;
const WORD = /^[A-Za-z_$][\w$-]*/;

function push(runs: Run[], kind: Kind, text: string): void {
  if (!text) return;
  const last = runs[runs.length - 1];
  if (last && last.kind === kind) last.text += text;
  else runs.push({ kind, text });
}

export function highlight(code: string, language: string): Run[] {
  const name = ALIASES[language.toLowerCase()];
  if (!name || code.length > MAX_LENGTH) return [{ kind: "plain", text: code }];
  const family = FAMILIES[name];
  const runs: Run[] = [];
  let i = 0;
  while (i < code.length) {
    const rest = code.slice(i);
    const block = family.block;
    if (block && rest.startsWith(block[0])) {
      const end = code.indexOf(block[1], i + block[0].length);
      const stop = end < 0 ? code.length : end + block[1].length;
      push(runs, "comment", code.slice(i, stop));
      i = stop;
      continue;
    }
    const marker = family.line.find((m) => rest.startsWith(m));
    if (marker && !(name === "shell" && code[i - 1] === "$")) {
      const end = code.indexOf("\n", i);
      const stop = end < 0 ? code.length : end;
      push(runs, "comment", code.slice(i, stop));
      i = stop;
      continue;
    }
    const quote = family.quotes.find((q) => rest.startsWith(q));
    if (quote) {
      let j = i + quote.length;
      const multiline = quote.length === 3 || quote === "`";
      while (j < code.length && !code.startsWith(quote, j)) {
        if (code[j] === "\\") j += 1;
        else if (code[j] === "\n" && !multiline) break; // an unclosed quote ends with its line
        j += 1;
      }
      const stop = code.startsWith(quote, j) ? j + quote.length : Math.min(j, code.length);
      push(runs, "string", code.slice(i, stop));
      i = stop;
      continue;
    }
    const previous = code[i - 1] ?? "";
    if (/\d/.test(rest[0]) && !/[\w$]/.test(previous)) {
      const number = NUMBER.exec(rest);
      if (number) {
        push(runs, "number", number[0]);
        i += number[0].length;
        continue;
      }
    }
    const word = WORD.exec(rest);
    if (word) {
      const text = word[0];
      const key = family.nocase ? text.toLowerCase() : text;
      const kind: Kind = family.literals.has(key) ? "literal" : family.keywords.has(key) ? "keyword" : "plain";
      push(runs, kind, text);
      i += text.length;
      continue;
    }
    push(runs, "plain", rest[0]);
    i += 1;
  }
  return runs;
}
