**English** · [Français](CLUSTER_ARCHITECTURE.fr.md)

# Machines: make Lutin answer with another machine's engine

A small PC (a Debian box without a graphics card, say) can answer with the engine of a PC with an NVIDIA card. **Every Lutin is a node**: no separate agent to install.

> **Honesty.** The protocol is tested with two real Lutin servers inside one test program, not on two computers. Nothing has been tried on a real network. Waking a powered-off machine arrives in 0.24.0.

## The principle

- The **node** (the PC with the card) lends its machine's engine. It is **off by default**; you turn it on in Settings > Machines ("Lend this machine's engine to other Lutin"), which needs the "network" access level (at "this machine only", nobody else could reach it).
- The **main** Lutin (the small PC) routes the conversation request to it **if** the node is operational for that model. Otherwise, or if the machine goes down, **the local engine answers, silently**.
- Routing first, spreading later. **A single model is never split between machines** (out of scope for 1.0).

## Adding a machine: explicit validation

1. On the node: Settings > Machines > "Allow a machine…" shows an **8-digit code**, valid 5 minutes, single use.
2. On the main one: Settings > Machines > "Add a machine": the node's address (`192.168.1.20` or `http://pc:8777`) and that code.
3. The node exchanges the code for a **node token**, specific to that machine. It keeps only its fingerprint (SHA-256). The main Lutin keeps the token, **never showing it**.

Never automatic acceptance, never network discovery. Too many code attempts from one address are blocked (as with the PIN code). **Revoking** a machine (on the node) cuts its access at once.

## What the token opens — and nothing else

`GET /api/noeud/etat`, `POST /api/noeud/chat`, that is all. The token opens **no conversations, no files, no settings, no memory**: every other path answers "authentication required" (automated test). The node keeps nothing of the requests: it runs its engine and returns the answer. It only passes the fields of a conversation to its engine (model, messages, tools, options…), nothing else, and never relays to a third machine.

## The four states

| State | Meaning |
|---|---|
| unreachable | no answer (off, off the network, Lutin stopped), or no longer the same machine at this address |
| wake-up sent | a wake-up packet was sent (0.24.0) |
| node reachable | the machine answers, but its engine is stopped or lacks the wanted model |
| engine operational | the machine can run this model: the request goes there |

The state is checked (kept 10 s) before anything is sent, and **the node's identifier is compared to the one from pairing**: if another machine took over the address, nothing is sent to it.

## An unreachable machine says nothing in the conversation

No error, no warning: the local engine answers. The state is visible in Settings > Machines, and the machines log only notes **one line per state change** (never per probe, never conversation content). A failure in the middle of an answer already started cannot be rescued by the local engine: it looks like any interrupted answer.

## Known limits

- The chosen model must have **the same name** on the node (otherwise the machine stays "reachable" and the local engine answers).
- The network is plain HTTP on the local network: the token and the conversations travel unencrypted. To go beyond your home, use an HTTPS proxy (see SECURITY.md). Never publish a node's port on the Internet.
- Only the engine chosen on the node is lent.
- Embeddings, images and background functions stay local.
