# ADR 0002 — New interface in Svelte 5 + TypeScript + Vite, shipped prebuilt

- Status: Accepted
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

The interface is one file, `src/lutin/web/index.html` (543 kB): about 4 500 lines of JavaScript in a single function, 8 pages, 298 element ids, a dark theme only.
It is carefully written — the page is built with `textContent` and `createElement`, never from HTML text — but it cannot be redesigned or shared between contributors
as it stands, and the browser tests are tied to its ids and French labels.

Constraints: no Node.js for end users, no run-time dependency, the wheel must stay self-contained and work offline.

## Options considered

1. JavaScript modules without a build step (types checked through JSDoc).
2. Svelte 5 + TypeScript + Vite.
3. React or Vue + TypeScript + Vite.

## Decision

Option 2, under three conditions:

1. **Prebuilt assets.** The CI builds the interface and puts the result in the wheel and the source archive. Installing or running Lutin never needs Node.js;
   only contributors to the interface do. A test fails if the shipped assets do not match the sources.
2. **Coexistence.** The new interface is served next to the old page until it reaches parity, screen by screen. The old page is removed only then, with its tests replaced.
3. **A versioned API.** The new interface talks to `/api/v1` (ADR 0001), never to the French routes.

## Rationale

Option 1 has the lowest risk but no component model: a design system and five redesigned areas would be written by hand again.
Option 3 brings the largest contributor pool at the price of a heavier bundle and more code, for no gain in this application.
Svelte compiles to a small static bundle, reports accessibility mistakes at build time and keeps components short.

## Consequences

- Positive: components, typed state, a design system with light and dark themes, tests per component.
- Negative: a build step and a `package.json` to maintain (lock file, Dependabot); a smaller pool of contributors than React.
- Risks: this is the largest item of the plan (XL). The existing browser tests do not transfer; parity must be proven screen by screen.
- Maintenance cost: front-end dependencies, pinned and updated monthly like the CI actions.

## Migration and rollback

Until parity the old page remains the default; the new one is opt-in. Going back is a setting, not a release. After the switch, the last version
carrying the old page stays installable (`lutin update --rollback-to`).
