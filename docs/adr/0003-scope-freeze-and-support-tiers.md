# ADR 0003 — Feature freeze during the migration; support tiers

- Status: Accepted
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

In seventeen days the project gained five engine families, multi-machine operation, wake-on-LAN, six add-ons, scheduled tasks and third-party skills,
written by one person. [DECISIONS.md](../DECISIONS.md) says plainly what has never run on real hardware (macOS, AMD and Intel graphics, Linux with a real card).
The risk for a credible public release is the breadth of what is promised, not a missing feature. Renaming every module while features keep landing would also conflict daily.

## Decision

1. **Freeze.** From the start of the renaming (plan step 3) to the end of the interface migration (step 4), no new feature. Fixes, security, tests and the migration itself only.
2. **Support tiers**, shown in the documentation and in the interface:
   - *Supported*: exercised by the CI and on the maintainer's hardware.
   - *Experimental*: written and tested with fakes, never validated on real hardware. Shown as such wherever the user chooses it.
   The list per tier is drawn up from « Known but not verified » in DECISIONS.md and kept there.
3. **Strategic axes** examined during the audit:
   - retained after stabilisation: model router, projects/backups/memory as one area, hardware and model monitoring;
   - retained in a reduced form: a signed catalogue of MCP connectors and skills (no marketplace, no third-party Python plug-ins: they cannot be isolated in-process);
   - deferred: multi-agent studio;
   - not retained before 1.0: visual workflow editor, knowledge graph, an IDE-like coding workspace.

## Consequences

- Positive: the migration can finish; what is announced is what works.
- Negative: ideas wait. Features already written but unverified are labelled experimental rather than removed.
- Risks: pressure to « just add » something during the freeze; any exception is a new ADR.

## Rollback

The freeze ends by decision of the maintainer; nothing technical depends on it.
