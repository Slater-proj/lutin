# Atomic Agent compared with Lutin

Study made in November 2026 to decide what Lutin should take from the best local-agent runtime of its ecosystem, and what it should not.

**Sources and their limits.** Atomic Agent: its site (atomicagent.io), its documentation (14 pages), its security, GBNF, Fusion and offline pages, and the READMEs of its repository
(`AtomicBot-ai/atomic-agent`, TypeScript on Node, MIT, 0.7.0). All of it was read through a model that summarised the pages: wording and numbers may be off, and **no source file of Atomic Agent was read nor run**.
Its documentation contradicts itself in places (v0.6.5 against 0.7.0, a prompt budget of 3 000 tokens against a 5 200-token prefix, an MCP panel with and without a restart key). Its benchmark (GAIA level 1, 53 tasks,
69.8 % against 58.5 % for another agent, one run per configuration, run by its maker, with a temperature that could not be controlled on the other side) is a claim, not a measure.
Lutin: read in the repository at `c41d07f` (greps and the headers of modules); a claim about Lutin below is a fact of the code unless it says otherwise.

## In one page

| Area | Atomic Agent | Lutin | Verdict |
|---|---|---|---|
| Agent loop | one inference = one step = an array of 1 to 16 calls, grammar-constrained; legs of 25 steps, task ceiling 1 000 steps or 2 h; parallel read-only batches; loop detector | `boucle_agent`, 14 steps by default (4 to 40), native tool calls, calls executed one by one; loop detector (3rd identical call warned, 5th stops the turn) | take parallel read-only batches; take the grammar **as an experiment** on llama.cpp only |
| Context and memory | stable byte-identical prompt prefix + bounded tail; SQLite with FTS5, versioned profile facts, lessons, procedures, optional embeddings | progress sheet kept by a scribe, thresholds 45/60/80 % of the window, summary-or-sheet choice, word search over files, optional embeddings through Ollama, **no SQLite at all** (JSON files) | take the prefix discipline and a SQLite store; keep the progress sheet |
| Tools | registry with a resource class per tool, about 60 tools, 1 000+ apps through Composio | about 27 tools, each switchable, bounds in `tool_settings`; no declared class | take the declared metadata; refuse Composio |
| Approvals | 5 levels, rules (deny > ask > allow), "once / this chat / always", hardline guard, shell unwrapping; **not a sandbox** | per-conversation switches, dry run, backup before every edit, validator without shell for « no approval » commands, auto-approval suspended after web content | take the rules engine and the three answers; keep our stricter defaults |
| MCP | stdio, streamable HTTP and SSE; `readOnlyHint` skips the prompt; no OAuth; fixed timeouts | stdio and HTTP; no tool offered until authorised one by one; read-only by default; every write asks at every call; results treated as untrusted web content | Lutin is ahead on safety; add the missing transports and sampling only if asked |
| Skills | `SKILL.md`, global and project folders, ClawHub and GitHub taps, scripts through the approval gate, import from other agents | same open format, listing in the prompt, GitHub install with a security analysis, no update of what Lutin did not install | at par; take import from other agents later |
| Scheduling | cron, interval, one-shot, webhooks; retry with backoff; no catch-up; overnight runs with budget | weekly days or once, read-only by design, notification channels, 10 last runs kept; long missions with a forced progress sheet | take cron/interval/webhook triggers and retry; keep read-only |
| Multi-agent (Fusion) | orchestrator plans and reviews, workers build in parallel in git worktrees, verification before acceptance, cost cap; default cloud planner + local workers | **no sub-agent**; paired machines, model router, missions | the best differentiating idea; build it on paired machines, local by default |
| llama.cpp | managed server, `cache_prompt` + slot reuse, GBNF grammar, own fork with a compressed KV cache (TurboQuant) | managed server with `--jinja`, machine-adapted flags, router mode; no grammar, no slot control found | measure prompt reuse first; grammar next |
| Desktop and terminal | Node binary (140 MB), Ink terminal UI, Tauri sidecar speaking NDJSON, OpenAI-compatible `serve`, Telegram and Discord | local web page, tray icon, `lutin chat`, PIN pairing of phones, no dependency | keep ours; take `/steer` and `/queue` ideas for the terminal |

## 1. Agent loop

1. **Atomic Agent.** One inference per step; a GBNF grammar forces an array of calls (up to 16 in the real grammar), so a malformed call is unreachable. After parsing: lookup, argument validation, danger check, run, compress the result, infer again.
   A batch has three phases (loop gate, grouped execution, terminal `reply`/`finish`); read-only tools fan out (8 by default, 16 at most), gated ones run alone. Legs of 25 steps, automatic continuation up to 1 000 steps or 2 hours.
   Loop detector with warning, critical and veto thresholds. Sessions: pending, running, awaiting approval, stalled, cancelled…
2. **Lutin.** `boucle_agent` (376 lines at the audit), 14 steps by default, tools executed in the order the model wrote them, stop honoured between calls, loop detection on identical calls and on repeated answers,
   tool results truncated, a retry ladder for empty answers (last attempt without tools), a router that can move up one model when the answer is empty.
3. **Improve.** Read-only calls in one step run together (reads, searches, web reads) and everything else stays sequential. Name the states of a turn (running, waiting for approval, stalled) so that the interface and the scheduler can show them.
   Split the loop (plan step 5) into a step executor, a batch policy and a finaliser, each testable.
4. **Take.** The batch idea with resource classes; the explicit session states; the loop detector thresholds as settings.
5. **Skip.** The JSON array as the only output shape and the `finish`/`reply` pseudo-tools: they exist to serve the grammar. 1 000-step tasks: a mission already exists and is bounded by hours.
6. **Implications and risks.** Parallel reads change the order of events in the stream (needs an ordered commit, as Atomic does); a tool wrongly declared read-only would run in parallel with a write. Needs the tool registry of section 3 first.

## 2. Context and memory

1. **Atomic Agent.** The prompt is a stable prefix (persona, rules, tool catalogue, skill index; about 5 200 tokens) plus a variable tail (loaded skills, profile, recalled notes, history), ordered from the slowest to the fastest changing, so that the cache of the engine is reused at every step.
   SQLite (`memory.sqlite`): notes with FTS5/BM25, a versioned profile (a new row supersedes the old), links between notes, lessons and procedures distilled every six hours, votes; optional embeddings with brute-force cosine; recall injected in the tail in a few hundred tokens.
   History is trimmed and tool results truncated; **no summarisation of history is documented**. Traces in NDJSON, plaintext, on by default.
2. **Lutin.** A progress sheet (goal, plan, step, done) written by a scribe every three answers, forced during missions; trimming at 45 % of the window, urgent at 60 % (80 % from the engine's real figures); a question « summary or sheet? » for long conversations;
   an archived beginning that can be recalled by words; optional meaning-based search through an Ollama embedding model with rank fusion; notes in `MEMOIRE.md`. **Nothing uses SQLite**; data are JSON files with atomic writes.
3. **Improve.** (a) Audit the order of the prompt: put what never changes first and what changes every turn last, and **measure** how many prompt tokens the engine re-reads at each step (Lutin already reads `prompt_eval_count`).
   (b) One local store for the index of conversations, notes and recall, with FTS5 (the Python standard library has SQLite: still zero dependency), created by the one-time data migration planned in step 3.
   (c) Version the facts about the user (a new value supersedes the old, history kept) instead of appending lines.
4. **Take.** Prefix discipline; FTS5 for recall; superseded facts; a bounded recall budget in the tail.
5. **Skip.** Automatic « reflection » by a small model that writes memory after each turn, the consolidator that invents lessons and procedures, votes and a link graph: a small local model writes wrong memories, and a wrong memory is read as truth for months.
   Memory in plaintext with traces stored verbatim and on by default: Lutin must keep traces opt-in and redacted.
6. **Implications and risks.** SQLite on a network share (WAL and locking are unreliable on SMB: Lutin data must stay on a local disk, which the NAS development copy is not); a migration to write once, with backup (plan step 3);
   the progress sheet is better than anything Atomic documents for long work and must not be replaced. Stable prefix: the date, the open files or any per-turn text placed early silently destroys cache reuse.

## 3. Tool architecture

1. **Atomic Agent.** One registry; each tool declares a name by family (`os.fs.read`, `browser.click`, `mcp.<server>.<tool>`), a resource class (pure read, memory write, browser, approval-gated…), a read-only flag and a danger flag; unknown names are rejected at invoke time;
   MCP tools are added to the registry and to the grammar; results are compressed (tail of a shell output, error signatures, a character cap per batch); a conformance test checks every tool against its contract.
2. **Lutin.** `tools.py` holds the schemas in one list (27 names: read, write, edit, run, search, web, symbols, tasks, memory, sheet, images, voice, missions…), `tool_settings` lets the user switch tools off and bound them;
   rights are declared per HTTP route in `api_v1` but **not per tool**: whether a tool needs an approval, writes, or can run in parallel lives in the code of each tool.
3. **Improve.** A tool table with metadata read by the loop: `readonly`, `needs_approval` (category), `resource_class`, `result_budget`, `since`. The approval engine, the batch executor, the scheduler's read-only mode and the dry run then read the same table
   (today the dry-run list and the scheduler's read-only list are written separately). A contract test per tool, like `test_api_access` does for routes.
4. **Take.** The table with metadata and the conformance test; the dedicated verification tools (`verify.syntax`, `verify.run` in a throwaway copy) as acceptance for missions.
5. **Skip.** 1 000+ apps through Composio (an American intermediary between the model and the user's mail and calendar: against a local-first promise); `os.email.*` through a vendor mailbox; desktop window control.
6. **Implications and risks.** The names of tools are what the models see (ADR 0007: measure before translating); a registry refactor must keep them byte-identical until the bench says otherwise.

## 4. Approvals and permissions

1. **Atomic Agent.** Five cumulative levels (paranoid, workspace, home, operator, full trust), default the strictest; rules in `approval-rules.json` (global, and per project where only `ask` and `deny` count, because the model can write in the workspace), precedence deny > ask > allow;
   answers « once », « this chat », « always » (saved as a rule), « deny »; a hardline guard that no rule overrides (`rm -rf`, `sudo`, `bash -c`, force push, `chmod 777`), with shell wrappers unwrapped (`sudo`, `env`, `xargs`, `find -exec`); a piped script is « unreadable » and asks;
   the agent cannot raise its own level (writes to its config always ask); keys are masked in what the model sees; a copy of the 20 last replaced files per folder. The page says plainly: **approvals are not a sandbox**; shell, skill scripts and MCP servers run with the user's rights. Telegram approvals expire after 8 minutes.
2. **Lutin.** Two switches per conversation (automatic writes, automatic commands), a dry run, a copy of the old version before every edit, « no approval » commands checked by a program without a shell (`safe_commands`), web addresses pinned and redirects checked (`net_guard`),
   automatic approval suspended after web content or an MCP result has been read, every MCP write asks at every call, a log of actions, rights per route declared and tested. No levels, no persistent rules except the list `commandes_sans_accord`, no « always allow for this command ».
3. **Improve.** A rules engine with the same precedence; the three answers on the approval card (the new interface has only approve and refuse); a hardline list that nothing overrides; the approval card showing the unwrapped command; named presets instead of two switches (for example *careful*, *workspace*, *autonomous*).
4. **Take.** Deny > ask > allow; project rules limited to ask and deny; « this chat » and « always » answers; never saving « always » for dangerous commands; the agent cannot change its own permissions; masking of keys in tool results.
5. **Skip.** Level 5 « full trust » as a one-flag switch (`--no-approval`); scheduled tasks running at the highest level (Lutin's read-only scheduled tasks are the right default); approvals sent through a third-party chat network as the main path.
6. **Implications and risks.** Persistent « always » rules are the classic way a user ends up with `bash *` allowed: store the rule as a command shape, show it, and let the user list and delete it. Rules written in the workspace by the model must never weaken a rule: only the user's own store may allow.
   The existing `safe_commands` validator already solves a part of the unwrapping problem; reuse it rather than writing a second parser.

## 5. MCP integration

1. **Atomic Agent.** Servers listed in `mcp.servers[]` (stdio, streamable HTTP, SSE), names `mcp.<server>.<tool>`, trust `approval_gated` by default, a tool with `readOnlyHint` skips the prompt; resources and prompts as tools; sampling routed to the local server;
   fixed timeouts (15 s connect, 60 s call), responses clipped to 8 000 characters; no OAuth; configuration read at startup only; live control only in the terminal panel.
2. **Lutin.** A hand-written JSON-RPC client (no dependency): stdio and HTTP; **nothing is offered to the model until the user authorises it tool by tool**; read-only by default; every write asks at every call and is logged;
   results are treated like web content (never obeyed, auto-approval suspended); only the configurator adds a connector (it launches a program); the process starts at the first call and stops when idle; a catalogue of known connectors.
3. **Improve.** Streamable HTTP and SSE if the servers people use need them; `readOnlyHint` as a *suggestion* shown at authorisation time, never a bypass; resources and prompts of a server in the interface; OAuth for remote servers.
4. **Take.** The naming `mcp.<server>.<tool>` into the same registry as built-in tools (one namespace, one table); clipping and timeouts as visible settings.
5. **Skip.** Trusting a server-declared `readOnlyHint` to skip a prompt; letting MCP servers inherit the whole environment (Atomic's stdio servers see the keys of its `.env`): Lutin should pass a minimal environment; MCP sampling enabled for every server at once.
6. **Implications and risks.** A server is a program run with the user's rights: the deny-by-default stance of Lutin is the right one and is a differentiator to state in the documentation.

## 6. Skills

1. **Atomic Agent.** A folder with `SKILL.md` (frontmatter: name, description, version, required tools, allowed scripts, platforms, dangerous hint), global and per-project folders (project shadows global), the stub in the prompt and the body loaded on demand,
   scripts run by a gated tool, installation from ClawHub or from GitHub taps with a security scan, 18 starter skills, import of skills and plugins from Claude Code, Codex, Cursor, Hermes, OpenClaw.
2. **Lutin.** The same open format (`agentskills.io`), listing name and description from the working folder (`.claude/skills`), model opens the file when needed; GitHub search and install with an analysis of the text and the scripts (pipe to shell, hidden instructions, secret reads), a licence check, a weight estimate for a small model,
   nothing installed without a click and nothing run at install, only what Lutin installed can be updated or removed (`.lutin-skill.json`).
3. **Improve.** A per-skill allow-list of scripts and a gated « run script » tool; the platform filter; a small set of starter skills in French and English; a global folder next to the project folder.
4. **Take.** The frontmatter fields `requires_tools`, `requires_scripts`, `platforms`; import from other agents' folders (`lutin import claude-code` as an onboarding aid).
5. **Skip.** A commercial registry as a default source; auto-reseeding starter skills at every boot (overwrites the user's edits).
6. **Implications and risks.** A skill is text the model obeys: Lutin's install-time analysis is already stricter than Atomic's scanner and should stay a selling point. Importing third-party plugins that carry **hooks that can block or alter tool calls** (Atomic does it) is a larger attack surface: do not take hooks.

## 7. Task scheduling

1. **Atomic Agent.** `tasks.sqlite`; schedules: none, at, interval, cron with time zone; retries with exponential backoff (3 attempts), stale recovery, a status per task (pending, running, completed, failed, blocked, cancelled); webhooks that render a template into a task; Telegram notification;
   a scheduler that runs only while a process is open (no catch-up, interval drifts); overnight runs with budget and hour caps; a known bug in its own `--at`.
2. **Lutin.** Scheduled tasks (weekly days or once), **read-only by design** (reads and searches are real, everything else is simulated as in a dry run), one conversation per task that grows with each run, ten last runs kept, nothing fails silently,
   a notification channel per task (Gotify, ntfy, Telegram, webhook), a task starts only if no answer is running; long missions (hours) with a forced progress sheet, autonomous or dry-run, bounded.
3. **Improve.** Interval and cron triggers (a small parser, no dependency); a webhook trigger bound to a task; retries with a bounded backoff; a « missed while Lutin was off » line in the run list; state names shared with section 1.
4. **Take.** The trigger types, the retry policy, the explicit terminal statuses (blocked vs failed), the budget caps for missions (time already; add a cap on steps and on remote machine use).
5. **Skip.** Running scheduled work with full trust; an agent tool that lets the model schedule arbitrary recurring tasks unreviewed (it must go through an approval and be visible in the list).
6. **Implications and risks.** A background scheduler only works while Lutin runs: say so, and offer the tray or service start-up that already exists. Never raise the rights of a scheduled run to make a task « work »: a task that needs a write must be a mission, started by a person.

## 8. Multi-agent orchestration (Fusion)

1. **Atomic Agent.** A third run mode next to local and cloud. An orchestrator plans, writes a brief per part and reviews; several short-lived workers build the parts in parallel and write straight to disk (isolation by git worktree is a config key);
   the orchestrator has one tool (`fusion.delegate`), never edits files itself, can verify with syntax checks, test commands or a headless browser and send weak parts back; workers cannot delegate nor write memory; approving a Fusion run does not allow its workers the dangerous commands;
   checkpoints in `fusion-runs/` with resume; a cost cap per turn (`turnBudgetUsd`). Seats can be swapped: cloud planner with local workers (suits jobs with many small parts) or the reverse. Local workers share one GPU, so on a small card « a run can stretch into hours ». The page admits that long review rounds can cost more than a single cloud model.
   No numbers are published for Fusion itself.
2. **Lutin.** **No sub-agent and no delegation** (nothing in the code). What exists is the ground it would stand on: pairing of machines with a relay that lets one machine lead a conversation run by another (`machines.py`), a model router by objective signals (images, code, reasoning, speed),
   long missions, a progress sheet, approvals, backups, a loop detector, and the one-turn-at-a-time limit per graphics card.
3. **Improve.** A « team » mode built on what Lutin has: a planner turn that writes a plan and briefs, workers as missions on other paired machines or on the same one in sequence, each in its own working copy (git worktree when the folder is a repository), an acceptance step that runs the checks the project already has,
   then a review turn. Budgets in hours, steps and machines.
4. **Take.** The roles and the rule that the orchestrator never edits; acceptance by checks before merging; workers that cannot delegate or write memory; isolation by worktree; a resume point per run.
5. **Skip.** Cloud planning as the default seat (the planner reads the user's request and files: for a tool that promises local, the default must be all local, the cloud seat opt-in and shown as such); a worker count in the dozens on one card.
6. **Implications and risks.** ADR 0003 froze new features during the migration: this is a **new feature** and needs the maintainer's decision (plan step 6 already lists differentiators). It needs sections 1, 3 and 4 first (registry, batches, rules) and an evaluation harness (section 9) to prove it beats a single agent:
   on one graphics card, parallel workers are slower than one agent, so the benefit only appears with several machines or a mix of local and remote models. This is where Lutin can be genuinely different: **a household or office of paired machines working as one local team**, which Atomic Agent does not have.

## 9. Performance with llama.cpp

1. **Atomic Agent.** A managed `llama-server` (their own fork with a compressed KV cache, backends Metal, Vulkan, CUDA); `cache_prompt` and slot reuse across steps, a byte-stable prefix, one slot pinned per session; context auto-sized to free GPU memory (capped at 131 072, at most 4 slots), partial offload retried with half the window; a second small server for embeddings, skipped under 7 GiB of RAM;
   an API key passed in the child's environment and not on the command line; **GBNF grammar** sent in each request; sampling defaults (temperature 0.2, top-p 0.95, top-k 40) as environment variables. Published numbers are the self-reported GAIA run (217 s against 351 s per task) and a memory-saving table (fp16 about 24 GB against Q4 about 6.7 GB, model unnamed). No flag list is published.
   Their own warning: the same weights on a runtime without grammar lose the guarantee.
2. **Lutin.** A managed `llama-server` with `--jinja`, `-m`, `-c`, an API key, machine-adapted flags (`reglages_machine`: variant, size, profile), vision projector, `--n-cpu-moe` for mixture-of-experts, and **router mode** (`--models-preset`, `--models-max`) that loads and unloads models; downloads and updates of the engine;
   catalogue with compatibility verdicts, a fit estimate, an engine bench and a metrics ranking. **No grammar, no slot or prompt-cache control** (my search of `llamacpp_engine.py` found none of `grammar`, `cache_prompt`, `id_slot`, `flash`); the engine layer is common to Ollama and OpenAI-compatible servers.
3. **Improve.** (a) Measure first: tokens re-read per step on a scripted conversation, before and after a prefix audit; (b) send `cache_prompt` and keep one slot per conversation on llama.cpp; (c) an *engine capabilities* record (grammar, slots, cache, embeddings) so that the loop adapts instead of assuming Ollama;
   (d) grammar-constrained tool calls as an experiment for small models on llama.cpp, with the existing bench as judge; (e) a second small server for embeddings only when the machine has the memory.
4. **Take.** Prefix stability, slot reuse, the capabilities record, the memory gate for the embedding model, the API key kept out of the command line, partial-offload retry.
5. **Skip.** A private fork of llama.cpp (a permanent maintenance burden and a supply-chain question for a project that ships to the public); forcing one engine; claiming speed-ups before measuring them.
6. **Implications and risks.** Grammar guarantees the **shape**, not the meaning: wrong tool, wrong argument, repeated calls remain (Atomic says so itself); a grammar must follow the dynamic list of tools (MCP, disabled tools); with `--jinja` the template already converts calls, so the gain is for small models that fail the template, which only the bench can show.
   ADR 0007 (names seen by models) interacts: renaming tools changes what the model must produce.

## 10. Desktop and terminal architecture

1. **Atomic Agent.** One TypeScript runtime (`createAgentRuntime`) behind four frontends: an Ink terminal UI, a one-shot `run`, an HTTP `serve` that speaks the OpenAI chat API, and a Tauri desktop app that talks to a sidecar through NDJSON on stdin/stdout; Telegram and Discord as channels; the state in `~/.atomic-agent` shared by all of them;
   signed packages, an install script checking SHA-256, a 140 MB binary; **telemetry on by default** (usage and crash reports, switches provided), traces on by default.
2. **Lutin.** A zero-dependency Python server; the interface is a local web page (the old one, and the new one under `/app/`); a tray icon on Windows; `lutin chat` in a terminal with the same tools, approvals and history through the HTTP client; PIN pairing for phones; Docker image; a Windows installer;
   notifications and a Telegram add-on; no telemetry, an offline mode that is checked by a test.
3. **Improve.** Make the runtime the single owner of a turn (`run_turn`) and have the web server, the terminal, the tray, the scheduler and the add-ons call it (plan step 5); an optional OpenAI-compatible endpoint so that other tools can use Lutin's models and rules (off by default, behind a token);
   `/steer` and `/queue` in the terminal (send while it works); an NDJSON recorder of turns for replay in tests (see below).
4. **Take.** One runtime, many frontends; replayable traces (`trace replay` that fails when the prompt drifts) as a regression test for the loop; checksum-verified install.
5. **Skip.** A Tauri or Electron shell (the web page plus tray already works on every system and keeps the package light); a Node runtime; default telemetry; Discord and Telegram as primary control channels.
6. **Implications and risks.** Traces contain prompts: opt-in, redacted, and stored next to the conversation they belong to. An OpenAI-compatible endpoint turns Lutin into a server for other programs: it must go through the same rights and approvals as the page, or it is a bypass.

## 11. What to keep as Lutin's identity

What Atomic Agent does not do and Lutin already does, and that should be stated as strengths: zero runtime dependency; no telemetry and a tested offline mode; web requests pinned and redirects checked; commands without approval checked by a program, not by a shell;
a copy of every file before it is changed; automatic approval suspended after web content; deny-by-default MCP; install-time analysis of skills; a progress sheet for long work; PIN-paired phones and machines; a catalogue of models with compatibility verdicts for the machine; bilingual interface; Ollama, llama.cpp and OpenAI-compatible engines.
Atomic Agent itself says what it is not: its approvals are not a sandbox, its traces are plaintext, its keys can reach the skills. Lutin can say the opposite, truthfully.

## 12. Order of work that follows

1. A deterministic task suite and a recorder/replayer of turns (the evidence for every change below; without it, the grammar and the team mode cannot be judged).
2. Prefix audit and measure of reused tokens on llama.cpp and Ollama; engine capabilities record.
3. Tool table with metadata and its conformance test; read-only batches.
4. Approval rules engine (deny > ask > allow, « this chat », « always »), hardline list, presets; matching approval card in the new interface.
5. SQLite store with FTS5, created by the data migration of step 3; versioned profile facts.
6. Scheduler triggers (interval, cron, webhook), retries, states.
7. Grammar-constrained tool calls on llama.cpp, opt-in, judged by the suite.
8. Team mode on paired machines — **only with the maintainer's decision** (feature freeze, ADR 0003).
