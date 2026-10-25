## Ce que change cette modification

## Comment c'est vérifié

- [ ] `python tests/lancer_tests.py` passe
- [ ] `python -m ruff check src tests tools` passe
- [ ] un test couvre le changement (ou : pourquoi il n'y en a pas)
- [ ] aucune donnée personnelle (conversation, mémoire, chemin, adresse) dans la modification
- [ ] si le catalogue change : `python tools/verifier_catalogue.py` passe, la capacité « outils » est vérifiée
