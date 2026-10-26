**English** · [Français](CLAUDE-PROJECTS.fr.md)

# Using a Claude project (CLAUDE.md, `.claude/`)

If you already work with Claude Code, your git repository (homelab, project…) holds your context: `CLAUDE.md`, skills, commands, agents, rules. Lutin can use all of it, so you lose nothing when switching from one tool to the other.

## What Lutin understands

| In the folder | What Lutin does with it |
|---|---|
| `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` | put in the model's instructions at every conversation (7,000 characters at most), with the `@path` imports (one level, inside the project only) |
| `.claude/skills/<name>/SKILL.md` | listed with their `description`; the model reads the file when the subject comes up |
| `.claude/commands/**/*.md` | listed (`infra/dns.md` becomes `infra:dns`); name one and the model reads the file and applies it |
| `.claude/agents/*.md`, `.claude/rules/**/*.md` | listed, read on demand |
| all of the above | also searchable with the « rappeler » tool, like `docs/` and `skills/` |

Nothing is executed on its own: these files are **instructions and notes** for the model. Every modification of a file or command still asks for your approval and can be undone.

## Two ways to use it

| | Work in the repository | Work in a copy |
|---|---|---|
| Command | `lutin importer <folder> --ici` | `lutin importer <folder> --copie [--vers <folder>]` |
| Files | **the same** as Claude Code's: both tools see each other's changes | a copy (git history included, without `node_modules`, `.venv`…); the original is never touched |
| When | you want continuity, nothing to merge | you want to try, or keep the original safe; compare or merge with git afterwards |

Without `--ici` or `--copie`, the command asks (copy by default). In the page: **Memory > Claude project > Import a Claude project…**. The folder becomes a workspace folder and the active one.

Good to know:

- Adding a folder is only possible from this machine (`this machine only` level, or the command line), like every workspace folder.
- A folder with neither `CLAUDE.md` nor `.claude/` is refused (use `lutin travaux ajouter` for an ordinary folder).
- In Docker, mount the repository under `/travail` and declare it with `LUTIN_TRAVAUX` (see [DOCKER.md](DOCKER.md)).
- Lutin uses local models: very long `CLAUDE.md` files and many skills cost context. Keep them short, and let the model read the details on demand.
