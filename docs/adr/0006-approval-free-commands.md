# ADR 0006 — Approval-free commands run without a shell, one validator per program

- Status: Accepted, implemented (`src/lutin/safe_commands.py`, `tests/test_safe_commands.py`)
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

The `executer` tool asks the user before running a command, except for « simple reads » (`git status`, `dir`, `type`, `ls`, `cat`, `echo`…), so that a model
looking around does not raise a prompt at every step. Those reads were recognised by a regular expression over the command line, and the line was then
handed to a shell (`cmd.exe` or `sh`).

A shell rewrites the line after the check. The audit reproduced that these all matched the whitelist and would have run without approval:

| Command | Effect |
|---|---|
| `type %USERPROFILE%\.ssh\id_rsa`, `type \Users\…`, `cat $HOME/…` | reads any file of the user, outside the workspace — including Lutin's own tokens |
| `echo $(…)`, `` echo `…` ``, `ls` + newline + another command | runs any command (POSIX) |
| `git branch -D main`, `git branch -f main HEAD~5` | changes the repository |

Web access is on by default and reading a page needs no approval, so a booby-trapped page could chain: read a secret, then fetch an address carrying it.
The suspension of automatic approvals after a web read did not cover these commands, since they never asked.

## Options considered

1. Remove the facility: every command asks.
2. Keep the regular expression and add more forbidden characters.
3. Never give an approval-free command to a shell; validate each argument with rules written for its program.

## Decision

Option 3.

- A command runs without approval only if `safe_commands.plan()` returns a plan. Otherwise the normal path applies: the user is asked, then the shell runs it — nothing is lost, it just asks.
- A plan is carried out without a shell: `git`, `ls`, `cat`, `pwd`, `which`, `where`, `python -V` are started from an argument list; `echo` is answered by Lutin;
  on Windows `dir` and `type` (built into `cmd.exe`, so impossible to start without it) are answered by Lutin's own listing and reading tools, with their confinement.
- Refused in every case: control characters, `| & ; < >`, backquote, `$`.
- Paths are checked by the workspace confinement already used by the file tools (`outils.chemin_sur`): inside the workspace, outside `.git` and outside Lutin's data.
- `git`: reading sub-commands only; `--output`, `--no-index`, `--ext-diff`, `--help` refused; `git branch` restricted to its listing forms.
- Commands the user declared safe (Settings > Tools) take simple arguments only (letters, digits, `_ . / : = - \`).
- On Windows, a program that is a `.bat` or `.cmd` script is started through `cmd.exe` by the system: it only receives arguments `cmd.exe` cannot interpret.
- The former whitelist stays as a first filter (hardened: no newline, no `$`, no backquote), so three checks must agree.

## Consequences

- Positive: nothing is expanded, substituted or chained after the check, because nothing reads the line after it.
- Negative, visible to users:
  - `dir` and `type` answer in Lutin's format (the listing and reading tools), not `cmd.exe`'s; `dir` options other than `/b` ask for approval;
  - `echo` with variables or wildcards asks for approval;
  - a declared-safe command with quoted or unusual arguments (`pytest -k "a or b"`) asks for approval.
- Risks: a validator that is too permissive for one program. Each program has its own rules and its own tests; adding a program means adding both.
  `git` still obeys the repository's and the user's configuration (external diff drivers, `core.fsmonitor`): the `.git` folder is protected from the agent's
  file tools, but a repository whose configuration is already hostile is outside what this guard covers.
- Maintenance cost: one validator per program.

## Migration and rollback

No data, no setting changes. Reverting the commit restores the former behaviour (and the vulnerability).
