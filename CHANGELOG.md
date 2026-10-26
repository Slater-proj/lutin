# Changelog

The following versions are published automatically (generated notes on the Releases page); this file keeps the first versions and the main changes. / Les versions suivantes sont publiées automatiquement (notes générées sur la page des Releases) ; ce fichier garde les premières versions et les changements principaux.

## 0.2.0

- **English and French**: the whole application (page, messages, terminal, memory templates) and the repository docs. `lutin langue [fr|en|auto]`, a language question at the start of the guided installation, a selector in the page settings, `LUTIN_LANGUE`. Tests fail if a text has no translation.
- **Docker: one complete image** (Lutin + Ollama in the same container, `:latest`) and a slim one (`:slim`, Lutin alone). New volume `/models`, `docker run` in one command.
- **Claude projects**: `lutin importer <folder>` (and Memory > Claude project in the page) takes over a repository with `CLAUDE.md` and `.claude/` (skills, commands, agents, rules), working in it or in a copy. See docs/CLAUDE-PROJECTS.md.
- **New version notice**: a banner in the page (once a day at most, silent offline, can be skipped); nothing is installed without you.
- Fix: `install.ps1` no longer fails with `irm … | iex` (ASCII file, no BOM) (0.1.1).

**Français.** **Français et anglais** : toute l'application (page, messages, terminal, mémoire de départ) et les docs du dépôt. `lutin langue [fr|en|auto]`, une question de langue au début de l'installation guidée, un sélecteur dans les réglages de la page, `LUTIN_LANGUE`. Les tests échouent si un texte n'a pas de traduction. **Projets Claude** : `lutin importer <dossier>` (et Mémoire > Projet Claude dans la page) reprend un dépôt avec `CLAUDE.md` et `.claude/` (skills, commandes, agents, règles), dedans ou dans une copie. **Nouvelle version** : un bandeau dans la page (une fois par jour au plus, silencieux hors ligne, ignorable). **Docker : une image complète** (Lutin + Ollama dans le même conteneur, `:latest`) et une légère (`:slim`, Lutin seul). Nouveau volume `/models`, `docker run` en une commande. Correction : `install.ps1` ne plante plus avec `irm … | iex` (fichier ASCII, sans BOM) (0.1.1).

## 0.1.0 (first release / première publication)

Première version : extraite de l'assistant d'un projet personnel, rendue indépendante.

- Détection de la machine (NVIDIA, AMD, Intel, Apple ; RAM ; disques) et sélection de modèles par rôle selon la mémoire disponible.
- Catalogue de modèles en données, validé, avec une phrase de description par modèle.
- Trois niveaux d'accès : cette machine, réseau local (code PIN), proxy (identité du proxy de confiance).
- Installation guidée (`lutin setup`), interactive ou automatique (`--oui`).
- Ligne de commande : `lutin`, `chat`, `modeles`, `pin`, `appareils`, `securite`, `doctor`.
- Vérification des mises à jour de modèles au lancement (au plus une fois par jour, jamais bloquante).
- Scripts d'installation Windows (PowerShell) et Linux / macOS (shell).
- Installation idempotente : relancer le script ou `lutin setup` sur une machine déjà installée ne change rien (ou met à jour si une version plus récente existe) ; les modèles déjà téléchargés ne sont jamais retéléchargés.
- `lutin update` ; boutons « Chercher les mises à jour » et « Chercher de nouveaux modèles » dans l'onglet Modèles ; relance automatique du serveur après une erreur (`lutin serve`).
- Linux et macOS : lectures sans accord (`ls`, `cat`, `pwd`, `which`), refus des chemins absolus, arrêt des commandes avec leurs sous-processus.
- **Mode hors ligne strict** : aucune connexion vers Internet, vérifiée sur les connexions réelles.
- **Dossiers de travail multiples** : un dossier actif à la fois, chaque conversation garde le sien ; ajout réservé à cette machine.
- **Banc d'essai** des modèles sur la machine (vitesse, appel d'outils, code, français, consignes), exportable.
- **Journal des actions** (fichiers modifiés, commandes lancées, accord, personne), **sauvegarde et restauration** des données en un `.zip`.
- **Image Docker** (Lutin + Ollama, GPU NVIDIA en option) et `docker-compose.yml`.
- **Publications automatiques** : fusion dans `main` = version + étiquette + Release + image ; autre branche = candidate sans étiquette.
- Logo, bannière, captures d'écran ; icônes du téléphone aux couleurs de Lutin ; liens directs `/#modeles`, `/#conv=…`.
- Page : pastille verte « réponse terminée, pas lue », réponse qui reste dans sa conversation quand on en ouvre une autre, resynchronisation automatique, liste de tâches qui se ferme quand tout est fait.
