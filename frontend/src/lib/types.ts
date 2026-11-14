// The shapes of /api/v1 (docs/modernization/API_V1.md). The server's contract tests fix them: tests/test_api_v1*.py.

export interface Status {
  version: string;
  language: string;
  access: { level: string; can_configure: boolean };
  offline: boolean;
  engine: { id: string; name: string; running: boolean };
  model: string;
  installed_models: string[];
  workspace: { path: string };
  active_turns: string[];
  pending_approvals: string[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
  pinned: boolean;
  origin_machine: string;
}

/** A stored message keeps the chat format of the engines. */
export interface StoredMessage {
  role: "system" | "user" | "assistant" | "tool";
  content?: string;
  thinking?: string;
  tool_name?: string;
  tool_calls?: { function?: { name?: string; arguments?: unknown } }[];
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  pinned: boolean;
  summary: string;
  messages: StoredMessage[];
}

export interface Download {
  name: string;
  state: "downloading" | "done" | "failed";
  done_bytes: number;
  total_bytes: number;
  text: string;
  restart_engine_advised: boolean;
}

export interface Models {
  engine: string;
  running: boolean;
  current: string;
  models: { name: string; size_bytes: number | null }[];
  downloads: Download[];
}

export interface Task {
  text: string;
  state: "todo" | "in_progress" | "done";
}

/** One line of the answer stream (rule 6 of API_V1.md). An event the interface does not know is ignored, never an error. */
export type TurnEvent =
  | { type: "start"; conversation_id: string }
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "status"; text: string }
  | { type: "notice"; text: string }
  | { type: "tool_call"; name: string; arguments: unknown }
  | { type: "tool_result"; name: string; text: string }
  | { type: "approval_request"; id: string; title: string; detail: string; diff: string; reason?: string; auto_approval_suspended?: boolean }
  | { type: "auto_approval_suspended"; reason: string }
  | { type: "auto_approval_restored" }
  | { type: "memory_choice"; conversation_id: string }
  | { type: "tasks"; tasks: Task[] }
  | { type: "dry_run"; title: string; detail: string; diff: string }
  | { type: "error"; error: { code: string; message: string } }
  | { type: "tokens"; used: number; total: number; measured: boolean }
  | { type: "speed"; write_tokens_per_s: number; read_tokens_per_s: number | null; load_s: number; total_s: number; tokens: number }
  | { type: "end"; conversation: { id: string; title: string } };
