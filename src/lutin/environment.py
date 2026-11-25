"""English names for the environment variables of Lutin (plan step 3).

The code still reads the original (French) names. This module lets the English ones be used today: at the start of the process, an English name that is set
fills its original name when that one is not set. If both are set, the original wins: an installation that already works keeps working, whatever a new file
or a new habit adds beside it. Nothing is ever removed or renamed in the environment, so a program started by Lutin sees both."""
import os

# English name -> the name the code reads
ALIASES = {
    "LUTIN_ROOT": "LUTIN_RACINE", "LUTIN_DATA": "LUTIN_DONNEES", "LUTIN_MEMORY": "LUTIN_MEMOIRE", "LUTIN_LANGUAGE": "LUTIN_LANGUE", "LUTIN_LEVEL": "LUTIN_NIVEAU",
    "LUTIN_PUBLIC_URL": "LUTIN_URL_PUBLIQUE", "LUTIN_OFFLINE": "LUTIN_HORS_LIGNE", "LUTIN_BUDGET_GB": "LUTIN_BUDGET_GO", "LUTIN_ADMIN_ALL": "LUTIN_ADMIN_TOUS",
    "LUTIN_LISTEN": "LUTIN_ECOUTE", "LUTIN_NO_BROWSER": "LUTIN_SANS_NAVIGATEUR", "LUTIN_BROWSER": "LUTIN_NAVIGATEUR", "LUTIN_MODEL": "LUTIN_MODELE",
    "LUTIN_CATALOG": "LUTIN_CATALOGUE", "LUTIN_SEARCH_URL": "LUTIN_RECHERCHE_URL", "LUTIN_TOOL_URL": "LUTIN_OUTIL_URL", "LUTIN_NO_GUARD": "LUTIN_SANS_GARDE",
    "LUTIN_NO_STARTUP": "LUTIN_SANS_DEMARRAGE", "LUTIN_TRACE_PROCESS": "LUTIN_TRACE_PROCESSUS", "LUTIN_PROPOSALS": "LUTIN_PROPOSITIONS",
}


def apply(environ=None):
    """Fills the original names from the English ones (see the module). Returns the names that were filled."""
    environ = os.environ if environ is None else environ
    filled = []
    for english, original in ALIASES.items():
        if english in environ and original not in environ:
            environ[original] = environ[english]
            filled.append(original)
    return filled
