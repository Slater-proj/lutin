# Contribuer

## Lancer les tests

```bash
python tests/lancer_tests.py            # un processus par fichier (le moteur garde des réglages globaux)
python tests/lancer_tests.py securite   # seulement les fichiers dont le nom contient « securite »
python -m pip install ruff && python -m ruff check src tests tools
```

Pas de dépendance à installer pour faire tourner Lutin ou ses tests : bibliothèque standard seulement. Garde-le ainsi.

## Règles

- Un changement = un test (ou une phrase qui explique pourquoi il n'y en a pas).
- Le **catalogue de modèles** (`src/lutin/data/modeles.json`) est une donnée : une phrase de description courte (140 caractères), la capacité « outils » vérifiée avec `ollama show`, la licence, des notes de 1 à 10 justifiées dans la description de la pull request. `python tools/verifier_catalogue.py` doit passer.
- Aucun accès réseau pendant les tests : utilise les faux Ollama des fichiers existants.
- Un test ne doit jamais exécuter de vraie commande système ni modifier l'environnement de l'utilisateur (voir `Parcours.setUp` dans `test_installation_cli.py`).
- Pas de télémétrie, jamais.
- Textes de l'interface en français pour l'instant ; l'anglais viendra avec un fichier de traduction.

## Données personnelles

Ne commite jamais de conversation, de fichier de mémoire personnel, de `config.json` ni de journal. `.gitignore` les exclut ; `gitleaks` tourne en CI.
