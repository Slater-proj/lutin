# The interface of Lutin

Svelte 5 + TypeScript + Vite ([ADR 0002](../docs/adr/0002-frontend-svelte-typescript-vite.md)). The build is written into `src/lutin/web/app/` and served by
Lutin under `/app/`, next to the present page, which stays the default until parity. State and parity lists: [INTERFACE.md](../docs/modernization/INTERFACE.md).

Node.js is needed to build the interface, never to install or run Lutin: the CI builds it into the wheel, the source archive and the Docker image.

```
npm ci --ignore-scripts    # the pinned development dependencies
npm run check              # types and Svelte diagnostics (accessibility included)
npm test                   # unit tests (Vitest)
npm run build              # writes ../src/lutin/web/app/
```

Then start Lutin and open `/app/`. The end-to-end tests are Python, with the rest of the suite: `tests/test_web_app.py` (what the server serves, and that the
build matches these sources) and `tests/test_web_app_chat.py` (the Chat screen in a real Chrome against a fake engine).

## Rules

- The page talks to `/api/v1` only (`src/lib/api.ts`), never to the French routes.
- The page is served under a content security policy that allows nothing inline and no other origin (`lutin.web_app.CSP`): no `style="…"` attribute,
  no inline script, no web font, no CDN. Classes and the tokens only.
- Every colour, size and space comes from `src/styles/tokens.css`. A component never writes a raw colour. Both themes are defined there, once.
- Every text is in `src/lib/messages.ts`, in English and in French; a unit test fails when a key has no French text.
- What can be a pure function is one (`src/lib/turn.ts`, `src/lib/stream.ts`) and has unit tests; components stay thin.
- Targets of 44 px at least, visible focus, real `<button>`, `<a>`, `<label>`: the screen must be usable with the keyboard alone and at 360 px wide.
