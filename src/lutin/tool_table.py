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


def names(*effects):
    """The tools whose effect is one of `effects`."""
    return {name for name, tool in TABLE.items() if tool.effect in effects}


def research_tools():
    """What the research mode keeps: reading, and Lutin's own notes. Nothing that touches a file of the person, runs a command or drives another program."""
    return names(READ, NOTES) - {"etat_outil"}          # the state of the image tool belongs to the optional image extension (modes.IMAGE_TOOLS)


def asking():
    return {name for name, tool in TABLE.items() if tool.asks}
