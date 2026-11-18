import { describe, expect, it } from "vitest";
import { remindedLater, remindLater, untilRestarted, updateOver } from "./lutin";

/** A server that answers according to `script` (true: it answers), one entry per reading; the last entry repeats. */
function server(script: boolean[]) {
  let reading = 0;
  const slept: number[] = [];
  return {
    answers: async () => script[Math.min(reading++, script.length - 1)],
    sleep: async (ms: number) => void slept.push(ms),
    readings: () => reading,
    slept,
  };
}

describe("Lutin's own version", () => {
  it("follows an update only while it runs", () => {
    expect(updateOver("running")).toBe(false);
    for (const state of ["idle", "failed", "up_to_date", "restarting", "installed"] as const) expect(updateOver(state)).toBe(true);
  });

  it("waits for the server to stop, then to answer again", async () => {
    const lutin = server([true, true, false, false, true]);
    expect(await untilRestarted(lutin.answers, { sleep: lutin.sleep })).toBe(true);
    expect(lutin.readings()).toBe(5);
  });

  it("does not take the server that has not stopped yet for the new one", async () => {
    const lutin = server([true, true, true, false, true]);
    await untilRestarted(lutin.answers, { sleep: lutin.sleep, every: 1000, goneWithin: 10000 });
    expect(lutin.readings()).toBe(5);
  });

  it("takes what answers when the restart was quicker than the readings", async () => {
    const lutin = server([true]);
    expect(await untilRestarted(lutin.answers, { sleep: lutin.sleep, every: 1000, goneWithin: 3000 })).toBe(true);
    expect(lutin.readings()).toBe(4);
  });

  it("gives up when the server never comes back", async () => {
    const lutin = server([false]);
    expect(await untilRestarted(lutin.answers, { sleep: lutin.sleep, every: 1000, backWithin: 5000 })).toBe(false);
  });

  it("remembers « later » for one version, and survives a storage that refuses", () => {
    const kept = new Map<string, string>();
    const storage = { getItem: (key: string) => kept.get(key) ?? null, setItem: (key: string, value: string) => void kept.set(key, value) };
    expect(remindedLater("1.2.0", storage)).toBe(false);
    remindLater("1.2.0", storage);
    expect(remindedLater("1.2.0", storage)).toBe(true);
    expect(remindedLater("1.3.0", storage)).toBe(false);
    const refusing = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
    expect(() => remindLater("1.2.0", refusing)).not.toThrow();
    expect(remindedLater("1.2.0", refusing)).toBe(false);
  });
});
