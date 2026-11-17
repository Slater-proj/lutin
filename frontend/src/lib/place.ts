// Where a conversation is held: this machine ("") or a paired machine (its id), ADR 0016 stage 6. Every path of the Chat that names a conversation,
// an approval or a file goes through here, so a conversation led on another machine uses its relayed routes (/machines/{id}/…) and nothing else.
// Pure functions, tested in place.test.ts.

const enc = encodeURIComponent;
const root = (machine: string): string => (machine ? `/machines/${enc(machine)}` : "");

/** The path of a conversation, under /api/v1: `/conversations/{id}` here, `/machines/{machine}/conversations/{id}` on another machine. */
export function conversationPath(machine: string, id: string): string {
  return `${root(machine)}/conversations/${enc(id)}`;
}

export function approvalPath(machine: string, id: string): string {
  return `${root(machine)}/approvals/${enc(id)}`;
}

/** Where a file for the next message is sent: the machine that holds the conversation keeps it. */
export function uploadPath(machine: string, kind: "images" | "attachments"): string {
  return `${root(machine)}/${kind}`;
}

/** The address of an image sent in a conversation (an <img> sends the session cookie: the route asks no page token). */
export function imageUrl(machine: string, id: string): string {
  return `/api/v1${root(machine)}/images/${enc(id)}`;
}

/** The address of a document sent in a conversation, saved under its name. */
export function attachmentUrl(machine: string, id: string, name: string): string {
  return `/api/v1${root(machine)}/attachments/${enc(id)}?name=${enc(name)}`;
}

/** A conversation of the list: local ones have no machine. */
export interface Listed {
  id: string;
  title: string;
  pinned: boolean;
  machine: string;
  machine_name: string;
}

/** The conversations of the other machines, grouped under each machine's name, in the order they come. */
export function byMachine(remote: Listed[]): { machine: string; name: string; conversations: Listed[] }[] {
  const groups: { machine: string; name: string; conversations: Listed[] }[] = [];
  for (const entry of remote) {
    let group = groups.find((item) => item.machine === entry.machine);
    if (!group) groups.push((group = { machine: entry.machine, name: entry.machine_name, conversations: [] }));
    group.conversations.push(entry);
  }
  return groups;
}
