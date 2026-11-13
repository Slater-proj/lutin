# ADR 0008 — Outbound web requests: pinned address, redirections checked hop by hop

- Status: Accepted, implemented (`src/lutin/net_guard.py`, `tests/test_net_guard.py`)
- Date: 2026-11-11
- Deciders: maintainer (the audit finding was accepted with the plan; the design is recorded here)

## Context

`web_lire` and `web_chercher` fetch addresses chosen by a model that may have just read an untrusted page. Lutin refused local addresses
by resolving the host name and checking its addresses, then asked the HTTP library to fetch the URL. The audit reproduced three weaknesses:

1. **Redirections.** The library followed a redirection by itself; its target was checked afterwards. The internal service had already received the request.
2. **Two resolutions.** The name was resolved for the check, then again by the library to connect. A DNS answer that changes in between (« rebinding ») connects elsewhere than what was checked.
3. **Ranges.** `100.64.0.0/10` (carrier-grade NAT, and the range Tailscale gives its machines) was accepted.

## Decision

A small module, standard library only, used by `web.web_telecharger`:

- **One resolution, by the connection.** The connection resolves the name, refuses unless every address is public, and connects to the address it just checked.
  The TLS certificate is still verified against the name.
- **No automatic redirection.** Each hop — the first address and every redirection target — goes through the caller's check (scheme, offline mode, host) before anything is sent. Five hops at most.
- **Headers given for one host stay with it.** An API key sent to a search provider is not carried to another host by a redirection.
- **Public means public.** Refused: loopback, private, link-local, carrier-grade NAT, multicast, reserved, unspecified, and IPv6 forms embedding such an IPv4 address
  (IPv4-mapped, NAT64, 6to4, Teredo).
- **The test switch needs two variables.** `LUTIN_WEB_LOCAL=1` reaches fake local services only together with `LUTIN_TESTS=1`, which the test suite alone sets.
- The one local host the user configured himself (his SearXNG) stays reachable, as before, and only for that purpose.

## Known limits

- **Behind a system proxy**, the proxy resolves the name: the address cannot be pinned. Lutin then falls back to checking the name before each request
  (redirections are still checked hop by hop). The rebinding window remains in that configuration.
- The add-ons (`addons.py`, `addons_comfyui.py`, `addons_mail.py`) keep their own guards: hosts restricted by a shipped manifest or a fixed list, redirections
  refused or controlled. They do not pin the address yet.
- The page preview (`apercu.py`) only opens workspace files and this machine's addresses, by design; it is not concerned.

## Consequences

- Positive: the address checked is the address connected; a redirection cannot reach the local network; fewer DNS queries.
- Negative: behind a system proxy the address is not pinned (see the limits above); a site that needs more than five redirections fails.
- Risks: the module overrides `connect()` of the standard HTTP connection classes. A test asserts that a name resolving to the loopback is refused with
  no request sent and a single resolution: if a future Python changed the classes, the test would fail rather than the guard silently disappear.

## Rollback

Reverting the commit restores the former behaviour (and the three weaknesses). No data or setting is involved.
