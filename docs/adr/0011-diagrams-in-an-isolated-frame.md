# ADR 0011 — Diagrams are drawn in an isolated frame; formulas by the browser

Status: accepted, implemented (plan step 4, last item of the Chat). Code: `src/lutin/web_app.py` (`diagram_page`, `DIAGRAM_CSP`),
`src/lutin/web/diagram_frame.js`, `frontend/src/lib/diagram.ts`, `frontend/src/components/Diagram.svelte`, `frontend/src/lib/math.ts`,
`frontend/src/components/Formula.svelte`; tests: `tests/test_web_app.py`, `tests/test_web_app_chat.py` (3i, 3j), `frontend/src/lib/*.test.ts`.

## Context

The present page draws the ` ```mermaid ` blocks of an answer with the Mermaid library shipped in `web/lib/mermaid.min.js` (3.5 MB). The new interface
(ADR 0002) is served with a strict content security policy: `script-src 'self'; style-src 'self'`, nothing inline. Mermaid runs no `eval`, but it writes
`style` attributes and `<style>` elements, which `style-src 'self'` blocks. Mermaid also reads text written by a model, which a web page read by the model
can influence, and it has had injection defects in the past.

Formulas were never drawn by the present page. Models write them in LaTeX between `$`, `$$`, `\( \)` and `\[ \]`.

## Options considered for diagrams

1. **Relax the policy** (`style-src 'unsafe-inline'`), Mermaid in the page. The cheapest. Rejected: Mermaid would run in the page that holds the token, the
   whole interface would lose the protection against injected styles, and a security test would have to be weakened.
2. **Own SVG renderer, no dependency.** Keeps the policy and runs no third-party code, in the spirit of the own Markdown reader. Rejected for 1.0: the Mermaid
   grammar is very large; a realistic subset (sequence, pie, simple flowcharts) would leave most diagrams as code, with a layout engine to maintain.
3. **Mermaid in an isolated frame** — chosen.

## Decision

**Diagrams.** Mermaid runs alone in a frame served by Lutin at `/app/diagram.html`:

- The frame is sandboxed (`sandbox allow-scripts`, in the policy of its page and on the element): it has **no origin**. It cannot read the interface, its
  token, its cookies or its storage, and a request it made would carry no session.
- Its policy is `default-src 'none'`: it can fetch and reach nothing. `style-src 'unsafe-inline'` is allowed **there only**. `script-src` names the hashes of
  the two scripts written into the page (Mermaid, then `diagram_frame.js`); nothing else runs, no inline handler either. The scripts are inline because a
  document without origin does not send the session cookie, and Lutin serves nothing without a session. The page is not made when a script would end its own
  `<script>` tag.
- The interface gains one directive, `frame-src 'self'`. It still has nothing inline; the test that forbids « unsafe » in its policy is unchanged.
- The interface sends the text of a diagram with `postMessage` and receives the text of a drawing (SVG). It believes a message only when it comes from its
  frame, with the origin `null`, in an expected shape. **It never reads the drawing as markup**: the drawing is shown as an image (`<img>` on a `blob:`
  address), where no script runs and nothing is fetched. A drawing that is not a well-formed image is not shown.
- Mermaid is set to `securityLevel: 'strict'` and draws labels as SVG text (`htmlLabels: false`), so that the drawing stays a well-formed image.
- One frame draws every diagram; it is created at the first diagram (3.5 MB are not loaded for answers without one), replaced when it stops answering.
- A diagram is drawn when its block is closed. While it is written, when it cannot be drawn, and on request (« Show the code »), it is its code.

**Formulas.** No library. `lib/math.ts` reads the usual subset of LaTeX (fractions, roots, indices, sums and integrals, Greek letters, signs, accents, text,
matrices, cases, aligned lines, `\left … \right`, styled alphabets) into a tree, drawn with real MathML elements that the browser lays out (MathML Core:
Chrome 109, Firefox, Safari). Nothing inline, nothing interpreted as HTML, read aloud by screen readers. What the reader does not know is **never guessed**:
the formula is shown as written. One dollar on each side is read with Pandoc's rule, because a dollar is also a price (`from $5 to $10` stays text).

## Consequences and limits

- Diagrams keep the full Mermaid grammar. The vendored file stays in the package (it already was) and is the only third-party code that reads model text;
  it is updated by replacing the file, and the hashes follow by themselves.
- A label written with Mermaid's HTML syntax is drawn as plain text.
- A diagram that makes Mermaid loop is abandoned after 20 s and its frame replaced. Where the browser does not give a sandboxed frame its own process, the page
  may be slow during that time.
- Verified in Chrome only (the test suite drives Chrome). Firefox and Safari follow the same standards but were not run.
- Formulas: the coverage is a subset; the layout is the browser's, less fine than KaTeX; before Chrome 109 a formula is a line of text.
- Svelte 5.57 creates an element given a plain-text MathML `xmlns` in the SVG namespace: `Formula.svelte` passes it as a value, and a browser test checks
  the namespace of every piece.

## Going back

Remove `frame-src 'self'` from `web_app.CSP` and the `diagram.html` route: diagrams are code blocks again, as before this record. Formulas: remove the
`math` cases of `lib/markdown.ts`; they are text again.
