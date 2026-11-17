import { describe, expect, it } from "vitest";
import { actionsOf, choiceValue, parseChoice, rightsToAsk, selector, type MachinesView, type PairedMachine } from "./machines";

const ID = "a".repeat(32);

function machine(changes: Partial<PairedMachine> = {}): PairedMachine {
  return {
    id: ID, name: "Bureau", address: "http://192.168.1.20:8777", mac: "", mac_auto: false, added: "2026-11-17", warnings: [], state: "operational",
    detail: "", step: null, shutdown_in_s: null, wake_failed: false, models: ["qwen3:8b"], load: null, version: "1.0", update_available: false,
    allowed: { lead: false, update: false, shutdown: false }, requested: [], shares: { skills: false, memory: false }, ...changes,
  };
}

const view = (answering: string, machines: PairedMachine[] = [machine()]): MachinesView => ({ enabled: true, answering, machines, log: [] });

describe("the choice of the model selector", () => {
  it("keeps the machine and a model whose name holds the separator", () => {
    expect(parseChoice(choiceValue(ID, "hf.co/x|y:Q4"))).toEqual({ machine: ID, model: "hf.co/x|y:Q4" });
    expect(parseChoice(choiceValue("", "qwen3:8b"))).toEqual({ machine: "", model: "qwen3:8b" });
    expect(parseChoice("qwen3:8b")).toEqual({ machine: "", model: "qwen3:8b" });
  });

  it("groups the models of each machine that answers, under its name", () => {
    const shown = selector(["gemma3"], "gemma3", [{ machine: ID, machine_name: "Bureau", state: "operational", models: ["qwen3:8b"] }], view(""));
    expect(shown.groups).toEqual([{ machine: ID, name: "Bureau", models: ["qwen3:8b"] }]);
    expect(shown.current).toBe(choiceValue("", "gemma3"));
    expect(shown.missing).toBeNull();
  });

  it("says when the chosen machine went off, and keeps the choice visible", () => {
    const shown = selector(["gemma3"], "qwen3:8b", [], view(ID));
    expect(shown.missing).toEqual({ machine: ID, name: "Bureau", model: "qwen3:8b", off: true });
    expect(shown.current).toBe(choiceValue(ID, "qwen3:8b"));
    expect(selector(["gemma3"], "qwen3:8b", [{ machine: ID, machine_name: "Bureau", state: "operational", models: ["qwen3:8b"] }], view(ID)).missing).toBeNull();
  });

  it("shows a model of this machine that is not installed, as before", () => {
    expect(selector(["gemma3"], "llama3", [], view("")).missing).toEqual({ machine: "", name: "", model: "llama3", off: false });
    expect(selector([], "", [], null).missing).toBeNull();
  });
});

describe("a machine card", () => {
  it("wakes only a machine that is off and has its MAC address", () => {
    expect(actionsOf(machine({ state: "unreachable" }))).toEqual([]);
    expect(actionsOf(machine({ state: "unreachable", mac: "00:1A:2B:3C:4D:5E" }))).toEqual(["wake"]);
    expect(actionsOf(machine({ mac: "00:1A:2B:3C:4D:5E" }))).toEqual([]);
  });

  it("shuts down and updates only with the right the machine grants", () => {
    expect(actionsOf(machine({ update_available: true }))).toEqual([]);
    expect(actionsOf(machine({ allowed: { lead: false, update: true, shutdown: true }, update_available: true }))).toEqual(["shutdown", "update"]);
    expect(actionsOf(machine({ allowed: { lead: false, update: false, shutdown: true }, shutdown_in_s: 20 }))).toEqual(["cancel-shutdown"]);
  });

  it("offers to ask for a right neither granted nor waiting", () => {
    expect(rightsToAsk(machine({ allowed: { lead: true, update: false, shutdown: false }, requested: ["update"] }))).toEqual(["shutdown"]);
  });
});
