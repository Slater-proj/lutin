// Diagrams of an answer (ADR 0011). Mermaid needs inline styles, which the policy of this page forbids, and it reads text written by a model:
// it runs alone in a sandboxed frame served by Lutin (/app/diagram.html), without origin, cookie, token or network. This page sends it the text of a
// diagram and receives the text of a drawing, which it never reads as markup: the drawing is only ever shown as an image, where nothing can run.

export type Drawing = { url: string; width: number; height: number };

export type Reply = { type: "ready" } | { type: "drawn"; id: string; svg: string } | { type: "failed"; id: string; error: string };

export const MAX_SOURCE = 50_000; // the limit of Mermaid itself: beyond it there is nothing to draw
const MAX_DRAWING = 4_000_000;
const MAX_SIDE = 20_000;
const WAIT_MS = 20_000;
const KEPT = 40;

/** The languages of a code block that are a diagram. */
export function isDiagram(language: string): boolean {
  return language.toLowerCase() === "mermaid";
}

/** What the frame says, or null for anything else: a message is believed only in the shapes this page expects. */
export function readReply(data: unknown): Reply | null {
  if (typeof data !== "object" || data === null) return null;
  const message = data as Record<string, unknown>;
  if (message.type === "ready") return { type: "ready" };
  if (typeof message.id !== "string") return null;
  if (message.type === "drawn" && typeof message.svg === "string" && message.svg.length <= MAX_DRAWING) return { type: "drawn", id: message.id, svg: message.svg };
  if (message.type === "failed") return { type: "failed", id: message.id, error: typeof message.error === "string" ? message.error.slice(0, 300) : "" };
  return null;
}

const ROOT = /^\s*<svg\b((?:[^>"']|"[^"]*"|'[^']*')*)>/;

function attribute(tag: string, name: string): string {
  const found = new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`).exec(tag);
  return found ? (found[1] ?? found[2] ?? "") : "";
}

/** A drawing with its size written on it in pixels, taken from its viewBox: as an image it then has a size of its own. Null when it is not a drawing. */
export function sized(svg: string): { svg: string; width: number; height: number } | null {
  const root = ROOT.exec(svg);
  if (!root) return null;
  const box = attribute(root[1], "viewBox").trim().split(/[\s,]+/).map(Number);
  let [width, height] = box.length === 4 ? [box[2], box[3]] : [Number.NaN, Number.NaN];
  if (!(width > 0 && height > 0)) [width, height] = [Number(attribute(root[1], "width")), Number(attribute(root[1], "height"))]; // « 100% » is not a number
  if (!(width > 0 && height > 0) || width > MAX_SIDE || height > MAX_SIDE) return null;
  const kept = root[1].replace(/\s(?:width|height|style)\s*=\s*(?:"[^"]*"|'[^']*')/g, "");
  return { svg: `<svg${kept} width="${width}" height="${height}">` + svg.slice(root[0].length), width: Math.ceil(width), height: Math.ceil(height) };
}

/** Drawings by theme and text, the oldest forgotten first. `forget` is called with what leaves. */
export class Kept<Value> {
  private readonly entries = new Map<string, Value>();

  constructor(
    private readonly size: number,
    private readonly forget: (value: Value) => void,
  ) {}

  get(key: string): Value | undefined {
    const value = this.entries.get(key);
    if (value !== undefined) {
      this.entries.delete(key); // read again: it becomes the newest
      this.entries.set(key, value);
    }
    return value;
  }

  set(key: string, value: Value): void {
    this.entries.delete(key);
    this.entries.set(key, value);
    while (this.entries.size > this.size) {
      const oldest = this.entries.keys().next().value as string;
      this.forget(this.entries.get(oldest) as Value);
      this.entries.delete(oldest);
    }
  }

  delete(key: string): void {
    this.entries.delete(key);
  }
}

/** The frame failed, not the diagram: the same text is worth another try. */
export class FrameError extends Error {}

type Waiting = { resolve: (svg: string) => void; reject: (reason: Error) => void; timer: ReturnType<typeof setTimeout> };

let frame: HTMLIFrameElement | null = null;
let ready: Promise<void> | null = null;
let announce: (() => void) | null = null;
let listening = false;
let count = 0;
const waiting = new Map<string, Waiting>();
const drawings = new Kept<Promise<Drawing>>(KEPT, (drawing) => {
  drawing.then(
    (done) => URL.revokeObjectURL(done.url),
    () => undefined,
  );
});

function onMessage(event: MessageEvent): void {
  // Only the frame of this page, and only while it has no origin: a frame that had one would not be isolated.
  if (!frame || event.source !== frame.contentWindow || event.origin !== "null") return;
  const reply = readReply(event.data);
  if (!reply) return;
  if (reply.type === "ready") {
    announce?.();
    return;
  }
  const asked = waiting.get(reply.id);
  if (!asked) return;
  waiting.delete(reply.id);
  clearTimeout(asked.timer);
  if (reply.type === "drawn") asked.resolve(reply.svg);
  else asked.reject(new Error(reply.error || "not drawn"));
}

/** Removes the frame and answers « no » to everything it was asked: the next diagram starts a new one. */
function discard(reason: string): void {
  frame?.remove();
  frame = null;
  ready = null;
  announce = null;
  for (const asked of waiting.values()) {
    clearTimeout(asked.timer);
    asked.reject(new FrameError(reason));
  }
  waiting.clear();
}

function start(): Promise<void> {
  if (ready) return ready;
  if (!listening) {
    window.addEventListener("message", onMessage);
    listening = true;
  }
  ready = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      discard("the frame did not start");
      reject(new FrameError("the frame did not start"));
    }, WAIT_MS);
    announce = () => {
      clearTimeout(timer);
      resolve();
    };
    const created = document.createElement("iframe");
    created.setAttribute("sandbox", "allow-scripts"); // scripts, and nothing else: no origin, no form, no pop-up, no navigation of this page
    created.setAttribute("aria-hidden", "true");
    created.tabIndex = -1;
    created.title = "Lutin diagrams";
    created.className = "diagram-frame";
    created.src = import.meta.env.BASE_URL + "diagram.html";
    frame = created;
    document.body.appendChild(created);
  });
  return ready;
}

async function draw(source: string, dark: boolean): Promise<Drawing> {
  if (source.length > MAX_SOURCE) throw new Error("too long");
  await start();
  const target = frame?.contentWindow;
  if (!target) throw new FrameError("no frame");
  count += 1;
  const id = "d" + count;
  const svg = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => discard("the drawing took too long"), WAIT_MS); // a frame that no longer answers is replaced
    waiting.set(id, { resolve, reject, timer });
    target.postMessage({ type: "draw", id, source, dark }, "*"); // a frame without origin can only be addressed this way; what is sent is the text of the diagram
  });
  const drawing = sized(svg);
  if (!drawing) throw new Error("not a drawing");
  return { url: URL.createObjectURL(new Blob([drawing.svg], { type: "image/svg+xml" })), width: drawing.width, height: drawing.height };
}

/** The drawing of a diagram, as an image address and its size. Asked once per text and theme; rejected when the text is not a diagram Mermaid can draw. */
export function drawDiagram(source: string, dark: boolean): Promise<Drawing> {
  const key = (dark ? "dark\n" : "light\n") + source;
  let drawing = drawings.get(key);
  if (!drawing) {
    drawing = draw(source, dark);
    drawings.set(key, drawing);
    drawing.catch((error: unknown) => {
      if (error instanceof FrameError) drawings.delete(key);
    });
  }
  return drawing;
}

/** Forgets a drawing whose image did not load, so that it is asked again. */
export function forgetDiagram(source: string, dark: boolean): void {
  drawings.delete((dark ? "dark\n" : "light\n") + source);
}
