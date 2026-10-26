[English](FEATURES.md) · **Français**

# Fonctions du quotidien

Ce que Lutin fait en plus de discuter. Tout se passe sur ta machine ; rien ici n'envoie quoi que ce soit sur Internet.

## Tester mon PC

Onglet Modèles > **⏱ Tester mon PC** (ou `/pc` dans la conversation). Lutin mesure la vitesse du modèle actif sur cette machine (environ 20 secondes), puis explique simplement ce que ça veut dire : combien de mots par seconde, combien de temps prend une réponse de 300 mots, si le modèle tient sur la carte graphique, et quoi changer si c'est lent (un modèle plus léger déjà installé ou conseillé pour ta machine, une fenêtre de contexte plus petite, le profil de charge « Discret »). Rien n'est modifié à ta place.

## Essai à blanc

Coche **Essai à blanc** sous la zone de message (ou `/essai on`). Lutin travaille normalement mais **n'écrit rien et ne lance rien** : chaque fichier qu'il écrirait et chaque commande qu'il lancerait est montré (avec la différence pour les fichiers) au lieu de demander un accord, et le modèle sait qu'il s'agit d'une simulation. La lecture et la recherche fonctionnent pour de vrai, donc la proposition s'appuie sur tes vrais fichiers. Sert à voir ce que Lutin compte faire avant de le laisser faire : tu décoches, tu redemandes, cette fois pour de bon.

## Notes de l'assistant

Onglet Mémoire > **Notes de l'assistant** : la liste de ce que Lutin a décidé de retenir, avec sa date et un bouton *Supprimer*. Une note fausse ou dépassée ne demande plus de modifier le fichier à la main (ce qui reste possible sous « Modifier le fichier à la main »).

## Documents (PDF, Word, texte LibreOffice, PowerPoint, Excel…)

Dépose tes documents dans le dossier `docs/` du dossier de travail (ou `documents/`). Lutin lit les **PDF, .docx, .odt, .pptx, .xlsx et pages HTML**, en plus du Markdown et des textes sans programme externe, les cherche hors ligne et **cite la page** (ou la diapositive, ou la feuille) où il a trouvé la réponse. Onglet Mémoire > **Documents** : liste de ce qui a été lu et zone de recherche ; l'assistant s'en sert aussi tout seul avec les outils `rappeler` et `lire`. Limites : les PDF scannés (images de texte) et les PDF chiffrés ne se lisent pas ; un document de plus de 30 Mo est refusé ; un document illisible est signalé sans bloquer les autres.

## Tâches planifiées

Onglet Mémoire > **Tâches planifiées** : une demande que Lutin traite tout seul à l'heure dite, les jours choisis (« chaque matin, résume ce qui a changé dans le dépôt »). Le résultat est une conversation « ⏰ nom » dans la liste, avec un bouton *Voir le résultat*.

- **Lecture seule** : personne n'est là pour accepter, la tâche tourne donc comme un essai à blanc : elle lit et cherche pour de vrai, chaque écriture ou commande est seulement montrée.
- Ne démarre que si aucune réponse n'est en cours (une seule carte graphique) ; une tâche manquée parce que le PC était éteint se fait au démarrage de Lutin, le jour même seulement.
- Création, pause et suppression depuis cette machine seulement (comme les dossiers de travail). *Lancer maintenant* teste une tâche sans attendre.
- Lutin doit tourner à l'heure dite (la page n'a pas besoin d'être ouverte).

## Images

Clique sur **📎** à côté de la zone de message, ou colle (Ctrl+V) ou glisse une image : PNG, JPEG, GIF ou WebP, 8 Mo et 4 images par message au plus. Si le modèle courant ne voit pas les images, Lutin passe pour cette demande sur un modèle installé qui les voit (rôle « Images » de l'onglet Modèles), ou te dit qu'il n'y en a pas et ignore les images. Les images restent dans le dossier de données de Lutin (`images/`), seules les plus récentes sont renvoyées au modèle, et les images orphelines sont supprimées après deux jours.

## Accès et appareils

L'onglet **Accès** réunit qui peut utiliser Lutin (le niveau), le code PIN avec un **QR code** pour connecter un téléphone en le scannant, et la liste des appareils connectés (avec *Révoquer*). Un changement de niveau qui demande un redémarrage affiche un bandeau avec un bouton *Redémarrer* quand Lutin peut le faire lui-même (commande `lutin` ou Docker), et dit quoi faire sinon. Détails : [SECURITY.fr.md](SECURITY.fr.md).

## Commandes dans la conversation

Tape `/` pour la liste : `/pc`, `/essai`, `/acces`, `/sante`, `/model`, `/compact`… et les commandes d'un projet Claude (`.claude/commands/*.md`, voir [CLAUDE-PROJECTS.fr.md](CLAUDE-PROJECTS.fr.md)) sont disponibles aussi, avec leurs arguments.
