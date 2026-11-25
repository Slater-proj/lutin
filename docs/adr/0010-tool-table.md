# ADR 0010 — One table says what each tool does

Status: accepted (plan step 5, item 3). Code: `src/lutin/tool_table.py`; tests: `tests/test_tool_table.py`.

## Context

What a tool changes (nothing, Lutin's notes, files, anything through a command, another program) was written in several lists: the tools of the research mode,
what asks for an approval, what a dry run simulates. They could drift apart without a test noticing.

## Decision

`tool_table.TABLE` has one entry per tool offered to the models: its `effect` (`read`, `notes`, `files`, `command`, `external`, `control`), whether it `asks`
before acting, whether it uses the `network`. The names are the ones the models see (ADR 0007). The research mode reads its list from the table. A conformance
test fails when a tool has no entry, when an entry has no tool, and when « asks » does not match the source of the tool.

## Not done yet

The schema, the result budget and the resource class of each tool are still where they were (`tools.OUTILS`, the settings). The loop does not yet read the table
to run read-only calls together (plan step 5, item 4): the table is what makes that possible.
