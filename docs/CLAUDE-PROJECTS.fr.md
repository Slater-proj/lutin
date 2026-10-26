[English](CLAUDE-PROJECTS.md) · **Français**

# Utiliser un projet Claude (CLAUDE.md, `.claude/`)

Si tu travailles déjà avec Claude Code, ton dépôt git (homelab, projet…) contient ton contexte : `CLAUDE.md`, skills, commandes, agents, règles. Lutin peut tout utiliser, pour que rien ne se perde en passant d'un outil à l'autre.

## Ce que Lutin comprend

| Dans le dossier | Ce que Lutin en fait |
|---|---|
| `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` | mis dans les consignes du modèle à chaque conversation (7 000 caractères au plus), avec les imports `@chemin` (un niveau, dans le projet seulement) |
| `.claude/skills/<nom>/SKILL.md` | listés avec leur `description` ; le modèle lit le fichier quand le sujet se présente |
| `.claude/commands/**/*.md` | listées (`infra/dns.md` devient `infra:dns`) ; nommes-en une et le modèle lit le fichier et l'applique ; elles sont aussi disponibles comme `/commandes` dans la conversation (tape `/`), avec leurs arguments |
| `.claude/agents/*.md`, `.claude/rules/**/*.md` | listés, lus à la demande |
| tout ce qui précède | interrogeable aussi avec l'outil « rappeler », comme `docs/` et `skills/` |

Rien ne s'exécute tout seul : ces fichiers sont des **consignes et des notes** pour le modèle. Chaque modification de fichier ou commande demande toujours ton accord et peut être annulée.

## Deux façons de s'en servir

| | Travailler dans le dépôt | Travailler dans une copie |
|---|---|---|
| Commande | `lutin importer <dossier> --ici` | `lutin importer <dossier> --copie [--vers <dossier>]` |
| Fichiers | **les mêmes** que ceux de Claude Code : chaque outil voit les changements de l'autre | une copie (historique git compris, sans `node_modules`, `.venv`…) ; l'original n'est jamais touché |
| Quand | tu veux de la continuité, rien à fusionner | tu veux essayer, ou garder l'original à l'abri ; compare ou fusionne ensuite avec git |

Sans `--ici` ni `--copie`, la commande demande (copie par défaut). Dans la page : **Mémoire > Projet Claude > Importer un projet Claude…**. Le dossier devient un dossier de travail et le dossier actif.

À savoir :

- Ajouter un dossier n'est possible que depuis cette machine (niveau « cette machine seulement », ou ligne de commande), comme tout dossier de travail.
- Un dossier sans `CLAUDE.md` ni `.claude/` est refusé (utilise `lutin travaux ajouter` pour un dossier ordinaire).
- Avec Docker, monte le dépôt sous `/travail` et déclare-le avec `LUTIN_TRAVAUX` (voir [DOCKER.fr.md](DOCKER.fr.md)).
- Lutin utilise des modèles locaux : un `CLAUDE.md` très long et beaucoup de skills coûtent du contexte. Garde-les courts et laisse le modèle lire le détail à la demande.
