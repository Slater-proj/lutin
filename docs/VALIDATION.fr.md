[English](VALIDATION.md) · **Français**

# Valider Lutin sur du vrai matériel

Les tests automatiques de Lutin utilisent de faux services (faux Ollama, faux Telegram, faux PC appairé). Ils garantissent que la logique est juste, **pas** que ton Ollama, ta carte graphique ou ton second PC se comportent comme prévu. Cette liste est la passe à faire à la main, une fois par version importante : une coche par ligne, une phrase de rapport quand ça ne marche pas.

Pour chaque ligne : **Fais** ce qui est écrit, **vois** ce qui est attendu. Sinon, note la ligne et colle la sortie de `lutin doctor` (aucun contenu personnel) dans un rapport de problème.

## 1. Les moteurs (un par un, sur la machine qui peut le faire tourner)

Réglages > Moteur : seuls les moteurs qui peuvent tourner sur cette machine sont proposés (les autres sont repliés, avec la raison).

| Moteur | Fais | Vois |
|---|---|---|
| Ollama | « Installer » (ou ton installation existante), télécharger un petit modèle depuis l'onglet Modèles | Le modèle apparaît dans la liste, une réponse arrive en quelques secondes |
| llama.cpp | « Installer », choisir un modèle GGUF proposé, « Démarrer » | État « en marche », une réponse arrive ; « Arrêter » libère la mémoire |
| LM Studio | « Installer » (Linux : la bibliothèque libatomic est installée ou la commande exacte est donnée) | Serveur démarré, modèles installés listés |
| ExLlamaV3 (NVIDIA, hors Docker) | « Installer », puis télécharger un modèle par son dépôt Hugging Face (propriétaire/modèle) | Carte visible seulement sur NVIDIA ; une réponse arrive |
| Colibri | « Préparer le modèle » depuis l'onglet Modèles | Aucune commande à saisir à la main ; l'état passe à « prêt » |
| Chaque moteur | « Comparer les moteurs » avec le même modèle | Vitesse et mémoire mesurées, sans erreur |

Pour **chaque** moteur : la liste des modèles installés s'affiche, un modèle se télécharge en un clic avec une progression, et « Tester » renvoie une réponse. Note celui qui échoue et à quelle étape.

## 2. Plusieurs ordinateurs

À faire avec deux vrais PC (A = celui où tu travailles, B = l'autre).

| Étape | Fais | Vois |
|---|---|---|
| Appairer | Sur B : Réglages > Machines, activer, copier le code ; sur A : « Ajouter une machine » | B apparaît, statut vert en moins de 10 s |
| Réveil | Éteindre B, bouton « Réveiller » sur A | B s'allume ; le statut passe au vert sans second clic (la machine est sondée toutes les 2 s) |
| Icône | Sur B, après le démarrage de Windows | L'icône de Lutin est près de l'horloge (au besoin sous la flèche « ^ ») |
| Répondre ici | Choisir « Cette machine » ou « B » dans « Qui répond à tes messages ? » | La réponse vient bien du moteur choisi (nom du moteur visible dans la conversation) |
| Autorisation | Sur A : « Demander » le droit de mise à jour | Sur B : la cloche s'allume ; accepter ; sur A le droit apparaît. **Rien n'est accordé sans la réponse de B** |
| Mise à jour | « Mettre à jour » B depuis A | B affiche la nouvelle version après redémarrage |
| Refus | Retirer le droit sur B | A ne peut plus mettre à jour B, et le dit |

## 3. Notifications et tâches planifiées

| Étape | Fais | Vois |
|---|---|---|
| Canal | Automatisation > Notifications : ajouter Gotify / ntfy / Telegram / webhook, « Envoyer un test » | Le message arrive sur ton téléphone ou ton salon Discord/Slack |
| Tâche | Créer une tâche « donne-moi l'heure », la lancer deux fois | Une seule conversation, deux échanges datés |
| Résultat | Associer le canal à la tâche, la lancer | La réponse de la tâche arrive sur ton canal |
| Échec | Éteindre le moteur, relancer la tâche | La conversation affiche la raison (pas un silence) et la notification le dit |

## 4. Connecteurs MCP (catalogue)

| Étape | Fais | Vois |
|---|---|---|
| Sans programme | Si Node.js ou uv n'est pas installé, brancher « Heure et fuseaux » | Lutin installe uv au passage (le bloc « Programmes utilisés par les connecteurs » le montre, avec un bouton pour le retirer) |
| Heure | Brancher « Heure et fuseaux » | « Branché » avec le nombre d'outils ; demander l'heure à Tokyo dans une conversation |
| Fichiers | Brancher « Fichiers » avec un dossier de test | Le modèle lit ce dossier ; refuse d'écrire tant que le connecteur est en lecture seule |
| Cassé | Brancher avec un dossier qui n'existe pas | Message clair, rien n'est ajouté |
| Home Assistant | Brancher avec l'adresse `/api/mcp` et un jeton longue durée | « Branché » avec ses outils, ou une erreur claire (son transport n'est pas confirmé par la documentation officielle : à vérifier chez toi) |
| Retrait | « Retirer » | Le connecteur disparaît, ses outils aussi |

## 5. Mémoire et recherche

| Étape | Fais | Vois |
|---|---|---|
| Rappel | Dire un fait précis, bavarder longtemps, le redemander avec d'autres mots | Le fait est retrouvé (pluriel, accents, reformulation) |
| Par le sens | Activer la recherche par le sens (modèle d'embeddings), redemander avec un synonyme | Le fait est retrouvé ; sans le modèle, la recherche par mots continue sans erreur |
| Mesure | `python tools/mesurer_rappel.py` | Rappel@1 d'au moins 92 % sur le corpus de référence |

## 6. Sécurité

| Étape | Fais | Vois |
|---|---|---|
| Secrets | Demander à l'assistant de lire le dossier des données de Lutin | Refus net (dossier réservé) |
| Canaux | Recharger la page Notifications | Aucun jeton réaffiché |
| Accès | Ouvrir Lutin depuis un autre appareil du réseau | Le code PIN est demandé |

## Quand tout est coché

Reporte la date, la version (`lutin --version`), le système et la carte graphique dans ton rapport, avec les lignes qui ont échoué. Une version est prête pour une 1.0 quand chaque ligne passe sur au moins un Windows et un Linux.
