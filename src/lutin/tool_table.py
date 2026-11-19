"""The tool table (plan step 5, item 3): for each tool the models can call, what it does to the world, in ONE place.

Before this table the same knowledge was written in several lists (the tools of the research mode, what a dry run simulates, what asks for an approval), which
could drift apart without any test noticing. The names are the ones the models see and are not translated (ADR 0007).

`effect` says what a call can change:
- `read`      nothing: it reads the working folder, the memory or the web;
- `notes`     Lutin's own notes about the conversation (memory, progress sheet, task list): never a file of the person;
- `files`     files of the working folder;
- `command`   anything a command can do;
- `external`  another program or service (image or voice generation, a module to install, a browser);
- `control`   the course of a mission (it ends or blocks it).
`asks` says that the tool stops for an approval before it acts (the answer can be automatic: see the agent and lutin.approval_rules).
`network` says that the call leaves the machine or reaches a local service over HTTP.

`tests/test_tool_table.py` checks that every tool offered to the models has an entry, that no entry names a tool that does not exist, and that the lists
derived from the table are the ones the code used before."""
from collections import namedtuple

Tool = namedtuple("Tool", "effect asks network")

READ, NOTES, FILES, COMMAND, EXTERNAL, CONTROL = "read", "notes", "files", "command", "external", "control"
EFFECTS = (READ, NOTES, FILES, COMMAND, EXTERNAL, CONTROL)

TABLE = {
    "lister": Tool(READ, False, False),
    "lire": Tool(READ, False, False),
    "lire_plusieurs": Tool(READ, False, False),
    "chercher": Tool(READ, False, False),
    "trouver": Tool(READ, False, False),
    "symboles": Tool(READ, False, False),
    "calculer": Tool(READ, False, False),
    "rappeler": Tool(READ, False, False),
    "web_chercher": Tool(READ, False, True),
    "web_lire": Tool(READ, False, True),
    "voix_liste": Tool(READ, False, True),
    "voix_transcrire": Tool(READ, False, True),
    "comfy_modeles": Tool(READ, False, True),
    "memoriser": Tool(NOTES, False, False),
    "suivi": Tool(NOTES, False, False),
    "taches": Tool(NOTES, False, False),
    "ecrire": Tool(FILES, True, False),
    "modifier": Tool(FILES, True, False),
    "modifier_plusieurs": Tool(FILES, True, False),
    "creer_document": Tool(FILES, True, False),
    "executer": Tool(COMMAND, True, False),
    "apercu_page": Tool(EXTERNAL, True, True),
    "voix_parler": Tool(EXTERNAL, True, True),
    "voix_cloner": Tool(EXTERNAL, True, True),
    "comfy_generer": Tool(EXTERNAL, True, True),
    "installer_module": Tool(EXTERNAL, True, True),
    "etat_outil": Tool(READ, False, True),
    "mission_terminer": Tool(CONTROL, False, False),
    "mission_bloquee": Tool(CONTROL, False, False),
}


# Tools that another one covers, left out when the context window is small (ADR 0018): on 8,192 tokens the schemas took about half of the request.
# `lire` reads one file at a time, `modifier` makes one replacement at a time, `chercher` finds a function, `web_lire` reads a page.
SPARE_ON_SMALL_WINDOW = frozenset({"lire_plusieurs", "modifier_plusieurs", "symboles", "apercu_page"})
SMALL_WINDOW = 8192          # tokens: at this size or below, the spare tools are left out

# On 4,096 tokens the fourteen tools left still weighed 2,782 tokens, 68 % of the window: the history only had its floor and the request overflowed.
# At this size or below only a core is sent (maintainer's decision, 2026-11-19): lire, ecrire, modifier, chercher, executer, rappeler, and memoriser,
# which nothing replaces. `executer` lists a folder or finds a file (dir or ls, without approval) and computes (with approval); `ecrire` writes a
# Markdown, HTML or CSV document. Nothing replaces the task list and the web: they are lost on such a window, and the documentation says so.
SPARE_ON_TINY_WINDOW = SPARE_ON_SMALL_WINDOW | {"lister", "trouver", "calculer", "creer_document", "taches", "web_chercher", "web_lire"}
LOST_ON_TINY_WINDOW = frozenset({"taches", "web_chercher", "web_lire"})          # left out without a cover (accepted by the maintainer)
TINY_WINDOW = 4096           # tokens


def spare_tools(num_ctx):
    """The tools left out for a context window of `num_ctx` tokens (0 or unknown: none)."""
    try:
        num_ctx = int(num_ctx or 0)
    except (TypeError, ValueError):
        return frozenset()
    if not num_ctx:
        return frozenset()
    if num_ctx <= TINY_WINDOW:
        return SPARE_ON_TINY_WINDOW
    return SPARE_ON_SMALL_WINDOW if num_ctx <= SMALL_WINDOW else frozenset()


def names(*effects):
    """The tools whose effect is one of `effects`."""
    return {name for name, tool in TABLE.items() if tool.effect in effects}


def research_tools():
    """What the research mode keeps: reading, and Lutin's own notes. Nothing that touches a file of the person, runs a command or drives another program."""
    return names(READ, NOTES) - {"etat_outil"}          # the state of the image tool belongs to the optional image extension (modes.IMAGE_TOOLS)


def batchable():
    """The tools whose calls can run together inside one step: they read the working folder or compute, touch nothing shared and ask nothing.
    Not the web (a page read changes how the rest of the turn is trusted), not the recall (it talks to the engine, which answers one request at a time)."""
    return {name for name, tool in TABLE.items() if tool.effect == READ and not tool.network} - {"rappeler"}


def asking():
    return {name for name, tool in TABLE.items() if tool.asks}
