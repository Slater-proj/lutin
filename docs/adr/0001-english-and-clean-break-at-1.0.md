# ADR 0001 — English is the language of the code; a clean compatibility break at 1.0

- Status: Accepted
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)
- Supersedes: the 2026-10-26 line of [DECISIONS.md](../DECISIONS.md) (« French stays the language the code is written in »)

## Context

Lutin is written in French: 108 modules, 2 022 functions, comments, commit messages. So is everything it exposes: about 185 HTTP routes
(`/api/reglages`), the JSON fields (`erreur`, `modele`), the stream events (`texte`, `approbation`), the keys of the files it stores (`titre`, `resume`),
its folders (`donnees`, `memoire`), 50 environment variables (`LUTIN_NIVEAU`), and the tool names given to the models (`lire`, `executer`).
The translation catalogues are keyed by the French sentence (2 246 + 1 675 entries). Only the command line already has English names with French aliases.

The project wants international contributors. It has very few external users today, which makes this the cheapest moment to change public names.

## Options considered

1. Rename the internals only; keep every public and stored name in French, forever.
2. Rename everything and keep the French names as aliases, with no end date.
3. Rename everything; one clean break at 1.0, with a one-shot migration of stored data.

## Decision

Option 3.

- **Code**: identifiers, comments, docstrings, commit messages and technical documentation are in English. New modules are written in English from now on.
  A change inside an existing French module follows the language of that file until the module itself is renamed, so that no file mixes two vocabularies.
- **Interface**: French and English remain user languages. English becomes the source language of the catalogues (the catalogues are inverted by script).
- **HTTP API**: a versioned English API, `/api/v1`, is built for the new interface (ADR 0002). The French routes stay as they are while the old page exists
  and are removed with it. They are not aliased.
- **Stored data**: migrated once, at the first start of 1.0, by a versioned, idempotent migration that first writes a backup. No French key is read afterwards.
- **Environment variables**: the one place where the old names stay as aliases (a single lookup function): they live in users' compose files and scripts.
- **Command line**: unchanged (English names, French aliases already in place).
- **Tool names and prompts sent to the models**: see ADR 0007.

## Rationale

Option 1 leaves the contract a contributor meets first (API, stored files) in French. Option 2 doubles every public name and every test for years, to protect
users who do not exist yet. Option 3 costs one migration, tested on real data from the previous version, at the moment the user base is smallest.

## Consequences

- Positive: one vocabulary; a documented, versioned API; the frontend rewrite and the API renaming are one piece of work instead of two.
- Negative: 0.x data cannot be opened by 1.0 without the migration; a machine paired with an older Lutin must be updated (the node protocol is versioned at the same time).
- Risks: a long-lived renaming branch conflicts with daily work — hence the freeze (ADR 0003) and renaming module by module on the integration branch.
- Maintenance cost: the environment-variable aliases only.

## Migration and rollback

Each renaming step is a mechanical commit verified by the full test suite; reverting it is `git revert`. The data migration keeps its backup:
restoring it and reinstalling the previous version (`lutin update --rollback-to X.Y.Z`) returns to the earlier state. The migration is not written yet:
its acceptance criteria are in [../modernization/PLAN.md](../modernization/PLAN.md).
