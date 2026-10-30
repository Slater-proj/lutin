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

## Pièces jointes : images, documents, fichiers texte et code

Clique sur **📎** à côté de la zone de message, ou colle (Ctrl+V) ou glisse des fichiers. Jusqu'à 4 **images** (PNG, JPEG, GIF, WebP, 8 Mo chacune) et 5 **fichiers** (20 Mo chacun) par message :

- **Documents** : PDF, Word, LibreOffice (texte, feuilles, diapositives), PowerPoint, Excel, HTML. Le texte est lu une fois, à l'envoi (un PDF scanné sans texte est refusé tout de suite, avec la raison).
- **Fichiers texte et code** : notes, Markdown, CSV, JSON, journaux, sous-titres et code source des langages courants (un fichier texte est aussi reconnu à son contenu, quelle que soit son extension).

Le texte des fichiers est ajouté à ton message **pour le modèle seulement** : la conversation ne garde que le nom. Seuls les derniers messages rejouent leurs fichiers, et un long fichier est coupé à une part de la fenêtre de contexte (avec une mention de ce qui a été coupé), pour ne jamais noyer le modèle. Rien dans un fichier n'est exécuté. Les fichiers restent dans le dossier de données de Lutin (`pieces/`) et les orphelins sont supprimés après deux jours.

## Images

Clique sur **📎** à côté de la zone de message, ou colle (Ctrl+V) ou glisse une image : PNG, JPEG, GIF ou WebP, 8 Mo et 4 images par message au plus. Si le modèle courant ne voit pas les images, Lutin passe pour cette demande sur un modèle installé qui les voit (rôle « Images » de l'onglet Modèles), ou te dit qu'il n'y en a pas et ignore les images. Les images restent dans le dossier de données de Lutin (`images/`), seules les plus récentes sont renvoyées au modèle, et les images orphelines sont supprimées après deux jours.

## Modes

Réglages > **Mode** (ou `/mode` dans la conversation) change ce que Lutin peut faire et sa façon de faire. Toute modification de fichier et toute commande demandent ton accord dans tous les modes.

| Mode | Outils | Quand |
|---|---|---|
| **Polyvalent** (par défaut) | lire, chercher, modifier, commandes, web, notes | questions de tous les jours, rédaction, analyse, un peu de code |
| **Travail** | tout, y compris les symboles de code | comprendre, modifier et tester les fichiers d'un dossier |
| **Écriture** | pas de commandes ; tes documents et anciennes conversations sont rappelés automatiquement | rédiger, reformuler, chercher dans tes documents |
| **Recherche** | lecture seule : lire, chercher, web ; rappels activés | lire et recouper fichiers, PDF et notes, répondre avec les sources, ne rien changer |
| **Discussion** | aucun outil | simple conversation, la plus rapide |

## Accès et appareils

L'onglet **Accès** réunit qui peut utiliser Lutin (le niveau), le code PIN avec un **QR code** pour connecter un téléphone en le scannant, et la liste des appareils connectés (avec *Révoquer*). Un changement de niveau qui demande un redémarrage affiche un bandeau avec un bouton *Redémarrer* quand Lutin peut le faire lui-même (commande `lutin` ou Docker), et dit quoi faire sinon. Détails : [SECURITY.fr.md](SECURITY.fr.md).

## Dossiers de travail et dossier par défaut

Les dossiers réseau (`\\serveur\partage\dossier`, un lecteur réseau, un NAS) marchent comme les autres : s'il est refusé, Lutin dit pourquoi (le compte du service n'y a pas accès, le partage est éteint…). **Parcourir…** choisit un dossier, **Déplacer…** le déplace (avec ses fichiers) ailleurs (la même fenêtre permet de retenir seulement le nouveau chemin quand tu l'as déplacé à la main). Un réglage garde aussi une copie Markdown lisible de chaque conversation dans le dossier de travail (`conversations-lutin/`).

Tout ce qui concerne les dossiers est dans Réglages > **Dossiers de travail** (la barre latérale n'a plus de liste de dossiers, pour laisser de la place). Le dossier utilisé est marqué ★ et c'est aussi celui que Lutin ouvre au démarrage : **Utiliser ce dossier** le change, maintenant et pour les prochains démarrages. **Ajouter un dossier…** en ajoute un et **Retirer** sort n'importe quel dossier de la liste, le principal compris (les fichiers ne sont jamais supprimés). Retirer le dossier en cours passe tout de suite au suivant ; sans dossier restant, Lutin travaille dans son dossier par défaut (`Lutin`, dans ton dossier personnel).

## Vérifier les mises à jour

Réglages > **Version de Lutin** affiche la version installée et un bouton **Vérifier les mises à jour** : il interroge GitHub tout de suite et dit « à jour » ou quelle version est disponible (une bannière propose alors la commande de mise à jour). Si GitHub ne répond pas, la vraie cause est affichée (pare-feu, certificat, mode hors ligne strict…) ; quand l'API de GitHub est bloquée, la page publique des publications sert de repli. Lutin vérifie aussi tout seul au démarrage, au plus une fois par jour. Rien n'est installé sans toi.

## Icône dans la zone de notification (Windows)

Le raccourci **Lutin** ouvre Lutin **sans fenêtre de console** : une icône Lutin dans la zone de notification (en bas à droite). Clic gauche : ouvre l'interface. Clic droit : **Code PIN** (pour connecter un téléphone), **Ouvrir l'interface**, **Redémarrer**, **Quitter**. Au tout premier lancement, la configuration guidée s'ouvre dans une console. Le serveur tourne en arrière-plan ; s'il s'arrête sur une erreur, il est relancé, et sa sortie va dans `donnees/serveur.log` (les erreurs de l'icône elle-même, s'il y en a, dans `donnees/zone.log`). La version terminal reste disponible avec `lutin` (et le raccourci « Lutin (terminal) »). Une seule icône tourne à la fois : la relancer ouvre l'interface.

## Commandes dans la conversation

Tape `/` pour la liste : `/pc`, `/essai`, `/acces`, `/sante`, `/model`, `/compact`… et les commandes d'un projet Claude (`.claude/commands/*.md`, voir [CLAUDE-PROJECTS.fr.md](CLAUDE-PROJECTS.fr.md)) sont disponibles aussi, avec leurs arguments.
