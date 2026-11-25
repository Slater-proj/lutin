// The flow of an add-on as the editor handles it. Pure functions (tested in addonflow.test.ts).

export type Flow = Record<string, unknown>;

export type Parsed = { ok: true; flow: Flow } | { ok: false };

/** The flow written in the box, if it is a JSON object. Whether it is a good flow (structure, hosts) is the server's to say: it checks before keeping. */
export function parseFlow(text: string): Parsed {
  try {
    const value: unknown = JSON.parse(text);
    if (value !== null && typeof value === "object" && !Array.isArray(value)) return { ok: true, flow: value as Flow };
  } catch {
    // not JSON: said by the caller
  }
  return { ok: false };
}

/** The text shown in the box: the same JSON for the same flow, indented, so that « changed » means something. */
export function flowText(flow: Flow): string {
  return JSON.stringify(flow, null, 1);
}

/** Whether the box holds something other than the flow in force (only a valid JSON object can be compared; anything else counts as changed). */
export function isChanged(text: string, flow: Flow): boolean {
  const parsed = parseFlow(text);
  return !parsed.ok || flowText(parsed.flow) !== flowText(flow);
}

/** The proposal can be offered only after a check that failed: the server refuses otherwise, and the button would promise something that cannot happen. */
export function canPropose(check: { ok: boolean } | null): boolean {
  return check !== null && !check.ok;
}
