# The new interface: state

Plan step 4 ([PLAN.md](PLAN.md), [ADR 0002](../adr/0002-frontend-svelte-typescript-vite.md)). Sources in `frontend/`, served under `/app/`; the present page at `/` stays the default.
This page says what exists, what was verified and how, and what is missing. It is updated with each screen.

## Foundation

| Piece | State |
|---|---|
| Project (Svelte 5, TypeScript, Vite), build into `src/lutin/web/app/` | done |
| Served by Lutin under `/app/`, session required, strict content security policy | done — `tests/test_web_app.py` |
| A shipped build that no longer matches its sources is detected | done — same hash computed by the build and by Python |
| Built by the CI before tests and packaging; wheel checked for the built files | written, **never run**: the branch has not been pushed |
| Design tokens, light and dark themes, theme kept per browser | done |
| Shell with the five areas (Chat, Agents, Projects, Models, Settings), icons, navigation bar at the bottom on a phone | done; four areas say « not here yet » and link to the present page |
| Texts in English and French | done — a unit test fails on a missing French text |
| Base components (button, card, field…) as shared components | not yet: styles are shared classes, components come with the second screen |
| Offline: no font, no CDN, nothing fetched from another origin | done — enforced by the policy |

## Chat

Verified end to end in a real Chrome against a fake engine (`tests/test_web_app_chat.py`): page loads without any policy violation; a message is sent and
the answer is written as it arrives; Markdown is drawn and no HTML comes out of an answer; an action waits for an approval given on the page and a refusal leaves the file untouched;
a conversation is renamed and pinned; a message is edited and the conversation goes on from it; a refusal of the server is shown and the message
given back; themes; no overflow at 360 px.

Not verified: a real engine, a real phone, a screen reader, other browsers than Chrome, automated accessibility checks (WCAG 2.2 AA is the target, no tool has been run yet).

| Present page | New interface |
|---|---|
| List, open, create, delete a conversation | done |
| Send a message, answer written as it arrives, stop | done |
| Reasoning, tool calls and results, notices, dry runs, errors | done |
| Approval of an action, with its diff | done |
| « Summary or progress sheet » question of a long conversation | done (the route is tested; the card has no end-to-end test) |
| Choice of the model | done (changes the setting, as the present page does) |
| Context gauge, speed, task list | done, during the turn only |
| Markdown in answers: headings, lists, tables, quotes, links, code blocks with a copy button | done — own parser (`frontend/src/lib/markdown.ts`), no HTML ever interpreted |
| Syntax colouring of code, diagrams (Mermaid), formulas | missing |
| Rename, pin a conversation | done |
| Edit a message and answer again from it | done |
| Images and attached documents | missing (upload routes are not in v1 yet) |
| Per-conversation options: mode, automatic approvals, mission | missing (not in v1 yet) |
| Conversations led on another machine | missing (not in v1 yet) |
| Reconnecting to a turn still running after a reload | missing: the page shows the stored conversation, not the running answer |

This list comes from the routes the present page calls for a conversation; it is not yet a complete audit of the present page, which the acceptance of the
screen requires (plan step 4: « functional parity with the old page listed and checked »).
