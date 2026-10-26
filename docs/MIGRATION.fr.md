[English](MIGRATION.md) · **Français**

# Reprendre un autre assistant

Tu utilises déjà un assistant construit sur le même moteur (l'assistant Ollama dont Lutin est issu) et tu veux ses données dans Lutin sans rien perdre. Lutin lit les dossiers de l'ancien assistant **sur place** (rien à exporter avant) ou une archive `.zip`, et te laisse choisir ce qui vient.

```bash
lutin reprendre <dossier de l'ancien assistant>          # montre ce qu'il a trouvé, demande quoi reprendre
lutin reprendre <dossier> --conversations --skills       # ou choisis avec des options (--memoire, --reglages, --tout)
lutin reprendre <sauvegarde.zip>                         # une sauvegarde de Lutin (lutin sauvegarde), ou un zip de donnees/ memoire/ skills/
```

Dans la page : **Mémoire > Reprendre les données d'un autre assistant…**.

| Catégorie | Ce qui vient | Où ça va |
|---|---|---|
| Conversations | tous les `donnees/conversations/*.json` (dates et ordre gardés ; les copies `.bak` et les fichiers illisibles sont sautés) | les conversations de Lutin. Les liens vers les anciennes sauvegardes de fichiers sont retirés ; une conversation prend le dossier de travail actif à sa première utilisation |
| Mémoire | `CONTEXTE.md`, `MEMOIRE.md` | la mémoire de Lutin. La tienne n'est **jamais écrasée** : si elle diffère du texte de départ de Lutin, l'ancienne est posée à côté sous `CONTEXTE.importe-<date>.md` |
| Skills | les `*.md` de `skills/` (à côté du dossier de l'ancien assistant, ou `--dossier-skills <dossier>`) | `skills/` du **dossier de travail actif** |
| Réglages | fenêtre de contexte, température, réflexion, étapes d'outils, garde-fous… | les réglages de Lutin, fusionnés avec les tiens |

Sécurité :

- **Rien n'est écrasé** sans `--ecraser` (ou la case dans la page) : une conversation ou un skill qui existe déjà est laissé et compté.
- Avant toute écriture, l'état actuel de Lutin est gardé dans `donnees/import/avant-import-<date>.zip`.
- Le **modèle** et les **accords automatiques** (fichiers, commandes) ne sont **jamais** repris : le modèle n'est peut-être pas installé ici, et les accords, c'est à toi de les redonner.
- Un `.zip` qui écrirait en dehors de ses dossiers est refusé ; on n'y lit que les conversations, les réglages, la mémoire et les skills.
- La reprise ne se fait que depuis cette machine (comme l'ajout d'un dossier de travail).

Pour un dépôt Claude Code (`CLAUDE.md`, `.claude/`), voir [CLAUDE-PROJECTS.fr.md](CLAUDE-PROJECTS.fr.md).
