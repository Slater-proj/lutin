// What a conversation looks like on screen, built from two sources: the stored messages, and the events of the answer being written.
// Pure functions: no DOM, no network (tested in turn.test.ts).
import type { StoredMessage, Task, TurnEvent } from "./types";

export type Block =
  | { kind: "text"; text: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool"; name: string; arguments: unknown; result: string | null }
  | { kind: "notice"; text: string }
  | { kind: "dry_run"; title: string; detail: string; diff: string }
  | { kind: "error"; message: string };

export type Item = { role: "user"; text: string } | { role: "assistant"; blocks: Block[] };

export interface Approval {
  id: string;
  title: string;
  detail: string;
  diff: string;
  reason: string;
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

function withResult(blocks: Block[], name: string, text: string): Block[] {
  const index = blocks.findIndex((block) => block.kind === "tool" && block.name === name && block.result === null);
  if (index < 0) {
    return [...blocks, { kind: "tool", name, arguments: null, result: text }];
  }
  return blocks.map((block, i) => (i === index && block.kind === "tool" ? { ...block, result: text } : block));
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
      return { ...turn, status: "", blocks: [...turn.blocks, { kind: "tool", name: event.name, arguments: event.arguments, result: null }] };
    case "tool_result":
      return { ...turn, approval: null, blocks: withResult(turn.blocks, event.name, event.text) };
    case "approval_request":
      return { ...turn, approval: { id: event.id, title: event.title, detail: event.detail, diff: event.diff, reason: event.reason ?? "" } };
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
  for (const message of messages) {
    if (message.role === "user") {
      items.push({ role: "user", text: message.content ?? "" });
      answer = null;
    } else if (message.role === "assistant") {
      const blocks = blocksOfAnswer();
      if (message.thinking) blocks.push({ kind: "thinking", text: message.thinking });
      if (message.content) blocks.push({ kind: "text", text: message.content });
      for (const call of message.tool_calls ?? []) {
        blocks.push({ kind: "tool", name: call.function?.name ?? "", arguments: call.function?.arguments ?? null, result: null });
      }
    } else if (message.role === "tool") {
      const blocks = blocksOfAnswer();
      const name = message.tool_name ?? "";
      const waiting = blocks.find((block) => block.kind === "tool" && block.result === null && (block.name === name || name === ""));
      if (waiting && waiting.kind === "tool") {
        waiting.result = message.content ?? "";
      } else {
        blocks.push({ kind: "tool", name, arguments: null, result: message.content ?? "" });
      }
    }
  }
  return items;
}
