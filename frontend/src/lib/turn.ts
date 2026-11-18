// What a conversation looks like on screen, built from two sources: the stored messages, and the events of the answer being written.
// Pure functions: no DOM, no network (tested in turn.test.ts).
import type { StoredMessage, StoredProduced, Task, TurnEvent, TurnState } from "./types";

/** What a tool produced: the images it generated (with where each is saved, when known) and the files it created. */
export interface Produced {
  media: { id: string; path: string }[];
  files: { id: string; name: string; size: number; path: string }[];
}

export type Block =
  | { kind: "text"; text: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool"; name: string; arguments: unknown; result: string | null; produced: Produced }
  | { kind: "notice"; text: string }
  | { kind: "dry_run"; title: string; detail: string; diff: string }
  | { kind: "error"; message: string };

/** `index` is the position of the message in the stored conversation: what `replace_from` takes to answer again from it. */
export interface Sent {
  images: string[]; // identifiers: shown through /api/v1/images/{id}
  files: { id: string; name: string }[]; // the documents: downloaded through /api/v1/attachments/{id}
}

export type Item = ({ role: "user"; text: string; index: number } & Sent) | { role: "assistant"; blocks: Block[] };

export interface Approval {
  id: string;
  title: string;
  detail: string;
  diff: string;
  reason: string;
  canRemember: boolean; // a command: the « yes » can be kept for this conversation, or always
}

/** The answer being written. */
export interface LiveTurn {
  blocks: Block[];
  status: string;
  approval: Approval | null;
  memoryChoice: boolean;
  autoApprovalSuspended: string;
  tasks: Task[];
  tokens: { used: number; total: number } | null;
  tokensPerSecond: number | null;
  title: string | null;
  done: boolean;
}

export function newTurn(): LiveTurn {
  return { blocks: [], status: "", approval: null, memoryChoice: false, autoApprovalSuspended: "", tasks: [], tokens: null, tokensPerSecond: null, title: null, done: false };
}

function appended(blocks: Block[], kind: "text" | "thinking", text: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === kind) {
    return [...blocks.slice(0, -1), { kind, text: last.text + text }];
  }
  return [...blocks, { kind, text }];
}

const nothing = (): Produced => ({ media: [], files: [] });

/** What a tool result carries, in the names of the stored messages (the stream gives the same values under English names). */
export function produced(media: string[] | undefined, mediaFiles: Record<string, string> | undefined, files: StoredProduced[] | undefined): Produced {
  return {
    media: (media ?? []).map((id) => ({ id, path: mediaFiles?.[id] ?? "" })),
    files: (files ?? []).map((file) => ({ id: file.id, name: file.nom, size: file.taille ?? 0, path: file.chemin ?? "" })),
  };
}

/** The same blocks without one produced image or file (after it was deleted): every block that shows it. */
export function withoutProduced(blocks: Block[], kind: "media" | "files", id: string): Block[] {
  return blocks.map((block) =>
    block.kind === "tool" ? { ...block, produced: { ...block.produced, [kind]: (block.produced[kind] as { id: string }[]).filter((entry) => entry.id !== id) } } : block,
  );
}

function withResult(blocks: Block[], name: string, text: string, made: Produced): Block[] {
  const index = blocks.findIndex((block) => block.kind === "tool" && block.name === name && block.result === null);
  if (index < 0) {
    return [...blocks, { kind: "tool", name, arguments: null, result: text, produced: made }];
  }
  return blocks.map((block, i) => (i === index && block.kind === "tool" ? { ...block, result: text, produced: made } : block));
}

/** The turn after one more event. Never changes its argument. An event this interface does not know leaves the turn as it is. */
export function applyEvent(turn: LiveTurn, event: TurnEvent): LiveTurn {
  switch (event.type) {
    case "text":
      return { ...turn, status: "", blocks: appended(turn.blocks, "text", event.text) };
    case "thinking":
      return { ...turn, blocks: appended(turn.blocks, "thinking", event.text) };
    case "status":
      return { ...turn, status: event.text };
    case "notice":
      return { ...turn, blocks: [...turn.blocks, { kind: "notice", text: event.text }] };
    case "tool_call":
      return { ...turn, status: "", blocks: [...turn.blocks, { kind: "tool", name: event.name, arguments: event.arguments, result: null, produced: nothing() }] };
    case "tool_result":
      return { ...turn, approval: null, blocks: withResult(turn.blocks, event.name, event.text, produced(event.media, event.media_files, event.attached_files)) };
    case "approval_request":
      return { ...turn, approval: { id: event.id, title: event.title, detail: event.detail, diff: event.diff, reason: event.reason ?? "", canRemember: event.can_remember === true } };
    case "auto_approval_suspended":
      return { ...turn, autoApprovalSuspended: event.reason };
    case "auto_approval_restored":
      return { ...turn, autoApprovalSuspended: "" };
    case "memory_choice":
      return { ...turn, memoryChoice: true };
    case "tasks":
      return { ...turn, tasks: event.tasks };
    case "dry_run":
      return { ...turn, blocks: [...turn.blocks, { kind: "dry_run", title: event.title, detail: event.detail, diff: event.diff }] };
    case "error":
      return { ...turn, status: "", blocks: [...turn.blocks, { kind: "error", message: event.error.message }] };
    case "tokens":
      return { ...turn, tokens: { used: event.used, total: event.total } };
    case "speed":
      return { ...turn, tokensPerSecond: event.write_tokens_per_s };
    case "end":
      return { ...turn, status: "", approval: null, memoryChoice: false, title: event.conversation.title, done: true };
    default:
      return turn;
  }
}

/**
 * What to say of an answer that this page did not start, from the state of its turn. A page that did not start a turn does not receive its approval cards:
 * a turn that waits for one would otherwise look like an answer that never comes. Without a state (the server only knows the turn as active), the plain notice.
 * The message never carries a count of seconds: it is read aloud each time it changes.
 */
export function elsewhereNotice(turn: Pick<TurnState, "state"> | undefined): "chat.elsewhere" | "chat.elsewhere.waiting" | "chat.elsewhere.stalled" | "chat.elsewhere.stopping" {
  if (turn?.state === "waiting_approval") return "chat.elsewhere.waiting";
  if (turn?.state === "stalled") return "chat.elsewhere.stalled";
  if (turn?.state === "cancelled") return "chat.elsewhere.stopping";
  return "chat.elsewhere";
}

/** The stored messages as items to show: one item per user message, and one per answer (its text, its reasoning, its tools and their results together). */
export function storedToItems(messages: StoredMessage[]): Item[] {
  const items: Item[] = [];
  let answer: Block[] | null = null;
  const blocksOfAnswer = (): Block[] => {
    if (answer === null) {
      answer = [];
      items.push({ role: "assistant", blocks: answer });
    }
    return answer;
  };
  for (const [index, message] of messages.entries()) {
    if (message.role === "user") {
      items.push({ role: "user", text: message.content ?? "", index, images: message.images ?? [], files: (message.pieces ?? []).map((piece) => ({ id: piece.id, name: piece.nom })) });
      answer = null;
    } else if (message.role === "assistant") {
      const blocks = blocksOfAnswer();
      if (message.thinking) blocks.push({ kind: "thinking", text: message.thinking });
      if (message.content) blocks.push({ kind: "text", text: message.content });
      for (const call of message.tool_calls ?? []) {
        blocks.push({ kind: "tool", name: call.function?.name ?? "", arguments: call.function?.arguments ?? null, result: null, produced: nothing() });
      }
    } else if (message.role === "tool") {
      const blocks = blocksOfAnswer();
      const name = message.tool_name ?? "";
      const made = produced(message.medias, message.medias_fichiers, message.fichiers_joints);
      const waiting = blocks.find((block) => block.kind === "tool" && block.result === null && (block.name === name || name === ""));
      if (waiting && waiting.kind === "tool") {
        waiting.result = message.content ?? "";
        waiting.produced = made;
      } else {
        blocks.push({ kind: "tool", name, arguments: null, result: message.content ?? "", produced: made });
      }
    }
  }
  return items;
}
