## What this change does / Ce que change cette modification

## How it is verified / Comment c'est vérifié

- [ ] `python tests/lancer_tests.py` passes / passe
- [ ] `python -m ruff check src tests tools` passes / passe
- [ ] if the interface changes: `npm run check`, `npm test` and `npm run build` pass in `frontend/` / si l'interface change : ces trois commandes passent
- [ ] a test covers the change (or: why there is none) / un test couvre le changement (ou : pourquoi il n'y en a pas)
- [ ] no personal data (conversation, memory, path, address) in the change / aucune donnée personnelle dans la modification
- [ ] if the catalogue changes: `python tools/verifier_catalogue.py` passes and the « tools » capability is verified / si le catalogue change : le script passe et la capacité « outils » est vérifiée
- [ ] a new displayed text has its translation (`_t(...)` in Python, a key of `frontend/src/lib/messages.ts` in the interface) and the docs exist in both languages / un nouveau texte affiché a sa traduction et les docs existent dans les deux langues
