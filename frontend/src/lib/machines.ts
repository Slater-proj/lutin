// The paired machines (ADR 0016): other computers running Lutin whose engine this one may use. The shapes of GET /machines and of `remote` in
// GET /models, the choice of the model selector (a model of this machine or of a paired one) and what a machine card offers. Pure functions,
// tested in machines.test.ts; the texts are in messages.ts under `machines.*`.

export type Right = "lead" | "update" | "shutdown";
export const RIGHTS: readonly Right[] = ["lead", "update", "shutdown"];

export type MachineState = "unknown" | "unreachable" | "wake_sent" | "reachable" | "operational";
export type MachineStep = "off" | "waking" | "powered_on" | "lutin_started" | "syncing" | "ready" | "shutting_down" | "updating";

export interface Load {
  busy_here: boolean;
  remote_turns: number;
  ram: { total: number | null; free: number | null } | null;
  vram: { total: number | null; free: number | null; name: string } | null;
}

export interface PairedMachine {
  id: string;
  name: string;
  address: string;
  mac: string;
  mac_auto: boolean;
  added: string;
  warnings: string[];
  state: MachineState;
  detail: string;
  step: MachineStep | null;
  shutdown_in_s: number | null;
  wake_failed: boolean;
  models: string[];
  load: Load | null;
  version: string;
  update_available: boolean;
  allowed: Record<Right, boolean>;
  requested: Right[];
  shares: { skills: boolean; memory: boolean };
}

export interface MachinesView {
  enabled: boolean;
  answering: string;
  machines: PairedMachine[];
  log: string[];
}

/** The models of a paired machine that answered in the last 40 s (`remote` in GET /models). */
export interface RemoteModels {
  machine: string;
  machine_name: string;
  state: MachineState;
  models: string[];
}

/** The value of an entry of the model selector: the machine ("" for this one) and the model. A machine id never holds « | »; a model name may. */
export function choiceValue(machine: string, model: string): string {
  return machine + "|" + model;
}

export function parseChoice(value: string): { machine: string; model: string } {
  const cut = value.indexOf("|");
  return cut < 0 ? { machine: "", model: value } : { machine: value.slice(0, cut), model: value.slice(cut + 1) };
}

export interface Selector {
  local: string[];
  groups: { machine: string; name: string; models: string[] }[];
  /** The value of what is chosen now. */
  current: string;
  /** The chosen model is not in the lists (not installed here, or its machine went off): shown on its own so the choice stays visible. */
  missing: { machine: string; name: string; model: string; off: boolean } | null;
}

/** What the model selector of the Chat shows: the models of this machine, then those of each paired machine that answers, under its name. */
export function selector(local: string[], current: string, remote: RemoteModels[], view: MachinesView | null): Selector {
  const answering = view?.answering ?? "";
  const groups = remote.filter((entry) => entry.models.length > 0).map((entry) => ({ machine: entry.machine, name: entry.machine_name, models: entry.models }));
  const here = answering === "" ? local.includes(current) : groups.some((group) => group.machine === answering && group.models.includes(current));
  let missing: Selector["missing"] = null;
  if (!here && current) {
    const paired = view?.machines.find((machine) => machine.id === answering);
    missing = { machine: answering, name: paired?.name ?? "", model: current, off: answering !== "" };
  }
  return { local, groups, current: choiceValue(answering, current), missing };
}

export type MachineAction = "wake" | "shutdown" | "cancel-shutdown" | "update";

/** The buttons a machine card offers now. Waking needs the MAC address of the machine; the other three need the right the machine grants. */
export function actionsOf(machine: PairedMachine): MachineAction[] {
  const on = machine.state === "operational" || machine.state === "reachable";
  const actions: MachineAction[] = [];
  if (!on && machine.mac) actions.push("wake");
  if (machine.shutdown_in_s !== null) actions.push("cancel-shutdown");
  else if (on && machine.allowed.shutdown) actions.push("shutdown");
  if (on && machine.allowed.update && machine.update_available) actions.push("update");
  return actions;
}

/** The rights one may still ask the machine for: neither granted nor already waiting for its owner's answer. */
export function rightsToAsk(machine: PairedMachine): Right[] {
  return RIGHTS.filter((right) => !machine.allowed[right] && !machine.requested.includes(right));
}
