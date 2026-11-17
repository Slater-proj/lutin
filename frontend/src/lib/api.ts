// The only door to the server: /api/v1, never the French routes (ADR 0002). An error always has a code for the program and a message for the person.
import { lineParser } from "./stream";
import type { TurnEvent } from "./types";

const PREFIX = "/api/v1";

function pageToken(): string {
  return document.querySelector<HTMLMetaElement>('meta[name="lutin-token"]')?.content ?? "";
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function send(method: string, path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  const headers: Record<string, string> = { "X-Token": pageToken() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(PREFIX + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin", signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "unreachable", "");
  }
  if (!response.ok) throw await failure(response);
  return response;
}

async function failure(response: Response): Promise<ApiError> {
  const answer: unknown = await response.json().catch(() => null);
  const error = (answer as { error?: { code?: unknown; message?: unknown } } | null)?.error;
  return new ApiError(response.status, typeof error?.code === "string" ? error.code : "unknown", typeof error?.message === "string" ? error.message : "");
}

/** Sends a file as the raw body of a POST (the bytes, not JSON). The name goes in `X-Name`, URL-encoded, for a document. */
export async function upload<T>(path: string, file: File, name?: string): Promise<T> {
  const headers: Record<string, string> = { "X-Token": pageToken(), "Content-Type": file.type || "application/octet-stream" };
  if (name !== undefined) headers["X-Name"] = encodeURIComponent(name);
  let response: Response;
  try {
    response = await fetch(PREFIX + path, { method: "POST", headers, body: file, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "unreachable", "");
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function api<T>(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  return (await (await send(method, path, body)).json()) as T;
}

/** Sends a message and calls `onEvent` for each event of the answer, until the stream ends. A refusal before the stream throws an ApiError.
 *  `conversation` is the path of the conversation (lib/place.ts): here, or on the paired machine that holds it. */
export async function streamTurn(conversation: string, body: { message: string; model?: string; replace_from?: number; images?: string[]; attachments?: { id: string; name: string }[] }, onEvent: (event: TurnEvent) => void, signal?: AbortSignal): Promise<void> {
  const response = await send("POST", `${conversation}/turns`, body, signal);
  const parser = lineParser(onEvent);
  if (!response.body) {
    parser.push(await response.text());
    parser.end();
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
  parser.push(decoder.decode());
  parser.end();
}
