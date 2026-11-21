# ADR 0009 — Approval rules for commands: deny > ask > allow, and a hardline list

Status: accepted (plan step 5, item 5). Code: `src/lutin/approval_rules.py`; tests: `tests/test_approval_rules.py`.

## Context

Before a command runs, Lutin had two things to decide with: the automatic approval of the conversation (a switch) and the commands declared safe in the settings
(ADR 0006). Nothing could refuse a command for good, nothing could force a question when the switch was on, and a « yes » could not be remembered for less than
« everything, for this conversation ».

## Decision

- Three effects, in this order of strength: **deny > ask > allow**.
- Four sources, from the strongest: the **hardline list** (commands that destroy or take over a machine: always asked, the answer is never remembered, no rule
  and no switch lets them through); the **rules of the person** (data folder, `approval_rules.json`); the **rules of the project** (`.lutin/approvals.json` in the
  working folder: they can only ask or deny, because the model can write that file and a cloned repository can bring it); the answers **for this conversation**
  (in memory).
- A rule names a command exactly, or a beginning followed by ` *`.
- The answers on the approval card: « once », « for this conversation », « always » (a rule of the person, written from the machine itself only), and no.
- A rule that allows is treated as an automatic approval: it is still suspended after web content was read in the turn (the existing safeguard).
- Without any rule, nothing changes: the switch of the conversation decides as before.

## Not chosen

- Rules for file writes: the per-conversation switch stays the only way; a path rule needs the same care as the command shapes and was not needed yet.
- A « full trust » flag: refused in ATOMIC_AGENT.md.
- Patterns richer than a prefix (regular expressions written by a person are a known source of rules that allow too much).

## Going back

Delete `approval_rules.json` and the project file: `decide()` answers `none` and the behaviour is the one before the rules. The hardline list alone can be emptied in the module.
