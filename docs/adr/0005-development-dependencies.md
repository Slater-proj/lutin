# ADR 0005 — Development-only dependencies allowed; none at run time

- Status: Accepted
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

« Standard library only » is a founding decision ([DECISIONS.md](../DECISIONS.md), 2026-10-25) and stays: simple installation, small attack surface, real offline mode.
It was also applied to development: Ruff checks syntax errors and unused names only (`E9`, `F`), no function has a type annotation, there is no coverage measure,
and renaming 108 modules by hand is not realistic.

## Decision

- **Run time: no dependency.** `dependencies = []` in `pyproject.toml` does not change.
- **Development: allowed**, declared in an optional group (`[project.optional-dependencies] dev`) and pinned for the CI:
  - Ruff with rules widened step by step (each new rule set is its own commit: the rule, then the fixes);
  - a type checker, introduced on new modules first, then module by module as they are renamed;
  - a syntax-tree refactoring tool for the renaming;
  - coverage measurement on the security-critical modules.
- **Front end** (ADR 0002): Node.js and its packages are build-time only.

Each tool is added when the step that needs it starts, not in advance.

## Consequences

- Positive: mechanical renaming, types on the contract, errors caught before review.
- Negative: contributors install a few tools (`pip install -e .[dev]`); tool versions must be kept up to date.
- Risks: a development dependency imported by mistake from `src/`. The packaging test installs the wheel in an empty environment and starts Lutin: it would fail.

## Rollback

Removing a tool is removing its line and its CI step.
