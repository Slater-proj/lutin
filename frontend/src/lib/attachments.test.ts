import { describe, expect, it } from "vitest";
import { fromStored, kindOf, MAX_DOCUMENTS, MAX_IMAGES, refusal, turnFields, uploading, type Attachment } from "./attachments";

const item = (kind: "image" | "document", id: string, state: "uploading" | "ready" = "ready", name = id): Attachment => ({ key: id, kind, name, id, state });

describe("what is attached", () => {
  it("tells an image from a document by its type", () => {
    expect(kindOf({ type: "image/png" })).toBe("image");
    expect(kindOf({ type: "image/svg+xml" })).toBe("document"); // not an image the server accepts
    expect(kindOf({ type: "application/pdf" })).toBe("document");
    expect(kindOf({ type: "" })).toBe("document");
  });

  it("refuses an empty file, a file too big, and one more than the limit of its kind", () => {
    const images = Array.from({ length: MAX_IMAGES }, (_, index) => item("image", `i${index}`));
    const documents = Array.from({ length: MAX_DOCUMENTS }, (_, index) => item("document", `d${index}`));
    expect(refusal([], { type: "image/png", size: 0 })).toBe("empty");
    expect(refusal([], { type: "image/png", size: 8 * 1024 * 1024 + 1 })).toBe("too_big");
    expect(refusal([], { type: "application/pdf", size: 20 * 1024 * 1024 })).toBeNull();
    expect(refusal(images, { type: "image/jpeg", size: 10 })).toBe("too_many");
    expect(refusal(images, { type: "text/plain", size: 10 })).toBeNull(); // the limits are per kind
    expect(refusal(documents, { type: "text/plain", size: 10 })).toBe("too_many");
  });

  it("sends only what is ready, in the fields the server takes", () => {
    expect(turnFields([])).toEqual({});
    expect(turnFields([item("image", "a.png"), item("document", "b.txt", "ready", "note.txt"), item("image", "c.png", "uploading")])).toEqual({
      images: ["a.png"],
      attachments: [{ id: "b.txt", name: "note.txt" }],
    });
    expect(uploading([item("image", "c.png", "uploading")])).toBe(true);
    expect(uploading([item("image", "a.png")])).toBe(false);
  });

  it("gives back the attachments of a stored message, so that editing it keeps them", () => {
    expect(fromStored({})).toEqual([]);
    expect(fromStored({ images: ["a.png"], pieces: [{ id: "b.txt", nom: "note.txt" }] }).map(({ kind, id, name, state }) => ({ kind, id, name, state }))).toEqual([
      { kind: "image", id: "a.png", name: "a.png", state: "ready" },
      { kind: "document", id: "b.txt", name: "note.txt", state: "ready" },
    ]);
  });
});
