import { describe, expect, it } from "vitest";
import { parseMath, type MathNode } from "./math";

/** A tree written short, to compare at a glance: tag[attributes](children) or tag:text. */
function show(nodes: MathNode[] | null): string {
  if (!nodes) return "null";
  return nodes
    .map((node) => {
      const attributes = node.attributes ? "[" + Object.entries(node.attributes).map(([name, value]) => `${name}=${value}`).join(",") + "]" : "";
      return node.tag + attributes + (node.children ? "(" + show(node.children) + ")" : node.text !== undefined ? ":" + node.text : "");
    })
    .join(" ");
}

const math = (source: string): string => show(parseMath(source));

describe("formulas", () => {
  it("reads letters, numbers and signs", () => {
    expect(math("x = 2a - 3.5")).toBe("mi:x mo:= mn:2 mi:a mo:− mn:3.5");
    expect(math("\\alpha \\le \\Omega \\times \\infty")).toBe("mi:α mo:≤ mi[mathvariant=normal]:Ω mo:× mi[mathvariant=normal]:∞");
    expect(math("f(x)")).toBe("mi:f mo[stretchy=false]:( mi:x mo[stretchy=false]:)");
    expect(math("50\\% \\neq \\$5")).toBe("mn:50 mi[mathvariant=normal]:% mo:≠ mi[mathvariant=normal]:$ mn:5");
  });

  it("writes what is above and below", () => {
    expect(math("x_i^2")).toBe("msubsup(mi:x mi:i mn:2)");
    expect(math("e^{i\\pi} + x^{}")).toBe("msup(mi:e mrow(mi:i mi:π)) mo:+ msup(mi:x mrow())");
    expect(math("f'(x) + g''")).toBe("msup(mi:f mo:′) mo[stretchy=false]:( mi:x mo[stretchy=false]:) mo:+ msup(mi:g mo:′′)");
    expect(math("x^2^3")).toBe("null");
    expect(math("{}^2 + \\displaystyle^3")).toBe("msup(mrow() mn:2) mo:+ msup(mrow() mn:3)");
    expect(math("^2")).toBe("null");
  });

  it("puts limits above and below sums and limits, beside integrals", () => {
    expect(math("\\sum_{i=1}^n i")).toBe("munderover(mo:∑ mrow(mi:i mo:= mn:1) mi:n) mi:i");
    expect(math("\\sum\\limits_{i} a")).toBe("munder(mo:∑ mi:i) mi:a");
    expect(math("\\int_0^\\infty f")).toBe("msubsup(mo:∫ mn:0 mi[mathvariant=normal]:∞) mi:f");
    expect(math("\\lim_{x \\to 0} f(x)")).toBe("munder(mo[movablelimits=true]:lim mrow(mi:x mo:→ mn:0)) mspace[width=0.167em] mi:f mo[stretchy=false]:( mi:x mo[stretchy=false]:)");
  });

  it("reads fractions, roots and binomials, with or without braces", () => {
    expect(math("\\frac{a+b}{2}")).toBe("mfrac(mrow(mi:a mo:+ mi:b) mn:2)");
    expect(math("\\frac12 + \\dfrac ab")).toBe("mfrac(mn:1 mn:2) mo:+ mfrac(mi:a mi:b)");
    expect(math("\\sqrt{x} + \\sqrt[3]{y}")).toBe("msqrt(mi:x) mo:+ mroot(mi:y mn:3)");
    expect(math("\\binom{n}{k}")).toBe("mrow(mo:( mfrac[linethickness=0](mi:n mi:k) mo:))");
  });

  it("spaces a function from what it applies to, but not from a bracket", () => {
    expect(math("\\sin x")).toBe("mi:sin mspace[width=0.167em] mi:x");
    expect(math("\\sin(x)")).toBe("mi:sin mo[stretchy=false]:( mi:x mo[stretchy=false]:)");
    expect(math("\\log_2 n")).toBe("msub(mi:log mn:2) mspace[width=0.167em] mi:n");
    expect(math("\\operatorname{softmax}(z)")).toBe("mi[mathvariant=normal]:softmax mo[stretchy=false]:( mi:z mo[stretchy=false]:)");
    expect(math("\\mathrm{d}x")).toBe("mi[mathvariant=normal]:d mi:x");
  });

  it("stretches the brackets of \\left and \\right, and those only", () => {
    expect(math("\\left( \\frac{a}{b} \\right]")).toBe("mrow(mo:( mfrac(mi:a mi:b) mo:])");
    expect(math("\\left. x \\right|_0")).toBe("msub(mrow(mi:x mo:|) mn:0)");
    expect(math("\\|v\\|_2 + \\big( a \\big)")).toBe("mo[stretchy=false]:‖ mi:v msub(mo[stretchy=false]:‖ mn:2) mo:+ mo[stretchy=false]:( mi:a mo[stretchy=false]:)");
    expect(math("\\left( x")).toBe("null");
  });

  it("writes styled letters with the mathematical letters of Unicode", () => {
    expect(math("\\mathbb{R}^n")).toBe("msup(mi:ℝ mi:n)");
    expect(math("\\mathbf{x} \\mathcal{L} \\mathfrak{g} \\mathbb{k1}")).toBe("mi:𝐱 mi:ℒ mi:𝔤 mrow(mi:𝕜 mn:𝟙)");
    expect(math("\\boldsymbol{\\beta}")).toBe("mi:𝜷");
    expect(math("\\mathbf{\\Gamma}")).toBe("mi[mathvariant=normal]:Γ");
  });

  it("reads text, accents and spaces", () => {
    expect(math("x \\text{ if } y > 0")).toBe("mi:x mtext: if  mi:y mo:> mn:0");
    expect(math("\\hat{y} \\vec v \\overline{AB}")).toBe("mover[accent=true](mi:y mo[stretchy=false]:^) mover[accent=true](mi:v mo[stretchy=false]:→) mover[accent=true](mrow(mi:A mi:B) mo:‾)");
    expect(math("a\\,b\\quad c\\!d")).toBe("mi:a mspace[width=0.167em] mi:b mspace[width=1em] mi:c mi:d");
    expect(math("\\underbrace{a+b}_{n}")).toBe("munder(munder[accentunder=true](mrow(mi:a mo:+ mi:b) mo:⏟) mi:n)");
    expect(math("a \\not\\in B \\not= c")).toBe("mi:a mo:∉ mi:B mo:≠ mi:c");
  });

  it("lays out matrices, cases and aligned lines", () => {
    expect(math("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}")).toBe("mrow(mo:( mtable(mtr(mtd(mi:a) mtd(mi:b)) mtr(mtd(mi:c) mtd(mi:d))) mo:))");
    expect(math("\\begin{cases} 1 & x > 0 \\\\ 0 & \\text{otherwise} \\end{cases}")).toBe(
      "mrow(mo:{ mtable[class=left](mtr(mtd[class=left,columnalign=left](mn:1) mtd[class=left,columnalign=left](mi:x mo:> mn:0)) mtr(mtd[class=left,columnalign=left](mn:0) mtd[class=left,columnalign=left](mtext:otherwise))))",
    );
    expect(math("\\begin{aligned} a &= b \\\\ &= c \\end{aligned}")).toBe(
      "mtable[class=pairs](mtr(mtd[class=right,columnalign=right](mi:a) mtd[class=left,columnalign=left](mo:= mi:b)) mtr(mtd[class=right,columnalign=right]() mtd[class=left,columnalign=left](mo:= mi:c)))",
    );
    expect(math("a \\\\ b")).toBe("mtable(mtr(mtd(mi:a)) mtr(mtd(mi:b)))");
    expect(math("a \\\\[2pt] [b] \\\\")).toBe("mtable(mtr(mtd(mi:a)) mtr(mtd(mo[stretchy=false]:[ mi:b mo[stretchy=false]:])))");
    expect(math("\\begin{pmatrix} a \\end{bmatrix}")).toBe("null");
  });

  it("never guesses what it does not know", () => {
    for (const unknown of ["\\unknowncommand{x}", "\\ce{H2O}", "x }", "{x", "\\frac{a}", "a & b }", "\\begin{tikzpicture} \\end{tikzpicture}", "\\right)", "", "   ", "x".repeat(4001), "{".repeat(100) + "}".repeat(100)]) {
      expect(math(unknown)).toBe("null");
    }
  });
});
