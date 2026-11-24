[English](CONTRIBUTING.md) · **Français**

# Contribuer

## Lancer les tests

```bash
python tests/lancer_tests.py            # un processus par fichier (le moteur garde des réglages globaux)
python tools/captures.py                # régénère les captures du README (anglaises et françaises) après un changement d'interface
python tests/lancer_tests.py securite   # seulement les fichiers dont le nom contient « securite »
python -m pip install ruff && python -m ruff check src tests tools
cd frontend && npm ci --ignore-scripts && npm run check && npm test && npm run build   # l'interface
```

Pas de dépendance à installer pour faire tourner Lutin ou ses tests : bibliothèque standard seulement. Garde-le ainsi. Les tests de l'interface utilisent un vrai navigateur (Chrome, Chromium ou Edge) et sont ignorés s'il n'y en a pas.

## Organisation du code

`src/lutin/core.py` porte l'état partagé (réglages, chemins, constantes) et ré-exporte le reste. Le travail est dans des modules qui lisent cet état au dernier moment (`from . import core as _m`) : `server` et `api_v1` (HTTP ; chaque route v1 déclare son droit dans une seule table), `agent` et `turn_runner` (un tour, la boucle de l'agent, une seule entrée pour tous les lanceurs : ADR 0015), `tools`, `storage` et `store` (conversations dans SQLite, ADR 0017), `recall` (rappel et recherche dans les documents), `scheduled_tasks`, `mission`, `images`, `access`, `health`, `change_review`, `machines` (ordinateurs appairés). Une constante qu'un test remplace doit vivre dans `core`. L'interface est dans `frontend/` (Svelte 5, TypeScript, Vite ; voir [frontend/README.md](frontend/README.md)) ; `tools/construire_icones.py` refait les icônes à la main.

## Commits et publications

Chaque fusion dans `main` **publie une version** (voir [docs/PUBLISHING.fr.md](docs/PUBLISHING.fr.md)). Le numéro vient du titre des commits : écris des titres conventionnels (`feat: …` pour une nouveauté, `fix: …` pour une correction, `feat!: …` ou « BREAKING CHANGE » pour une rupture ; `docs:`, `chore:`, `ci:`, `test:`, `refactor:` pour le reste). Fusionne par **squash** avec un titre soigné : c'est lui qui apparaît dans les notes de version.

Jusqu'à la sortie de la 1.0, le travail et les pull requests visent la branche `modernization` ; `main` ne reçoit que la publication. `tools/release_channel.json` décide si une fusion publie une alpha, une beta, une candidate ou une version stable.

## Règles

- Un changement = un test (ou une phrase qui explique pourquoi il n'y en a pas).
- Le **catalogue de modèles** (`src/lutin/data/modeles.json`) est une donnée : une phrase de description courte (140 caractères), la capacité « outils » vérifiée avec `ollama show`, la licence, des notes de 1 à 10 justifiées dans la description de la pull request. `python tools/verifier_catalogue.py` doit passer.
- Aucun accès réseau pendant les tests : utilise les faux Ollama des fichiers existants.
- Un test ne doit jamais exécuter de vraie commande système ni modifier l'environnement de l'utilisateur (voir `Parcours.setUp` dans `test_installation_cli.py`).
- Pas de télémétrie, jamais.

## Langues (français et anglais)

Le code, ses commentaires et ses tests sont écrits en **anglais** ([ADR 0001](docs/adr/0001-english-and-clean-break-at-1.0.md)) ; un module encore en français garde sa langue jusqu'au renommage de ses noms. L'application et le dépôt sont bilingues, et le français reste la langue d'écriture des textes.

- En Python, tout texte montré à l'utilisateur passe par `_t("texte français")` (`from .i18n import t as _t`) ; sa traduction anglaise va dans `src/lutin/langues/messages.en.json`, avec le texte français exact comme clé.
- Dans l'interface, les textes sont dans `frontend/src/lib/messages.ts` (français et anglais, une clé chacun) et s'affichent avec `t("clé")` ; un test Vitest échoue si une clé manque dans une langue.
- Un texte construit par concaténation se traduit mal : écris-le comme un gabarit (`_t("{} libres sur {}").format(a, b)`).
- `tests/test_langue.py` échoue si un texte Python n'a pas de traduction, si une traduction perd une variable `{}`, ou si une traduction est restée sans objet. Sans traduction, le français s'affiche : jamais d'erreur, mais jamais de trou silencieux non plus.
- Documentation : `X.md` est en anglais, `X.fr.md` en français ; chacun commence par un lien vers l'autre. Mets les deux à jour dans la même pull request.

## Données personnelles

Ne commite jamais de conversation, de fichier de mémoire personnel, de `config.json` ni de journal. `.gitignore` les exclut ; `gitleaks` tourne en CI.
