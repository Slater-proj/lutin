# ADR 0022 — The old page and its routes are removed at 1.0; the machine protocol stays

Status: accepted on 2026-11-22 (the maintainer: « remove it all, I do not want to hear about the old interface and the obsolete code any more »).
Implemented. It replaces what ADR 0001, ADR 0002 and `docs/modernization/PARITY.md` said about keeping the old page at `/ancienne/` during 1.x.

## Context

At 1.0 the new interface (ADR 0002) was the default at `/` and the parity audit (`PARITY.md`) had found nothing the old page did that it did not.
The old page still lived at `/ancienne/`: one file of 538 kB, its two libraries (`web/lib/highlight.min.js`, `github-dark.min.css`), its
dictionary (`langues/interface.en.json`) and about 70 French routes in `server.py` (1,200 lines), with their tests. Each fix risked being made
twice, and the French routes were a second door to every action, with their own checks.

Some French routes were not used by the page only:

- `lutin chat`, `lutin pin`, `lutin devices` and the tray icon called `/api/chat`, `/api/etat`, `/api/nouveau-pin`, `/api/appareils*`…;
- the Docker job of the CI checked the image through `/api/etat`, `/api/reglages`, `/api/document`…;
- a machine that leads a conversation on another one (ADR 0016) sends its requests through `/api/noeud/relais/<route>`, and `<route>` is one of
  eleven French routes (`RELAIS_GET`, `RELAIS_POST` in `server.py`). The other machine may still run an older Lutin.

## Decision

1. The old page goes, with `/ancienne/`, `/h/` (the old page's view of a conversation on another machine), `/lib/`, `/ouvrir/` and
   `/api/ouvrir-chemin` (links of the old page), its libraries, its dictionary, `lutin.open_file`, and every function only it used
   (`lutin.diagnostic`, `lutin.performance_advice`, and about twenty functions in other modules).
2. The command line, the tray and the CI use `/api/v1` (`lutin.client` prefixes every path with it and reads the v1 errors).
3. What stays outside `/api/v1` is what another program speaks, not a page:
   - `/api/appairer`, posted by the login page (the only request without a session: it is how one is obtained);
   - `/api/noeud/*`, the protocol between paired machines;
   - the eleven routes of the relay, answered **only** when the request came through `/api/noeud/relais` with a node token (`_via_relais`):
     called directly, they are 404. They move to `/api/v1` paths when the relay does, in a 1.x version that can still talk to an older machine;
   - `/image/`, `/piece/`, `/fichier/`: the addresses `/api/v1` gives for media, attachments and produced files, opened by `<img>` and links
     with the session cookie.

## Consequences

- `server.py` goes from 1,934 to 730 lines; the package loses 560 kB.
- A version before 1.0 cannot be driven through the removed routes. `lutin update --rollback-to` still installs one.
- The tests that went through French routes either use `/api/v1` or were removed when a `/api/v1` test already covers the same behaviour.
