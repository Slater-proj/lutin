**English** · [Français](MIGRATION.fr.md)

# Taking over another assistant

You already use an assistant built on the same engine (the Ollama assistant Lutin comes from), and you want its data in Lutin without losing anything. Lutin reads the old assistant's folders **in place** (nothing to export first) or a `.zip` archive, and lets you choose what to take.

```bash
lutin reprendre <old assistant folder>                  # shows what it found, asks what to take
lutin reprendre <folder> --conversations --skills       # or choose with options (--memoire, --reglages, --tout)
lutin reprendre <backup.zip>                            # a Lutin backup (lutin sauvegarde), or a zip of donnees/ memoire/ skills/
```

In the page: **Memory > Take over another assistant…**.

| Category | What is taken | Where it goes |
|---|---|---|
| Conversations | every `donnees/conversations/*.json` (dates and order kept; the `.bak` copies and unreadable files are skipped) | Lutin's conversations. Links to old file backups are dropped; a conversation takes the active workspace folder on first use |
| Memory | `CONTEXTE.md`, `MEMOIRE.md` | Lutin's memory. Yours is **never overwritten**: if it differs from Lutin's starting text, the old one is put next to it as `CONTEXTE.importe-<date>.md` |
| Skills | the `*.md` of `skills/` (next to the old assistant's folder, or `--dossier-skills <folder>`) | `skills/` of the **active workspace folder** |
| Settings | context window, temperature, thinking, tool steps, safeguards… | Lutin's settings, merged with yours |

Safety:

- **Nothing is overwritten** unless you add `--ecraser` (or tick the box in the page): a conversation or a skill that already exists is left alone and counted.
- Before any write, Lutin's current state is kept in `donnees/import/avant-import-<date>.zip`.
- The **model** and the **automatic approvals** (files, commands) are **never** taken over: the model may not be installed here, and approvals are for you to give again.
- A `.zip` that would write outside its folders is refused; only conversations, settings, memory and skills are read from it.
- Importing is only possible from this machine (like adding a workspace folder).

For a Claude Code repository (`CLAUDE.md`, `.claude/`), see [CLAUDE-PROJECTS.md](CLAUDE-PROJECTS.md).
