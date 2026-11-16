// Formulas of an answer: the usual subset of LaTeX, turned into a tree of MathML elements that components/Formula.svelte draws with real elements.
// No dependency, no HTML, no inline style: the browser lays the formula out (MathML Core) and reads it aloud. What this subset does not know is
// never guessed: parseMath returns null and the formula is shown as it was written.
// Only what MathML Core has is produced: styled letters are the Unicode mathematical letters, not a `mathvariant` (Core keeps only « normal »).

export type MathTag =
  | "mrow" | "mi" | "mn" | "mo" | "mtext" | "mspace" | "mfrac" | "msqrt" | "mroot" | "msup" | "msub" | "msubsup"
  | "munder" | "mover" | "munderover" | "mtable" | "mtr" | "mtd";

export type MathNode = { tag: MathTag; text?: string; children?: MathNode[]; attributes?: Record<string, string> };

const MAX_LENGTH = 4000;
const MAX_DEPTH = 40;

class Unknown extends Error {}

function table(list: string): Map<string, string> {
  return new Map(list.trim().split(/\s+/).map((entry) => [entry.slice(0, entry.indexOf(":")), entry.slice(entry.indexOf(":") + 1)]));
}

// Letters: italic, as the browser draws a single letter.
const LETTERS = table(`alpha:α beta:β gamma:γ delta:δ epsilon:ϵ varepsilon:ε zeta:ζ eta:η theta:θ vartheta:ϑ iota:ι kappa:κ varkappa:ϰ lambda:λ mu:μ nu:ν xi:ξ
  pi:π varpi:ϖ rho:ρ varrho:ϱ sigma:σ varsigma:ς tau:τ upsilon:υ phi:ϕ varphi:φ chi:χ psi:ψ omega:ω imath:ı jmath:ȷ ell:ℓ`);
// Upright signs that stand for a value.
const SIGNS = table(`Gamma:Γ Delta:Δ Theta:Θ Lambda:Λ Xi:Ξ Pi:Π Sigma:Σ Upsilon:Υ Phi:Φ Psi:Ψ Omega:Ω infty:∞ partial:∂ nabla:∇ hbar:ℏ Re:ℜ Im:ℑ aleph:ℵ wp:℘
  emptyset:∅ varnothing:∅ angle:∠ triangle:△ square:□ Box:□ top:⊤ bot:⊥ forall:∀ exists:∃ nexists:∄ neg:¬ lnot:¬ prime:′ degree:° %:% $:$ #:# &:& _:_
  dots:… ldots:… cdots:⋯ vdots:⋮ ddots:⋱ dotsc:… dotsb:⋯ S:§ pounds:£ checkmark:✓`);
const OPERATORS = table(`times:× cdot:⋅ cdotp:⋅ div:÷ pm:± mp:∓ ast:∗ star:⋆ circ:∘ bullet:∙ oplus:⊕ ominus:⊖ otimes:⊗ odot:⊙ cup:∪ cap:∩ sqcup:⊔ sqcap:⊓ setminus:∖
  land:∧ wedge:∧ lor:∨ vee:∨ leq:≤ le:≤ geq:≥ ge:≥ leqslant:⩽ geqslant:⩾ neq:≠ ne:≠ approx:≈ equiv:≡ sim:∼ simeq:≃ cong:≅ propto:∝ ll:≪ gg:≫ doteq:≐ triangleq:≜
  lesssim:≲ gtrsim:≳ prec:≺ succ:≻ preceq:⪯ succeq:⪰ in:∈ notin:∉ ni:∋ subset:⊂ subseteq:⊆ subsetneq:⊊ supset:⊃ supseteq:⊇ supsetneq:⊋ nsubseteq:⊈
  to:→ rightarrow:→ leftarrow:← gets:← leftrightarrow:↔ Rightarrow:⇒ Leftarrow:⇐ Leftrightarrow:⇔ iff:⟺ implies:⟹ impliedby:⟸ mapsto:↦ longmapsto:⟼
  longrightarrow:⟶ longleftarrow:⟵ Longrightarrow:⟹ Longleftarrow:⟸ hookrightarrow:↪ rightleftharpoons:⇌ uparrow:↑ downarrow:↓ updownarrow:↕ nearrow:↗ searrow:↘
  perp:⊥ parallel:∥ mid:∣ nmid:∤ vdash:⊢ dashv:⊣ models:⊨ therefore:∴ because:∵ colon:: dagger:† ddagger:‡ amalg:⨿ wr:≀ bowtie:⋈ smile:⌣ frown:⌢ asymp:≍`);
// Signs that fence: with \left and \right they stretch; alone they keep their size, as in LaTeX.
const FENCES = table(`langle:⟨ rangle:⟩ lfloor:⌊ rfloor:⌋ lceil:⌈ rceil:⌉ vert:| lvert:| rvert:| Vert:‖ lVert:‖ rVert:‖ |:‖ lbrace:{ rbrace:} {:{ }:} lbrack:[ rbrack:]
  backslash:\\ lgroup:⟮ rgroup:⟯ ulcorner:⌜ urcorner:⌝ llcorner:⌞ lrcorner:⌟`);
const BIG = table("sum:∑ prod:∏ coprod:∐ bigcup:⋃ bigcap:⋂ bigoplus:⨁ bigotimes:⨂ bigodot:⨀ bigvee:⋁ bigwedge:⋀ bigsqcup:⨆ biguplus:⨄");
const INTEGRALS = table("int:∫ iint:∬ iiint:∭ oint:∮ oiint:∯");
const FUNCTIONS = new Set("sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh coth log ln lg exp dim ker deg hom arg".split(" "));
// Words that take what is written under them, as a limit does.
const LIMITS = new Map(Object.entries({ lim: "lim", limsup: "lim\u2009sup", liminf: "lim\u2009inf", max: "max", min: "min", sup: "sup", inf: "inf", argmax: "arg\u2009max", argmin: "arg\u2009min", det: "det", gcd: "gcd", Pr: "Pr" }));
const SPACES = table(",:0.167em >:0.222em ;:0.278em quad:1em qquad:2em enspace:0.5em enskip:0.5em thinspace:0.167em medspace:0.222em thickspace:0.278em");
SPACES.set(":", "0.222em").set(" ", "0.333em").set("\n", "0.333em");
const ACCENTS = table("hat:^ widehat:^ bar:‾ overline:‾ vec:→ overrightarrow:→ overleftarrow:← tilde:~ widetilde:~ dot:˙ ddot:¨ check:ˇ breve:˘ acute:´ grave:` overbrace:⏞ mathring:˚");
const UNDER = table("underline:_ underbrace:⏟ underrightarrow:→");
const STRETCHED = new Set(["widehat", "overline", "overrightarrow", "overleftarrow", "widetilde", "overbrace", "underline", "underbrace", "underrightarrow"]);
const NEGATED = table("=:≠ ∈:∉ ⊂:⊄ ⊆:⊈ ≡:≢ ∼:≁ <:≮ >:≯ ≤:≰ ≥:≱ ∣:∤ ∃:∄ ≈:≉ ≃:≄ ≅:≇ ∥:∦ →:↛ ⇒:⇏");
const IGNORED = new Set(("displaystyle textstyle scriptstyle scriptscriptstyle limits nolimits nonumber notag hline rm bf it big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr " +
  "bigm Bigm biggm Biggm ! negthinspace negmedspace negthickspace allowbreak nobreak centering").split(" "));
const IGNORED_WITH_ARGUMENT = new Set(["label", "tag", "tag*", "color", "vspace", "phantom", "hphantom", "vphantom", "rule"]);
const TRANSPARENT = new Set(["mathit", "mathnormal", "cancel", "bcancel", "xcancel", "mathstrut", "displaylines", "ensuremath", "smash", "mathopen", "mathclose", "mathrel", "mathbin", "mathord", "mathpunct", "mathinner"]);
const TEXTS = new Set(["text", "textrm", "textnormal", "textbf", "textit", "textsf", "texttt", "mbox", "hbox", "intertext"]);
// Environments: [opening sign, closing sign, how columns are aligned].
const ENVIRONMENTS: Record<string, [string, string, "center" | "left" | "pairs"]> = {
  matrix: ["", "", "center"], smallmatrix: ["", "", "center"], pmatrix: ["(", ")", "center"], bmatrix: ["[", "]", "center"], Bmatrix: ["{", "}", "center"], vmatrix: ["|", "|", "center"],
  Vmatrix: ["‖", "‖", "center"], array: ["", "", "center"], cases: ["{", "", "left"], dcases: ["{", "", "left"], rcases: ["", "}", "left"], aligned: ["", "", "pairs"], align: ["", "", "pairs"],
  alignat: ["", "", "pairs"], alignedat: ["", "", "pairs"], split: ["", "", "pairs"], eqnarray: ["", "", "pairs"], gathered: ["", "", "center"], gather: ["", "", "center"], equation: ["", "", "center"],
  multline: ["", "", "center"], subarray: ["", "", "center"],
};

function alphabet(upper: number, lower: number, digit: number, exceptions = ""): (character: string) => string {
  const other = table(exceptions || "-:-");
  return (character) => {
    const code = character.codePointAt(0) as number;
    if (other.has(character)) return other.get(character) as string;
    if (upper && code >= 65 && code <= 90) return String.fromCodePoint(upper + code - 65);
    if (lower && code >= 97 && code <= 122) return String.fromCodePoint(lower + code - 97);
    if (digit && code >= 48 && code <= 57) return String.fromCodePoint(digit + code - 48);
    if (upper === 0x1d468 && code >= 0x391 && code <= 0x3a9) return String.fromCodePoint(0x1d71c + code - 0x391); // bold Greek, for \boldsymbol
    if (upper === 0x1d468 && code >= 0x3b1 && code <= 0x3c9) return String.fromCodePoint(0x1d736 + code - 0x3b1);
    return character;
  };
}

const ALPHABETS: Record<string, (character: string) => string> = {
  mathbf: alphabet(0x1d400, 0x1d41a, 0x1d7ce),
  boldsymbol: alphabet(0x1d468, 0x1d482, 0x1d7ce),
  bm: alphabet(0x1d468, 0x1d482, 0x1d7ce),
  mathbb: alphabet(0x1d538, 0x1d552, 0x1d7d8, "C:ℂ H:ℍ N:ℕ P:ℙ Q:ℚ R:ℝ Z:ℤ"),
  mathcal: alphabet(0x1d49c, 0x1d4b6, 0, "B:ℬ E:ℰ F:ℱ H:ℋ I:ℐ L:ℒ M:ℳ R:ℛ e:ℯ g:ℊ o:ℴ"),
  mathscr: alphabet(0x1d49c, 0x1d4b6, 0, "B:ℬ E:ℰ F:ℱ H:ℋ I:ℐ L:ℒ M:ℳ R:ℛ e:ℯ g:ℊ o:ℴ"),
  mathfrak: alphabet(0x1d504, 0x1d51e, 0, "C:ℭ H:ℌ I:ℑ R:ℜ Z:ℨ"),
  mathsf: alphabet(0x1d5a0, 0x1d5ba, 0x1d7e2),
  mathtt: alphabet(0x1d670, 0x1d68a, 0x1d7f6),
};

const leaf = (tag: MathTag, text: string, attributes?: Record<string, string>): MathNode => (attributes ? { tag, text, attributes } : { tag, text });
const node = (tag: MathTag, children: MathNode[], attributes?: Record<string, string>): MathNode => (attributes ? { tag, children, attributes } : { tag, children });
const group = (children: MathNode[]): MathNode => (children.length === 1 ? children[0] : node("mrow", children));
const fence = (sign: string, stretchy: boolean): MathNode => (stretchy ? leaf("mo", sign) : leaf("mo", sign, { stretchy: "false" }));
const space = (width: string): MathNode => ({ tag: "mspace", attributes: { width } });

// What a node is besides its tag: a word after which a space is due (sin x), or an operator whose scripts go above and below.
const functions = new WeakSet<MathNode>();
const limits = new WeakSet<MathNode>();

class Reader {
  at = 0;
  depth = 0;

  constructor(readonly text: string) {}

  done(): boolean {
    return this.at >= this.text.length;
  }

  blank(): void {
    while (this.at < this.text.length && /\s/.test(this.text[this.at])) this.at += 1;
  }

  peek(piece: string): boolean {
    return this.text.startsWith(piece, this.at);
  }

  take(piece: string): boolean {
    if (!this.peek(piece)) return false;
    this.at += piece.length;
    return true;
  }

  /** The command that starts here, without its backslash (« frac », « , », « \ »), or "". */
  command(): string {
    const found = /^\\([A-Za-z]+\*?|[\s\S])/.exec(this.text.slice(this.at, this.at + 40));
    return found ? found[1] : "";
  }

  /** The text between the braces that open here, braces of its own included. */
  raw(): string {
    this.blank();
    if (!this.take("{")) throw new Unknown("argument");
    const start = this.at;
    for (let open = 1; this.at < this.text.length; this.at += 1) {
      const character = this.text[this.at];
      if (character === "\\") this.at += 1;
      else if (character === "{") open += 1;
      else if (character === "}" && --open === 0) return this.text.slice(start, this.at++);
    }
    throw new Unknown("brace");
  }
}

/** True where a row ends: a closing brace, a cell or line break, the end of an environment or of a \left. */
function ends(reader: Reader, bracket: boolean): boolean {
  if (reader.peek("}") || reader.peek("&") || (bracket && reader.peek("]"))) return true;
  const command = reader.command();
  return command === "\\" || command === "end" || command === "right";
}

function parseRow(reader: Reader, bracket = false): MathNode[] {
  const out: MathNode[] = [];
  for (;;) {
    reader.blank();
    if (reader.done() || ends(reader, bracket)) return out;
    const atom = parseScripted(reader);
    if (!atom) continue;
    out.push(atom);
    reader.blank();
    // « sin x » needs the thin space LaTeX puts there; « sin(x) » does not.
    if (functions.has(atom) && !reader.done() && !ends(reader, bracket) && !reader.peek("(") && !reader.peek("[") && reader.command() !== "left") out.push(space("0.167em"));
  }
}

/** One thing with what is written above and below it: x_i^2, \sum_{i=1}^n, f'. */
function parseScripted(reader: Reader): MathNode | null {
  let base = parseAtom(reader);
  let sub: MathNode | null = null;
  let sup: MathNode | null = null;
  let primes = "";
  for (;;) {
    reader.blank();
    const command = reader.command();
    if (command === "limits" || command === "nolimits") reader.at += command.length + 1;
    else if (reader.take("'")) primes += "′";
    else if (reader.peek("^") && !sup) {
      reader.at += 1;
      sup = group(argument(reader));
    } else if (reader.peek("_") && !sub) {
      reader.at += 1;
      sub = group(argument(reader));
    } else break;
  }
  if (primes) sup = sup ? node("mrow", [leaf("mo", primes), sup]) : leaf("mo", primes);
  if (!sub && !sup) return base;
  base ??= node("mrow", []);
  let scripted: MathNode;
  if (limits.has(base)) scripted = sub && sup ? node("munderover", [base, sub, sup]) : sub ? node("munder", [base, sub]) : node("mover", [base, sup as MathNode]);
  else scripted = sub && sup ? node("msubsup", [base, sub, sup]) : sub ? node("msub", [base, sub]) : node("msup", [base, sup as MathNode]);
  if (functions.has(base)) functions.add(scripted);
  return scripted;
}

/** What a command applies to: a group in braces, or the single thing that follows (\frac12 is one over two). */
function argument(reader: Reader): MathNode[] {
  reader.blank();
  if (reader.take("{")) {
    const inside = parseBody(reader);
    if (!reader.take("}")) throw new Unknown("brace");
    return inside;
  }
  if (reader.done() || ends(reader, false)) throw new Unknown("argument");
  if (/\d/.test(reader.text[reader.at])) return [leaf("mn", reader.text[reader.at++])];
  const atom = parseAtom(reader);
  return atom ? [atom] : [];
}

/** Rows and cells: lines separated by \\, cells by &. One line with one cell is a plain row. */
function parseLines(reader: Reader): MathNode[][][] {
  const rows: MathNode[][][] = [[]];
  for (;;) {
    rows[rows.length - 1].push(parseRow(reader));
    reader.blank();
    if (reader.take("&")) continue;
    if (reader.command() === "\\") {
      reader.at += 2;
      if (/^\s*\[\s*-?[\d.]+\s*(?:pt|em|ex|mm|cm|in|mu)\s*\]/.test(reader.text.slice(reader.at, reader.at + 30))) reader.at = reader.text.indexOf("]", reader.at) + 1; // \\[2pt]: a height, not drawn
      rows.push([]);
      continue;
    }
    break;
  }
  const last = rows[rows.length - 1];
  if (rows.length > 1 && last.every((cell) => cell.length === 0)) rows.pop(); // a line break at the very end
  return rows;
}

function grid(rows: MathNode[][][], wanted: "center" | "left" | "pairs"): MathNode {
  const align = wanted === "pairs" && rows.every((cells) => cells.length === 1) ? "center" : wanted; // lines without « & » are centred, as in gather
  return node("mtable", rows.map((cells) => node("mtr", cells.map((cell, column) => {
    const side = align === "left" ? "left" : align === "pairs" ? (column % 2 ? "left" : "right") : "";
    return node("mtd", cell, side ? { class: side, columnalign: side } : undefined);
  }))), align === "center" ? undefined : { class: align });
}

/** What stands between two braces, or the whole formula: a row, or lines when it holds \\ or &. */
function parseBody(reader: Reader): MathNode[] {
  if (++reader.depth > MAX_DEPTH) throw new Unknown("depth");
  const rows = parseLines(reader);
  reader.depth -= 1;
  return rows.length === 1 && rows[0].length === 1 ? rows[0][0] : [grid(rows, "pairs")];
}

function delimiter(reader: Reader, stretchy: boolean): MathNode | null {
  reader.blank();
  if (reader.take(".")) return null;
  const command = reader.command();
  if (command && FENCES.has(command)) {
    reader.at += command.length + 1;
    return fence(FENCES.get(command) as string, stretchy);
  }
  const arrow = command && /arrow$/.test(command) ? OPERATORS.get(command) : undefined;
  if (arrow) {
    reader.at += command.length + 1;
    return fence(arrow, stretchy);
  }
  const character = reader.text[reader.at] ?? "";
  if (!"()[]|/<>".includes(character) || !character) throw new Unknown("delimiter");
  reader.at += 1;
  return fence(character === "<" ? "⟨" : character === ">" ? "⟩" : character, stretchy);
}

function restyle(nodes: MathNode[], change: (character: string) => string): MathNode[] {
  return nodes.map((item) => {
    if (item.children) return { ...item, children: restyle(item.children, change) };
    if ((item.tag !== "mi" && item.tag !== "mn") || item.text === undefined) return item;
    const text = [...item.text].map(change).join("");
    return text === item.text ? item : { tag: item.tag, text };
  });
}

function upright(nodes: MathNode[]): MathNode[] {
  return nodes.map((item) => (item.children ? { ...item, children: upright(item.children) } : item.tag === "mi" ? { ...item, attributes: { mathvariant: "normal" } } : item));
}

function plainText(raw: string): string {
  // The spaces at both ends count (« x \text{ if } y »): MathML would drop plain ones.
  return raw.replace(/\\([%$&#_{} ])/g, "$1").replace(/~/g, "\u00a0").replace(/\\(?:quad|,|;)/g, " ").replace(/^ +| +$/g, (spaces) => "\u00a0".repeat(spaces.length));
}

function environment(reader: Reader, name: string): MathNode {
  const kind = ENVIRONMENTS[name.replace(/\*$/, "")];
  if (!kind) throw new Unknown(name);
  reader.blank();
  if (/^\[[tbc]\]/.test(reader.text.slice(reader.at, reader.at + 3))) reader.at += 3; // where the block sits on its line: not drawn
  reader.blank();
  if (/^(?:array|alignat|alignedat|subarray)/.test(name) && reader.peek("{")) reader.raw(); // the columns of an array: every column is centred here
  if (++reader.depth > MAX_DEPTH) throw new Unknown("depth");
  const rows = parseLines(reader);
  reader.depth -= 1;
  if (reader.command() !== "end") throw new Unknown("end");
  reader.at += 4;
  if (reader.raw() !== name) throw new Unknown("end");
  const body = grid(rows, kind[2]);
  if (!kind[0] && !kind[1]) return body;
  return node("mrow", [...(kind[0] ? [fence(kind[0], true)] : []), body, ...(kind[1] ? [fence(kind[1], true)] : [])]);
}

/** One thing, without what is written above or below it. Null for a command that draws nothing. */
function parseAtom(reader: Reader): MathNode | null {
  reader.blank();
  const character = reader.text[reader.at];
  if (character === undefined) throw new Unknown("end");
  if (character === "{") {
    reader.at += 1;
    const inside = parseBody(reader);
    if (!reader.take("}")) throw new Unknown("brace");
    return node("mrow", inside);
  }
  if (character !== "\\") {
    const number = /^\d+(?:\.\d+)?/.exec(reader.text.slice(reader.at, reader.at + 60));
    if (number) {
      reader.at += number[0].length;
      return leaf("mn", number[0]);
    }
    const sign = String.fromCodePoint(reader.text.codePointAt(reader.at) as number);
    reader.at += sign.length;
    if (/[\p{L}]/u.test(sign)) return leaf("mi", sign);
    if (sign === "~") return space("0.333em");
    if ("^_}&".includes(sign)) throw new Unknown(sign);
    if ("()[]|".includes(sign)) return fence(sign, false);
    return leaf("mo", sign === "-" ? "−" : sign);
  }
  const command = reader.command();
  if (!command) throw new Unknown("\\");
  reader.at += command.length + 1;
  const name = command.replace(/\*$/, "");
  if (LETTERS.has(command)) return leaf("mi", LETTERS.get(command) as string);
  if (SIGNS.has(command)) return leaf("mi", SIGNS.get(command) as string, { mathvariant: "normal" });
  if (OPERATORS.has(command)) return leaf("mo", OPERATORS.get(command) as string);
  if (FENCES.has(command)) return fence(FENCES.get(command) as string, false);
  if (INTEGRALS.has(command)) return leaf("mo", INTEGRALS.get(command) as string);
  if (SPACES.has(command)) return space(SPACES.get(command) as string);
  if (IGNORED.has(command)) return null;
  if (BIG.has(command) || LIMITS.has(command)) {
    const operator = BIG.has(command) ? leaf("mo", BIG.get(command) as string) : leaf("mo", LIMITS.get(command) as string, { movablelimits: "true" });
    limits.add(operator);
    if (LIMITS.has(command)) functions.add(operator);
    return operator;
  }
  if (FUNCTIONS.has(command)) {
    const word = leaf("mi", command);
    functions.add(word);
    return word;
  }
  if (IGNORED_WITH_ARGUMENT.has(command)) {
    reader.raw();
    return null;
  }
  if (TRANSPARENT.has(command)) return group(argument(reader));
  if (TEXTS.has(command)) return leaf("mtext", plainText(reader.raw()));
  if (ALPHABETS[command]) return group(restyle(argument(reader), ALPHABETS[command]));
  if (ACCENTS.has(command) || UNDER.has(command)) {
    const mark = leaf("mo", (ACCENTS.get(command) ?? UNDER.get(command)) as string, STRETCHED.has(command) ? undefined : { stretchy: "false" });
    const marked = node(ACCENTS.has(command) ? "mover" : "munder", [group(argument(reader)), mark], ACCENTS.has(command) ? { accent: "true" } : { accentunder: "true" });
    if (command === "overbrace" || command === "underbrace") limits.add(marked); // what follows ^ or _ is written above or below the brace
    return marked;
  }
  switch (name) {
    case "frac": case "dfrac": case "tfrac": case "cfrac":
      return node("mfrac", [group(argument(reader)), group(argument(reader))]);
    case "binom": case "dbinom": case "tbinom": case "choose":
      return node("mrow", [fence("(", true), node("mfrac", [group(argument(reader)), group(argument(reader))], { linethickness: "0" }), fence(")", true)]);
    case "sqrt": {
      reader.blank();
      if (!reader.take("[")) return node("msqrt", argument(reader));
      const index = parseRow(reader, true);
      if (!reader.take("]")) throw new Unknown("]");
      return node("mroot", [group(argument(reader)), group(index)]);
    }
    case "left": {
      const open = delimiter(reader, true);
      if (++reader.depth > MAX_DEPTH) throw new Unknown("depth");
      const inside = parseLines(reader);
      reader.depth -= 1;
      if (reader.command() !== "right") throw new Unknown("right");
      reader.at += 6;
      const close = delimiter(reader, true);
      const body = inside.length === 1 && inside[0].length === 1 ? inside[0][0] : [grid(inside, "pairs")];
      return node("mrow", [...(open ? [open] : []), ...body, ...(close ? [close] : [])]);
    }
    case "middle":
      return delimiter(reader, true);
    case "begin":
      return environment(reader, reader.raw());
    case "mathrm": case "operatorname": case "mathop": {
      reader.blank();
      const start = reader.at;
      const raw = reader.peek("{") ? reader.raw() : null;
      let word: MathNode;
      if (raw !== null && /^[A-Za-z0-9 .,-]*$/.test(raw)) word = raw.includes(" ") ? leaf("mtext", raw) : leaf("mi", raw, { mathvariant: "normal" });
      else {
        reader.at = start;
        word = group(upright(argument(reader)));
      }
      if (name !== "mathrm") functions.add(word);
      if (command === "operatorname*" || name === "mathop") limits.add(word);
      return word;
    }
    case "overset": case "stackrel": case "underset": {
      const mark = group(argument(reader));
      return node(name === "underset" ? "munder" : "mover", [group(argument(reader)), mark]);
    }
    case "xrightarrow": case "xleftarrow":
      return node("mover", [leaf("mo", name === "xrightarrow" ? "→" : "←"), group(argument(reader))]);
    case "substack":
      return group(argument(reader));
    case "not": {
      const next = parseAtom(reader);
      if (!next || next.text === undefined) throw new Unknown("not");
      return { ...next, text: NEGATED.get(next.text) ?? next.text + "̸" }; // a slash over it
    }
    case "textcolor": case "colorbox":
      reader.raw();
      return group(argument(reader));
    case "boxed": case "fbox":
      return node("mrow", argument(reader), { class: "boxed" });
    case "bmod": case "mod":
      return leaf("mo", "mod", { lspace: "0.278em", rspace: "0.278em" });
    case "pmod":
      return node("mrow", [space("1em"), fence("(", false), leaf("mo", "mod", { lspace: "0", rspace: "0.333em" }), ...argument(reader), fence(")", false)]);
    case "hspace": case "hskip": case "kern": case "mskip": case "mkern":
      if (reader.peek("{")) reader.raw();
      else reader.at += (/^\s*-?[\d.]+\s*[a-z]{2}/.exec(reader.text.slice(reader.at, reader.at + 20)) ?? [""])[0].length;
      return space("0.5em");
    default:
      throw new Unknown(command);
  }
}

/** The MathML tree of a formula written in LaTeX, or null when it uses something this subset does not know: it is then shown as written. */
export function parseMath(source: string): MathNode[] | null {
  if (source.length > MAX_LENGTH || !source.trim()) return null;
  const reader = new Reader(source);
  try {
    const nodes = parseBody(reader);
    reader.blank();
    return reader.done() ? nodes : null;
  } catch (error) {
    if (error instanceof Unknown || error instanceof RangeError) return null;
    throw error;
  }
}
