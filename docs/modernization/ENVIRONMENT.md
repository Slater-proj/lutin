# Environment variables: English names

Plan step 3. The code still reads the original names (mostly French). `lutin/environment.py` lets the English ones be used today: at the start of the process, an English name that is set fills its original name when that one is not set. If both are set, **the original wins**, so an installation that already works keeps working. Nothing is removed from the environment: a program started by Lutin sees both.

| English name | Original name |
|---|---|
| `LUTIN_ROOT` | `LUTIN_RACINE` |
| `LUTIN_DATA` | `LUTIN_DONNEES` |
| `LUTIN_MEMORY` | `LUTIN_MEMOIRE` |
| `LUTIN_LANGUAGE` | `LUTIN_LANGUE` |
| `LUTIN_LEVEL` | `LUTIN_NIVEAU` |
| `LUTIN_PUBLIC_URL` | `LUTIN_URL_PUBLIQUE` |
| `LUTIN_OFFLINE` | `LUTIN_HORS_LIGNE` |
| `LUTIN_BUDGET_GB` | `LUTIN_BUDGET_GO` |
| `LUTIN_ADMIN_ALL` | `LUTIN_ADMIN_TOUS` |
| `LUTIN_LISTEN` | `LUTIN_ECOUTE` |
| `LUTIN_NO_BROWSER` | `LUTIN_SANS_NAVIGATEUR` |
| `LUTIN_BROWSER` | `LUTIN_NAVIGATEUR` |
| `LUTIN_MODEL` | `LUTIN_MODELE` |
| `LUTIN_CATALOG` | `LUTIN_CATALOGUE` |
| `LUTIN_SEARCH_URL` | `LUTIN_RECHERCHE_URL` |
| `LUTIN_TOOL_URL` | `LUTIN_OUTIL_URL` |
| `LUTIN_NO_GUARD` | `LUTIN_SANS_GARDE` |
| `LUTIN_NO_STARTUP` | `LUTIN_SANS_DEMARRAGE` |
| `LUTIN_TRACE_PROCESS` | `LUTIN_TRACE_PROCESSUS` |
| `LUTIN_PROPOSALS` | `LUTIN_PROPOSITIONS` |

The variables that already have an English name (`LUTIN_HOME`, `LUTIN_CONFIG`, `LUTIN_ENGINES`, `LUTIN_PORT`, `LUTIN_GPU`, `LUTIN_DOCKER`, `LUTIN_ADMINS`, `LUTIN_PROXY_IP`…) are not in the table.
Renaming the names the code reads is a later step; the aliases stay until then, and the original names keep working after it (ADR 0001: no break for an installation that exists).
Tested in `tests/test_environment.py`.
