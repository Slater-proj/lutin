// The shapes of /api/v1 (docs/modernization/API_V1.md). The server's contract tests fix them: tests/test_api_v1*.py.
import type { NewVersion } from "./lutin";
import type { RemoteModels } from "./machines";

export interface Status {
  version: string;
  new_version: NewVersion | null; // a newer Lutin found by the check made at launch, not ignored: the banner
  restart: { needed: boolean; possible: boolean }; // a change waits for the next start; `possible`: something starts Lutin again
  language: string;
  access: { level: string; can_configure: boolean };
  offline: boolean;
  engine: { id: string; name: string; running: boolean };
  model: string;
  installed_models: string[];
  workspace: { path: string };
  can_open_files: boolean; // « Open » asks this machine's system to open a produced file: the browser of this machine only
  active_turns: string[];
  turns: TurnState[];
  pending_approvals: string[];
}

/** Where a running turn is (lutin/turn_state.py). A turn launched by something older than this record is in `active_turns` only. */
export interface TurnState {
  conversation: string;
  state: "running" | "waiting_approval" | "stalled" | "cancelled";
  phase: "context" | "model" | "tool";
  step: number;
  detail: string;
  elapsed_s: number;
  idle_s: number;
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
  images?: string[]; // identifiers of the images sent with this message
  pieces?: { id: string; nom: string }[]; // the documents sent with it
  medias?: string[]; // a tool result: the images it generated (read as the images sent)
  medias_fichiers?: Record<string, string>; // where each generated image is saved on the disk
  fichiers_joints?: StoredProduced[]; // a tool result: the files it created
  tool_calls?: { function?: { name?: string; arguments?: unknown } }[];
  epingle?: boolean; // pinned: kept in front of the model
  ts?: string; // when it was written (ISO, local time of the server)
}

/** A file a tool created, as stored in its result (French names inside the messages, as `pieces`). */
export interface StoredProduced {
  id: string;
  nom: string;
  taille?: number;
  chemin?: string;
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

export interface Settings {
  mode: "general" | "technical" | "scenario" | "research" | "chat";
  thinking: boolean;
  web: boolean;
  dry_run: boolean;
  num_predict: number;
}

export interface ConversationOptions {
  mode: "general" | "technical" | "scenario" | "research" | "chat" | "mission";
  thinking: boolean;
  web: boolean;
  dry_run: boolean;
  auto_approve_writes: boolean;
  auto_approve_commands: boolean;
  num_predict: number;
  mission_hours: number;
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
  /** The models of the paired machines that answer (lib/machines.ts); empty while the multi-machine mode is off. */
  remote: RemoteModels[];
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
  | { type: "tool_result"; name: string; text: string; media?: string[]; media_files?: Record<string, string>; attached_files?: StoredProduced[] }
  | { type: "approval_request"; id: string; title: string; detail: string; diff: string; reason?: string; auto_approval_suspended?: boolean; can_remember?: boolean }
  | { type: "auto_approval_suspended"; reason: string }
  | { type: "auto_approval_restored" }
  | { type: "memory_choice"; conversation_id: string }
  | { type: "tasks"; tasks: Task[] }
  | { type: "dry_run"; title: string; detail: string; diff: string }
  | { type: "error"; error: { code: string; message: string } }
  | { type: "tokens"; used: number; total: number; measured: boolean }
  | { type: "speed"; write_tokens_per_s: number; read_tokens_per_s: number | null; load_s: number; total_s: number; tokens: number }
  | { type: "end"; conversation: { id: string; title: string } };
