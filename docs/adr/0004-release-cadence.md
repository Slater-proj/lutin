# ADR 0004 — Pre-releases during the migration instead of a release per merge

- Status: Accepted, implemented (`tools/release_channel.json`, `tools/prochaine_version.py`, `.github/workflows/release.yml`; the `main` path of the workflow has not run yet)
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

Every merge into `main` publishes a version, a GitHub Release and Docker images (`.github/workflows/release.yml`): 137 versions in seventeen days.
During the migration, `main` will receive mechanical renamings and half-migrated screens that nobody should install as « the latest version ».

## Decision

- The migration lives on the `modernization` branch. Branches already produce candidates without a tag: that mechanism is kept for testing.
- While the migration lasts, `main` only receives fixes of the current line (0.50.x).
- Milestones of the migration are published as **pre-releases** (`1.0.0-alpha.N`, then `-beta.N`), marked as such on GitHub and never tagged `:latest` for Docker,
  and never offered by the in-app update notice.
- 1.0.0 is published when the acceptance criteria of [../modernization/PLAN.md](../modernization/PLAN.md) are met.
- After 1.0: releases are cut on purpose (a tag), not by every merge.

## Consequences

- Positive: an installed Lutin does not update itself into a half-migrated state; the changelog becomes readable.
- Negative: `tools/prochaine_version.py` and `release.yml` must learn pre-releases; the update check must ignore them.
- Risks: the pre-release path of the workflow only runs on `main`: it is covered by the tests of the version computation, not yet by a real run. The first merge should be watched.

## Migration and rollback

The workflow change is a separate, small commit with its own tests (`tests/test_version.py`). Reverting it restores a release per merge.
