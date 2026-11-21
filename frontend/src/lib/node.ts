// This machine as a node (ADR 0016, stage 5): what it lends to the machines paired with it. The shape of GET /api/v1/node and what the
// « Lend this machine » group of Settings draws from it. Pure functions, tested in node.test.ts; the texts are in messages.ts under `lend.*`.
import type { Right } from "./machines";

export interface NodeView {
  lending: boolean;
  id: string;
  shares: { skills: boolean; memory: boolean };
  allow: Record<Right, boolean>;
  pending_shutdown: { in_s: number; by: string } | null;
  requests: { machine: string; right: Right; date: string }[];
  authorized: { name: string; date: string }[];
  startup: { installed: boolean; possible: boolean; limits: string };
}

export type Share = keyof NodeView["shares"];
export const SHARES: readonly Share[] = ["skills", "memory"];

/** What waits for the owner of this machine: the rights requests and a shutdown asked by another machine. Shown as a badge on Settings. */
export function waiting(node: NodeView | null): number {
  if (!node) return 0;
  return node.requests.length + (node.pending_shutdown ? 1 : 0);
}

/** The path of the answer to one request: the machine name may hold spaces and accents, never a slash (lutin.machines keeps [\w .-]). */
export function requestPath(request: { machine: string; right: Right }): string {
  return `/node/requests/${encodeURIComponent(request.machine)}/${request.right}`;
}
