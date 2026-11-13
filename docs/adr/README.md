# Architecture decision records

One file per structuring decision of the modernization: what was chosen, what was not, and how to go back. An ADR is not edited once accepted; a later
decision supersedes it with a new file and a line in the old one. The earlier decisions of the project stay in [DECISIONS.md](../DECISIONS.md).

These records are technical documentation, written in English only (ADR 0001). The plan they belong to is in [../modernization/PLAN.md](../modernization/PLAN.md).

| # | Decision | Status |
|---|---|---|
| [0001](0001-english-and-clean-break-at-1.0.md) | English is the language of the code; a clean compatibility break at 1.0 | Accepted |
| [0002](0002-frontend-svelte-typescript-vite.md) | New interface in Svelte 5 + TypeScript + Vite, shipped prebuilt | Accepted |
| [0003](0003-scope-freeze-and-support-tiers.md) | Feature freeze during the migration; support tiers | Accepted |
| [0004](0004-release-cadence.md) | Pre-releases during the migration instead of a release per merge | Accepted |
| [0005](0005-development-dependencies.md) | Development-only dependencies allowed; none at run time | Accepted |
| [0006](0006-approval-free-commands.md) | Approval-free commands run without a shell, one validator per program | Accepted, implemented |
| [0007](0007-model-facing-language.md) | Language of tool names and system prompts: measure before switching | Accepted |
| [0008](0008-outbound-web-guard.md) | Outbound web requests: pinned address, redirections checked hop by hop | Accepted, implemented |
