import { describe, expect, it } from "vitest";
import { latestOnly } from "./latest";

describe("overlapping requests", () => {
  it("only the last one started may apply its answer, whatever the order the answers arrive in", async () => {
    const opening = latestOnly();
    const shown: string[] = [];
    let answerA: (value: string) => void = () => undefined;
    let answerB: (value: string) => void = () => undefined;
    const open = async (answer: Promise<string>) => {
      const ticket = opening.begin();
      const read = await answer;
      if (opening.current(ticket)) shown.push(read);
    };
    const a = open(new Promise((resolve) => (answerA = resolve)));
    const b = open(new Promise((resolve) => (answerB = resolve)));
    answerB("B");
    await b;
    answerA("A"); // the slow answer of the first click comes last
    await a;
    expect(shown).toEqual(["B"]);
  });

  it("a new start with nothing to wait for cancels the one in flight", () => {
    const opening = latestOnly();
    const ticket = opening.begin();
    opening.begin(); // « New conversation » clicked while a conversation was loading
    expect(opening.current(ticket)).toBe(false);
  });
});
