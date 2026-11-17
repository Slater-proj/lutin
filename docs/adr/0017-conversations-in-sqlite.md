# ADR 0017 — Conversations in SQLite, settings in JSON

Status: accepted on 2026-11-17, for 1.0 (plan step 3, item 6, and step 6, item 3): the maintainer asked for « the most efficient and fluid,
adapted to our needs », a mix of JSON and a database being acceptable, and left the choice to this record. Implemented: `lutin/store.py`,
`tests/test_store.py`. Still to do: `lutin export --conversations`, the warning for a data folder on a network share (decision 7) and the
handling of a database that cannot be opened (decision 8).

## Context

Read in `lutin/storage.py` on `98ebd28`:

- **One JSON file per conversation** (`donnees/conversations/<id>.json`), rewritten whole at each write, with a `.bak` copy of the previous version
  made by copying the file first; its options in a second file (`donnees/options/<id>.json`).
- **The list** reads every file whose date or size changed since the last reading, and keeps an accelerator (`index-conversations.json`); with
  thousands of conversations the first listing reads thousands of files.
- **No full-text search** of the conversations: recall and search read files or the embeddings index.
- **Concurrent reads on Windows**: opening a file while `os.replace` swaps it raises `PermissionError` (fixed by a bounded retry in `7f2c97e`, but
  every new reader has to know it).
- **Small, human-edited files** (settings, configuration, MCP, notifications) are read often and written rarely; the notes the model reads
  (`MEMOIRE.md`, `CONTEXTE.md`) and the skills are Markdown files the person edits by hand.

## Decision

1. **A SQLite database, `donnees/lutin.db`, is the store of the conversations**: their summary fields, their messages (one row each, in order),
   their options, and a full-text index (FTS5, `unicode61 remove_diacritics 2`) of titles and message texts. Standard library only (`sqlite3`):
   still no dependency. WAL journal, one transaction per write: a reader never sees half a conversation, on any system.
2. **JSON and Markdown stay for what is small and edited by hand**: settings (`reglages.json`), configuration, MCP servers, notification channels,
   machines and node, missions and scheduled tasks, the two notes and the skills. They are indexed by FTS5 when recall needs them, never moved.
3. **One door**: `lutin.store` (English module) offers what `storage.py` offers today for conversations (read, write, list, delete, rename, pin,
   options) with the same dictionaries, so the callers do not change; `storage.py` keeps its names as thin wrappers until step 3 renames them.
4. **The list and the search are queries**, not file scans: the list reads one table; search (`GET /api/v1/conversations?q=`) uses FTS5, ranked.
5. **The migration is one step, versioned, with a backup first** (`PRAGMA user_version`, a `migrations` table): at the first start of 1.0, the
   `conversations/` and `options/` folders are zipped into `donnees/sauvegardes/`, then imported in one transaction per conversation; a file that
   cannot be read is left where it is and reported, never deleted. The imported files are moved to `donnees/archives/avant-1.0/`, not deleted.
   Nothing is imported twice: a file is moved once imported, and the same conversation dropped again writes nothing. A file put in that folder
   later is taken as it is: it comes from a restore, from `lutin migrate` (which leaves out what is already here) or from a person putting a
   conversation back.
6. **The way back** is the backup: `lutin restore` puts the 0.x files back, and `lutin export --conversations` writes every conversation of the
   database as the 0.x JSON files.
7. **Local disk only**: SQLite's locking is unreliable on a network share. When `donnees/` is on one, Lutin says so at start and in `lutin doctor`
   and keeps working, as the plan says (step 6: dead data may move to a network disk, the database never).
8. **A database that cannot be opened** (damaged, disk full) is never replaced in silence: it is copied aside, Lutin says what happened and starts
   with an empty one; `lutin doctor` points to the copy and to the backups.

## Not chosen

- **SQLite for everything, settings included**: settings are a few kilobytes, read at once and edited by hand or by `lutin` commands; a table
  would hide them from the person and gain nothing.
- **SQLite as an index only, JSON kept as the source**: two copies of every conversation to keep in step, the Windows read race and the slow first
  listing stay; it solves search only.
- **Another engine (DuckDB, LMDB…)**: a dependency, against the rule of the project.
- **One file per message**: thousands of files per conversation, slower than both.

## Consequences

- Writing a turn becomes a transaction that replaces the messages of one conversation (a conversation of a few hundred messages: milliseconds).
  Appending only the new messages is an optimisation left for later, measured first.
- Tests read and write conversations through the same functions: they keep working on a temporary `lutin.db`; new tests cover the migration on
  data written by 0.50 (a fixture of 0.x files), the idempotence, the backup and the way back.
- The copy of a conversation into the workspace folder (`conversations-lutin/`, Markdown) is unchanged.

## Way back

Before release: revert the commits. After: `lutin restore` with the backup made by the migration, or `lutin export --conversations`.
