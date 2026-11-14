// What is attached to the next message. Pure functions: no DOM, no network (tested in attachments.test.ts).
// The limits are the server's (lutin.images and lutin.attachments); the server checks them again, these only avoid a useless upload.

export const MAX_IMAGES = 4;
export const MAX_DOCUMENTS = 5;
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

export type AttachmentKind = "image" | "document";

export interface Attachment {
  key: string; // unique on this page, whatever the server answers
  kind: AttachmentKind;
  name: string;
  id: string; // the identifier given by the server once uploaded
  state: "uploading" | "ready";
}

export function kindOf(file: { type: string }): AttachmentKind {
  return IMAGE_TYPES.includes(file.type) ? "image" : "document";
}

export function count(list: Attachment[], kind: AttachmentKind): number {
  return list.filter((item) => item.kind === kind).length;
}

export type Refusal = "too_many" | "too_big" | "empty" | null;

/** Whether this file may join the list: the number per kind and the size are the server's limits. */
export function refusal(list: Attachment[], file: { type: string; size: number }): Refusal {
  const kind = kindOf(file);
  if (file.size === 0) return "empty";
  if (file.size > (kind === "image" ? MAX_IMAGE_BYTES : MAX_DOCUMENT_BYTES)) return "too_big";
  if (count(list, kind) >= (kind === "image" ? MAX_IMAGES : MAX_DOCUMENTS)) return "too_many";
  return null;
}

/** The fields of a turn for what is ready; what is still uploading is not sent. */
export function turnFields(list: Attachment[]): { images?: string[]; attachments?: { id: string; name: string }[] } {
  const ready = list.filter((item) => item.state === "ready");
  const images = ready.filter((item) => item.kind === "image").map((item) => item.id);
  const documents = ready.filter((item) => item.kind === "document").map((item) => ({ id: item.id, name: item.name }));
  return { ...(images.length ? { images } : {}), ...(documents.length ? { attachments: documents } : {}) };
}

export function uploading(list: Attachment[]): boolean {
  return list.some((item) => item.state === "uploading");
}

/** The attachments of a message already stored, so that editing it keeps them (the server needs them again to answer from that message). */
export function fromStored(message: { images?: string[]; pieces?: { id: string; nom: string }[] }): Attachment[] {
  return [
    ...(message.images ?? []).map((id, index): Attachment => ({ key: `stored-image-${index}`, kind: "image", name: id, id, state: "ready" })),
    ...(message.pieces ?? []).map((piece, index): Attachment => ({ key: `stored-document-${index}`, kind: "document", name: piece.nom, id: piece.id, state: "ready" })),
  ];
}
