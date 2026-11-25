// Lutin's own version (docs/modernization/PARITY.md, item 6): what /status and /lutin/update say, and waiting for Lutin to come back after a
// restart. The server has the last word: these are its shapes (tests/test_api_v1_lutin.py) and the page only follows them.

export interface NewVersion {
  version: string;
  page: string; // the release notes
  command: string; // what does the same in a terminal: `lutin update`, or the docker one
}

export type UpdateState = "idle" | "running" | "failed" | "up_to_date" | "restarting" | "installed";

export interface UpdateView {
  state: UpdateState;
  lines: string[];
  before: string;
  after: string;
  command: string;
  can_update: boolean; // false in Docker: the image is replaced instead
  can_check: boolean; // false when this launch keeps no version cache
  can_restart: boolean; // something starts Lutin again when it stops
}

/** An update is followed while it runs; any other state is where it ended. */
export const updateOver = (state: UpdateState): boolean => state !== "running";

const LATER = "lutin-later-";

/** « Later »: the banner of this version stays hidden until the browser is closed. Storage may be refused (a private window): the banner then
 *  only hides until the page is reloaded. */
export function remindLater(version: string, storage?: Pick<Storage, "setItem">): void {
  try {
    (storage ?? sessionStorage).setItem(LATER + version, "1"); // reading `sessionStorage` itself throws when the site's storage is blocked
  } catch {
    // nothing kept: the banner comes back on the next reading
  }
}

export function remindedLater(version: string, storage?: Pick<Storage, "getItem">): boolean {
  try {
    return (storage ?? sessionStorage).getItem(LATER + version) === "1";
  } catch {
    return false;
  }
}

/** Waits until Lutin has stopped and answers again, then resolves. `answers` asks the server once (true when it answered). First the server must
 *  be seen gone: it stops a moment after answering the restart (and an update restarts later still); if it is never seen gone within `goneWithin`
 *  ms (a restart quicker than the readings), what answers is taken as the new one. Then it is asked until it answers, for at most `backWithin` ms;
 *  resolves with false if it never came back. */
export async function untilRestarted(answers: () => Promise<boolean>, { every = 1500, goneWithin = 20000, backWithin = 120000,
  sleep = (ms: number) => new Promise<void>((done) => setTimeout(done, ms)) } = {}): Promise<boolean> {
  let waited = 0;
  while (waited < goneWithin && (await answers())) {
    await sleep(every);
    waited += every;
  }
  waited = 0;
  while (waited < backWithin) {
    if (await answers()) return true;
    await sleep(every);
    waited += every;
  }
  return false;
}
