[English](DECISIONS.md) · **Français**

# Décisions

Ce que le projet a choisi, pourquoi, et ce qui reste à trancher. Une décision change quand on a une meilleure raison, pas parce que le fichier est vieux : on ajoute alors une ligne datée.

## Prises

| Date | Décision | Raison |
|---|---|---|
| 2026-10-25 | **Nom : Lutin.** Commande `lutin`. | Court, français, facile à taper ; le lutin travaille chez toi, sans bruit. Le nom nu est pris sur PyPI (autre projet) : Lutin n'est **pas** publié sur PyPI, il se distribue par les Releases GitHub, les scripts d'installation et l'image Docker. |
| 2026-10-25 | **Dépôt public** `Slater-proj/lutin` sur GitHub. | Demande du propriétaire. Tout ce qui est commité est public (voir CONTRIBUTING.fr.md, « Données personnelles »). |
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
| 2026-10-25 | **Image Docker** : accès par code PIN, port publié sur `127.0.0.1` par défaut, utilisateur non administrateur. | « Cette machine seulement » n'a pas de sens dans un conteneur : le port ne doit jamais être ouvert sans protection. |
| 2026-10-26 | **Deux langues : français et anglais**, pour l'application (interface, messages, ligne de commande) et pour le dépôt (README, docs). Le français reste la langue d'écriture du code ; tout texte affiché passe par un dictionnaire et un test échoue si une traduction manque. | Lutin est écrit en français et d'abord utilisé en français ; l'anglais l'ouvre à tous. Langue : variable d'environnement, puis réglage (`lutin langue`, réglages de la page), puis système. |
| 2026-10-26 | **Docker : une image complète par défaut** (Lutin + Ollama dans le même conteneur, `:latest`), et une image légère (`:slim`, Lutin seul) pour ceux qui ont déjà Ollama ailleurs. | « Je lance l'image et ça marche » : rien d'autre à installer. Le prix est la taille (plusieurs Go, les bibliothèques d'Ollama). |
| 2026-10-26 | **Installateur Windows** (`lutin-setup-*.exe`, Inno Setup) : par utilisateur, sans droits administrateur, en français et en anglais. Il utilise le Python déjà présent sur l'ordinateur (un environnement privé, comme `install.ps1`) et n'installe rien d'autre ; sans Python, il copie celui qu'il embarque. Construit et testé (installation, réinstallation, Python embarqué, désinstallation) en CI. | Ceux qui ont le plus besoin d'un installateur n'ont pas Python ; ceux qui l'ont ne doivent pas en recevoir un second. |
| 2026-10-26 | **Pas de signature de l'installateur Windows pour l'instant.** SignPath Foundation a été étudiée puis abandonnée. | Trop de mise en place (réputation, approbations manuelles, double authentification partout) pour un public d'une personne ; les sommes de contrôle sont publiées. À reconsidérer si le projet a de vrais utilisateurs. |
| 2026-10-26 | **Nouvelle version de Lutin annoncée dans la page** (un bandeau, une fois par jour au plus, silencieux hors ligne, ignorable) : rien n'est installé sans l'utilisateur. | Les modèles étaient déjà vérifiés au lancement ; Lutin lui-même non. |
| 2026-10-26 | **Projets Claude** (`CLAUDE.md`, `.claude/`) repris sur place ou en copie. | Le contexte construit avec Claude Code ne doit pas se perdre en changeant d'outil. |

## À trancher

- **Catalogue : qui note les modèles ?** Les notes sont éditoriales (1 à 10), écrites sans mesure sur du matériel réel. Le banc d'essai (`lutin bench --exporter`) permet maintenant de proposer des corrections justifiées ; il manque des résultats publiés sur quelques machines de référence.
- **Autres langues.** Le mécanisme est en place (`src/lutin/langues/`) : en ajouter une demande un dictionnaire pour les messages et un pour la page, et un code dans `i18n.LANGUES`.

## Connu mais pas vérifié

- **Linux** : toute la suite de tests tourne en CI sous Ubuntu (Python 3.10 à 3.13), avec un faux Ollama. **Jamais essayé avec un vrai Ollama et une vraie carte graphique.**
- **macOS, AMD, Intel** : le code est écrit pour, la détection est analysée sur des sorties d'exemple, mais **rien n'a jamais été exécuté sur ces systèmes ni ces cartes**.
- **Images Docker** : construites et démarrées par la CI (page, code PIN, Ollama dans l'image complète) et publiées sur ghcr.io. **Jamais lancées avec une vraie carte NVIDIA**, ni sur un NAS.
- **Comparaison des empreintes de modèles** avec le registre d'Ollama : suppose que l'empreinte affichée par Ollama est celle du manifeste. À valider sur une vraie machine.
- **Catalogue en ligne** : lu depuis `raw.githubusercontent.com/Slater-proj/lutin/main/…` ; la CI hebdomadaire contrôle le catalogue, mais la lecture réelle depuis un Lutin installé n'a pas été tracée.
- **`install.ps1`** : exécuté pour de vrai sous Windows (source locale : installation, relance sans changement, montée de version) puis depuis l'adresse publiée, ce qui a révélé un défaut de BOM (corrigé en 0.1.1, avec un test). `install.sh` : syntaxe et CI seulement.
- **Installation d'Ollama** sous Linux et macOS : prévue (script officiel d'Ollama, avec accord), non testée.
- **Page web** : Chrome sans écran charge la vraie page sans erreur JavaScript en français et en anglais (tests) et les captures du README en viennent. Les scénarios (changer de conversation pendant une réponse, pastille verte, boutons de recherche) n'ont pas de test automatique dans un navigateur.
- **Banc d'essai** : testé avec un faux Ollama ; jamais lancé sur un vrai modèle.
- **Python** : suite verte sous Windows avec 3.10, 3.12 et 3.13, et sous Ubuntu avec 3.10 à 3.13.
