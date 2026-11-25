import type { TurnEvent } from "./types";

/** Reads a stream of JSON lines as it arrives, whatever the cuts between the pieces. An empty line is the heartbeat of the server;
 * a line that is not an event (cut connection) is dropped: the conversation is reloaded at the end of the turn anyway. */
export function lineParser(onEvent: (event: TurnEvent) => void): { push(chunk: string): void; end(): void } {
  let rest = "";
  const emit = (line: string): void => {
    if (!line) return;
    try {
      const event: unknown = JSON.parse(line);
      if (event !== null && typeof event === "object" && typeof (event as { type?: unknown }).type === "string") {
        onEvent(event as TurnEvent);
      }
    } catch {
      // not a complete line of JSON
    }
  };
  return {
    push(chunk: string): void {
      rest += chunk;
      let cut = rest.indexOf("\n");
      while (cut >= 0) {
        emit(rest.slice(0, cut).trim());
        rest = rest.slice(cut + 1);
        cut = rest.indexOf("\n");
      }
    },
    end(): void {
      emit(rest.trim());
      rest = "";
    },
  };
}
