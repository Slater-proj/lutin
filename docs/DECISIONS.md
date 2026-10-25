# Décisions

Ce que le projet a choisi, pourquoi, et ce qui reste à trancher. Une décision change quand on a une meilleure raison, pas parce que le fichier est vieux : on ajoute alors une ligne datée.

## Prises

| Date | Décision | Raison |
|---|---|---|
| 2026-10-25 | **Nom : Lutin.** Commande `lutin`. | Court, français, facile à taper ; le lutin travaille chez toi, sans bruit. À vérifier : disponibilité du nom du dépôt GitHub et du paquet sur PyPI avant publication. |
| 2026-10-25 | **Dépôt public** sur GitHub. | Demande du propriétaire. Conséquence : tout ce qui est commité est public (voir CONTRIBUER.md, « Données personnelles »). |
| 2026-10-25 | **Bibliothèque standard seulement**, aucune dépendance. | Installation simple, peu de surface d'attaque, rien à mettre à jour. |
| 2026-10-25 | **Deux interfaces sur un seul moteur** : navigateur (PWA) et ligne de commande (`lutin chat`). | Le terminal parle au même serveur local avec un jeton réservé à l'utilisateur : mêmes outils, mêmes accords, même historique. |
| 2026-10-25 | **Cinq rôles** : polyvalent, rapide, créatif, code, images. | « Images » = comprendre les images (vision), pas en générer. |
| 2026-10-25 | **Modèles sans filtre : proposés, jamais imposés.** Option « modèles avancés », avertissement affiché, jamais choisis automatiquement. | Le choix revient à l'utilisateur ; le projet ne les met pas en avant. |
| 2026-10-25 | **Aucune installation de modèle sans accord.** La vérification au lancement propose. | Un modèle pèse 2 à 60 Go. |
| 2026-10-25 | **Aucune télémétrie.** Les seuls accès réseau : catalogue et registre d'Ollama (GET anonymes), téléchargements demandés, recherche web si la case est cochée. | Confiance. |
| 2026-10-25 | **Pas d'accord automatique hors niveau « machine »** (règle dure dans le code, testée). | Exécuter des commandes à distance sans accord est le pire scénario. |
| 2026-10-25 | **Installation par script (PowerShell / shell)** + `pip`, dans un environnement privé de l'utilisateur, sans droits administrateur. | Simple, auditable (un script lisible), Windows et Linux avec le même mécanisme. |

## À trancher

- **Catalogue : qui note les modèles, et comment ?** Les notes actuelles sont éditoriales (1 à 10) et ont été écrites sans mesure sur du matériel réel. Piste : un petit banc de tests maison (code, français, appel d'outils) exécuté sur quelques modèles de référence, résultats publiés dans le dépôt. Tant que ce n'est pas fait, les notes sont un point de départ.
- **Signature des fichiers publiés.** Sans signature, Windows SmartScreen peut avertir. Options : SignPath (gratuit pour l'open source), Azure Trusted Signing (payant), ou publier seulement des sommes de contrôle pour la 0.x.
- **Installateur graphique Windows** (`.exe` avec Python embarqué) : pas fait. Le script PowerShell couvre le besoin tant que la version reste 0.x.
- **Exposition de l'adresse du proxy** : faut-il accepter une plage (`10.0.0.0/24`) ? Oui dans le code ; à documenter avec un exemple Docker.
- **Langues.** Interface et textes en français ; extraire les chaînes avant d'ajouter l'anglais.
- **Où est le catalogue distant ?** `catalogue_url` est vide : à renseigner avec l'adresse « raw » du dépôt une fois publié, puis tester le téléchargement réel.

## Connu mais pas vérifié

- Détection AMD / Intel / Apple : analysée sur des sorties d'exemple, **jamais exécutée sur ces machines**.
- Comparaison des empreintes de modèles avec le registre d'Ollama : suppose que l'empreinte affichée par Ollama est celle du manifeste du registre. **À valider sur une vraie machine** (un test avec un faux registre ne le prouve pas).
- `install.ps1` : **exécuté pour de vrai sous Windows** avec une source locale (installation, deuxième exécution « déjà à jour », montée de version, `lutin update`). Pas avec une source publiée (elle n'existe pas encore).
- `install.sh` : seulement la syntaxe (`bash -n`). **Jamais exécuté sur Linux ni macOS**, comme tout le reste du code sur ces systèmes : la CI Ubuntu sera le premier vrai essai.
- Installation d'Ollama sous Linux et macOS : prévue (script officiel d'Ollama, avec ton accord), non testée.
- Page web : Chrome sans écran charge la vraie page servie par le vrai serveur, sans erreur JavaScript, et la liste des modèles s'affiche. Les **scénarios** (changer de conversation pendant une réponse, boutons « chercher », pastille verte) n'ont pas de test automatique dans un navigateur.
- Python : suite de tests verte sous Windows avec 3.10, 3.12 et 3.13.

## Nom du projet

« Lutin » est un nom de travail. Le nom nu **est déjà pris sur PyPI** (un autre projet, « Lutin generic builder ») : le paquet publié devra s'appeler autrement (par exemple `lutin-ai`, libre au 2026-10-25), même si la commande reste `lutin`. Le dépôt GitHub compte déjà environ 240 dépôts dont le nom contient « lutin » ; aucun n'empêche d'en créer un autre sous ton compte.
