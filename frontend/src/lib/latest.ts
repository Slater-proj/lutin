/** Several requests overlap (a conversation clicked, then another): only the last one started may apply its answer.
 * `begin()` gives a ticket before the request; after each `await`, `current(ticket)` says whether that answer is still wanted. */
export function latestOnly(): { begin(): number; current(ticket: number): boolean } {
  let last = 0;
  return {
    begin: () => ++last,
    current: (ticket) => ticket === last,
  };
}
