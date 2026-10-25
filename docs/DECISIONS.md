# Décisions

Ce que le projet a choisi, pourquoi, et ce qui reste à trancher. Une décision change quand on a une meilleure raison, pas parce que le fichier est vieux : on ajoute alors une ligne datée.

## Prises

| Date | Décision | Raison |
|---|---|---|
| 2026-10-25 | **Nom : Lutin.** Commande `lutin`. | Court, français, facile à taper ; le lutin travaille chez toi, sans bruit. Le nom nu est pris sur PyPI (autre projet) : Lutin n'est **pas** publié sur PyPI, il se distribue par les Releases GitHub, les scripts d'installation et l'image Docker. |
| 2026-10-25 | **Dépôt public** `Slater-proj/lutin` sur GitHub. | Demande du propriétaire. Tout ce qui est commité est public (voir CONTRIBUER.md, « Données personnelles »). |
| 2026-10-25 | **Bibliothèque standard seulement**, aucune dépendance. | Installation simple, peu de surface d'attaque, rien à mettre à jour. |
| 2026-10-25 | **Deux interfaces sur un seul moteur** : navigateur (PWA) et ligne de commande (`lutin chat`). | Le terminal parle au même serveur local avec un jeton réservé à l'utilisateur : mêmes outils, mêmes accords, même historique. |
| 2026-10-25 | **Cinq rôles** : polyvalent, rapide, créatif, code, images. | « Images » = comprendre les images (vision), pas en générer. |
| 2026-10-25 | **Modèles sans filtre : proposés, jamais imposés.** Option « modèles avancés », avertissement affiché, jamais choisis automatiquement. | Le choix revient à l'utilisateur ; le projet ne les met pas en avant. |
| 2026-10-25 | **Aucune installation de modèle sans accord.** La vérification au lancement propose. | Un modèle pèse 2 à 60 Go. |
| 2026-10-25 | **Aucune télémétrie.** Les seuls accès réseau : catalogue et registre d'Ollama (GET anonymes), publications GitHub (`lutin update`), téléchargements demandés, recherche web si la case est cochée. Tous coupés par le mode hors ligne strict. | Confiance. |
| 2026-10-25 | **Pas d'accord automatique hors niveau « machine »** (règle dure dans le code, testée). | Exécuter des commandes à distance sans accord est le pire scénario. |
| 2026-10-25 | **Installation par script (PowerShell / shell)** dans un environnement privé de l'utilisateur, sans droits administrateur ; par défaut la dernière publication GitHub. Idempotente. | Simple, auditable, Windows et Linux avec le même mécanisme. |
| 2026-10-25 | **Mode hors ligne strict** centralisé (`horsligne.py`), vérifié par un test qui surveille les connexions réelles. | Une garantie qu'on peut auditer en un endroit. |
| 2026-10-25 | **Dossiers de travail multiples, un seul actif à la fois**, ajout réservé à cette machine. | Une seule racine à la fois évite les conflits et les accès croisés ; l'ajout à distance permettrait de déclarer `/`. |
| 2026-10-25 | **Notes mesurées = indicateur** (11 questions, aucun code du modèle exécuté), sans effet automatique sur le choix des modèles. | Un banc minuscule ne doit pas décider seul ; il sert à contester les notes éditoriales. |
| 2026-10-25 | **Version déduite des étiquettes git** (setuptools-scm) ; chaque fusion dans `main` publie (étiquette, Release, image) ; chaque autre branche produit une candidate **sans étiquette**. | Personne ne fixe un numéro à la main ; les candidates se testent sans polluer l'historique des versions. |
| 2026-10-25 | **Image Docker** : Lutin et Ollama séparés, accès par code PIN, port publié sur `127.0.0.1` par défaut, utilisateur non administrateur. | « Cette machine seulement » n'a pas de sens dans un conteneur : le port ne doit jamais être ouvert sans protection. |

## À trancher

- **Catalogue : qui note les modèles ?** Les notes sont éditoriales (1 à 10), écrites sans mesure sur du matériel réel. Le banc d'essai (`lutin bench --exporter`) permet maintenant de proposer des corrections justifiées ; il manque des résultats publiés sur quelques machines de référence.
- **Signature des fichiers publiés.** Sans signature, Windows SmartScreen peut avertir. Options : SignPath (gratuit pour l'open source), Azure Trusted Signing (payant), ou seulement des sommes de contrôle (déjà publiées) pour la 0.x.
- **Installateur graphique Windows** (`.exe` avec Python embarqué) : pas fait. Le script PowerShell couvre le besoin tant que la version reste 0.x.
- **Langues.** Interface et textes en français ; extraire les chaînes avant d'ajouter l'anglais.
- **Nouvelle version de Lutin signalée dans l'interface** : aujourd'hui seulement avec `lutin update` (les modèles, eux, sont vérifiés au lancement).

## Connu mais pas vérifié

- **Linux, macOS, AMD, Intel** : le code est écrit pour, la détection est analysée sur des sorties d'exemple, mais **rien n'a jamais été exécuté sur ces systèmes**. La CI Ubuntu est le premier vrai essai.
- **Image Docker** : `Dockerfile`, `docker-compose.yml` et `entrypoint.sh` sont écrits et relus ; le script de démarrage a été exécuté en local (hors conteneur) avec succès (page de connexion, code PIN, dossiers de travail). **L'image n'a jamais été construite** (pas de Docker sur la machine de développement) : la CI la construit et la démarre.
- **Workflows GitHub** : syntaxe YAML vérifiée ; **jamais exécutés** (le dépôt n'est pas encore poussé). Le calcul des versions est testé sur un vrai dépôt git temporaire.
- **Comparaison des empreintes de modèles** avec le registre d'Ollama : suppose que l'empreinte affichée par Ollama est celle du manifeste. À valider sur une vraie machine.
- **Catalogue en ligne** : lu depuis `raw.githubusercontent.com/Slater-proj/lutin/main/…` ; test réel impossible tant que le dépôt n'est pas public.
- **`install.ps1`** : exécuté pour de vrai sous Windows avec une source locale (installation, relance sans changement, montée de version). La résolution de la « dernière publication » GitHub n'a jamais tourné : il n'y a pas encore de publication. `install.sh` : syntaxe seulement.
- **Installation d'Ollama** sous Linux et macOS : prévue (script officiel d'Ollama, avec accord), non testée.
- **Page web** : Chrome sans écran charge la vraie page sans erreur JavaScript et les captures du README en viennent. Les scénarios (changer de conversation pendant une réponse, pastille verte, boutons de recherche) n'ont pas de test automatique dans un navigateur.
- **Banc d'essai** : testé avec un faux Ollama ; jamais lancé sur un vrai modèle.
- **Python** : suite verte sous Windows avec 3.10, 3.12 et 3.13.
