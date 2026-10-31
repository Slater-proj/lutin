[English](PROMPT-DOCKER-COMPOSE.md) · **Français**

# Un prompt pour que ton IA locale écrive le `docker-compose.yml` de Lutin

Ce prompt est écrit **pour ton IA locale** (celle qui connaît ta machine et ta charte de docker-compose). Copie le bloc ci-dessous et colle-le dans une conversation avec elle. Elle doit pouvoir travailler seule : explorer ta machine en lecture seule, retrouver **ta charte**, puis te rendre un `docker-compose.yml` prêt à l'emploi, un fichier `.env`, les commandes à lancer et la vérification, sans te poser de questions inutiles.

Avant de le coller, remplace les trois valeurs marquées **À REMPLACER** (ton nom de domaine, ton identifiant Authelia, le budget mémoire pour les modèles) : l'IA découvre elle-même le reste (processeur, mémoire, reverse proxy, réseaux). Le tutoriel humain, étape par étape, est dans [TUTO-DOCKER-DEBIAN.fr.md](TUTO-DOCKER-DEBIAN.fr.md).

````text
# MISSION

Tu es mon administrateur système Docker. Produis, de façon AUTONOME, un `docker-compose.yml` prêt à l'emploi (plus son `.env` et les commandes de mise en route) pour déployer **Lutin**, un assistant IA local, sur mon mini PC Debian, en suivant **MA charte de docker-compose** (mes conventions habituelles). Ne me pose une question que si une information est introuvable ET bloquante ; dans ce cas, regroupe toutes tes questions en une seule fois.

# CE QUE JE TE DONNE

Ma machine : un serveur sous Debian avec Docker et Docker Compose v2 (installés, ou à installer). Décris-la toi-même : processeur, mémoire totale et LIBRE, disque, carte graphique éventuelle (`lscpu`, `free -h`, `df -h`, `nvidia-smi` s'il existe). Mes autres services se partagent la machine : ne compte que sur la mémoire LIBRE.
Domaine : Lutin doit être joignable par mon reverse proxy à l'adresse **https://lutin.example.com**   ← À REMPLACER par mon vrai nom de domaine, protégé par **Authelia** (qui transmet l'identité dans l'en-tête `Remote-User`).
Mon identifiant Authelia (administrateur de Lutin) : **alice**   ← À REMPLACER.
Mémoire que je réserve aux modèles de Lutin : **8 Go**   ← À REMPLACER (sans valeur, prends environ 60 % de la mémoire libre, au plus).
Mon reverse proxy : tu dois le découvrir (nginx / Nginx Proxy Manager / SWAG / Traefik / Caddy).

# MA CHARTE DE DOCKER-COMPOSE

C'est elle qui fait foi pour la forme (noms, arborescence, réseaux, étiquettes, journaux, sécurité, sauvegardes…). Retrouve-la toi-même : cherche dans ta mémoire, dans tes fichiers de référence, et dans mes piles existantes (par exemple `/opt/stacks`, `/srv`, `~/docker`, `/home/*/docker`, tout dossier contenant plusieurs `docker-compose.yml`). Lis 2 ou 3 de mes piles qui tournent déjà pour confirmer mes habitudes réelles : nom du dossier de pile, nom du projet, réseau externe utilisé, façon de nommer les volumes, usage d'un `.env`, politique de redémarrage, limites de ressources, journalisation, étiquettes du reverse proxy, fuseau horaire, utilisateur/UID, emplacement des données persistantes, nommage des conteneurs.
- Si tu trouves ma charte : applique-la point par point, et cite en une ligne d'où elle vient.
- Si tu ne la trouves pas : dis-le en une ligne, déduis mes habitudes de mes piles existantes, et liste les conventions que tu as retenues.
- Là où ma charte et les contraintes techniques de Lutin (ci-dessous) se contredisent, les contraintes de Lutin gagnent : signale chaque écart en une ligne, avec la raison.

# DÉCOUVERTE (LECTURE SEULE, SANS RIEN MODIFIER)

Si tu as accès à un terminal sur la machine, lance (et analyse) par exemple :
`docker --version && docker compose version` · `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Networks}}'` · `docker network ls` puis `docker network inspect <réseau du reverse proxy>` (sous-réseau et passerelle) · `free -h` · `df -h` · `id` · `ls` des dossiers de piles · les fichiers `docker-compose*.yml` existants · la configuration du reverse proxy et le middleware Authelia (noms exacts des middlewares, des entrypoints, du résolveur de certificats) · `docker volume ls`.
Si tu n'as PAS d'accès terminal : donne-moi en une seule fois la liste exacte des commandes à exécuter et de ce que je dois te coller en retour, puis attends.
Ne lance AUCUNE commande qui modifie quelque chose (pas de `up`, `down`, `rm`, `prune`, `chown`, `mkdir`) avant mon accord explicite.

# CE QU'IL FAUT SAVOIR SUR LUTIN (tout est exact ; n'invente rien d'autre)

- Image : `ghcr.io/slater-proj/lutin:latest` = Lutin + Ollama dans UN conteneur (c'est celle qu'il faut). Une version précise : `ghcr.io/slater-proj/lutin:X.Y.Z`. L'étiquette `:slim` = Lutin sans Ollama (inutile ici).
- Port dans le conteneur : **8777** (HTTP). Ne pas le publier si le reverse proxy est dans Docker : il joint `http://lutin:8777` par un réseau Docker commun. Si le reverse proxy tourne sur l'hôte : publier `127.0.0.1:8777:8777` seulement.
- Ollama écoute à l'intérieur du conteneur (127.0.0.1:11434) : **ne jamais publier le port 11434**.
- Le conteneur tourne sous l'utilisateur **1000:1000** : tout dossier de l'hôte monté en écriture doit appartenir à 1000:1000 (`chown 1000:1000`), sinon Lutin refuse de démarrer avec un message clair.
- Volumes : `/data` (configuration, conversations, mémoire, appareils : À SAUVEGARDER), `/models` (modèles Ollama : gros, retéléchargeables), `/travail` (SEUL dossier que Lutin peut lire et modifier ; c'est un dossier de l'hôte à monter). Autres dossiers de travail éventuels : sous `/travail/...` et listés dans `LUTIN_TRAVAUX` (séparés par des virgules).
- Variables d'environnement (les SEULES à utiliser) :
  `LUTIN_NIVEAU=proxy` (identité fournie par le reverse proxy) · `LUTIN_URL_PUBLIQUE=https://lutin.example.com` (tout autre nom d'hôte est refusé) · `LUTIN_PROXY_IP=<réseau ou adresse du reverse proxy tel que Lutin le voit>` (ex. `172.30.0.0/24` ; la valeur doit correspondre au sous-réseau réel du réseau partagé) · `LUTIN_ADMINS=alice` (identifiants Authelia autorisés à configurer depuis la page ; vide = ligne de commande seulement) · `LUTIN_LANGUE=fr` · `LUTIN_BUDGET_GO=8` (Go maximum pour les modèles) · `LUTIN_HORS_LIGNE=1` (facultatif : plus aucune connexion sortante) · `LUTIN_TRAVAUX` · `LUTIN_GPU` (inutile ici) · `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=5m` (économie de mémoire).
- Limite de mémoire : `mem_limit` (ou `deploy.resources.limits.memory`) un peu au-dessus du budget des modèles (par exemple 10g pour 8 Go) : Lutin adapte ses conseils de modèles à cette limite. Avec ~8 Go pour les modèles, les bons choix sont des modèles de 3 à 4 milliards de paramètres (`qwen3:4b`, `llama3.2:3b`) ; 7 à 8 milliards est à la limite. Sans carte NVIDIA ou AMD donnée au conteneur, tout tourne sur le processeur (les puces graphiques intégrées ne sont pas utilisées).
- Santé : l'image a déjà un HEALTHCHECK (`curl -fsS http://127.0.0.1:8777/`). Ne le redéfinis que si ta charte l'exige, avec la même commande et `start_period` d'au moins 20 s (40 s conseillé : Ollama démarre dans le même conteneur).
- Le reverse proxy doit : (1) être derrière Authelia et transmettre l'identité dans `Remote-User` en écrasant tout `Remote-User` venant du client ; (2) transmettre le `Host` d'origine ; (3) ne PAS mettre les réponses en mémoire tampon (la réponse s'affiche mot à mot : `proxy_buffering off` pour nginx) ; (4) autoriser de longs délais (3600 s) et des envois de 30 Mo.
- `restart: unless-stopped`. Aucun secret n'est nécessaire pour Lutin lui-même (l'identité vient d'Authelia).

# LIVRABLES (dans cet ordre)

1. **Résumé** (5 lignes maximum) : ce que tu as découvert (reverse proxy, réseau, sous-réseau, conventions) et d'où vient ma charte.
2. **`docker-compose.yml`** complet, commenté en une ligne par choix non évident, avec les étiquettes/blocs du reverse proxy que j'utilise réellement (et uniquement celui-là).
3. **`.env`** (valeurs concrètes, sans secret superflu).
4. **Fichiers du reverse proxy / d'Authelia à ajouter** : le bloc exact (nginx, Traefik, Caddy…) ET la règle `access_control` d'Authelia pour mon domaine (politique `two_factor` sauf si ma charte dit autre chose).
5. **Commandes de mise en route**, dans l'ordre : création du dossier de pile et du dossier de travail, `chown 1000:1000`, création du réseau s'il manque, `docker compose config`, `pull`, `up -d`, installation d'un modèle (`docker compose exec lutin lutin modeles installer qwen3:4b`), vérification.
6. **Vérifications** avec le résultat attendu pour chacune : conteneur `healthy`, page joignable derrière Authelia, réponse affichée mot à mot, mon identifiant reconnu comme administrateur.
7. **Retour arrière** : comment tout défaire sans toucher à mes autres piles.
8. **Écarts** entre ma charte et les contraintes de Lutin, un par ligne.

# RÈGLES

- Vérifie ton fichier avant de me le rendre : `docker compose config` doit passer (lance-le si tu peux sans rien démarrer ; sinon relis-le comme le ferait cet outil : indentation, clés valides, réseaux et volumes déclarés).
- Pas de `latest` si ma charte épingle les versions : dans ce cas, mets la dernière version publiée de Lutin que tu connais et dis-moi de vérifier sur https://github.com/Slater-proj/lutin/releases.
- N'expose aucun port inutile, n'ajoute aucun service que je n'ai pas demandé, ne touche pas à mes autres piles.
- Si une valeur dépend de ma machine et que tu ne peux pas la lire (sous-réseau, nom du réseau, nom du middleware), mets une valeur claire entre chevrons `<…>`, explique comment la trouver, et ne la devine pas en silence.
- Ne lance rien de modifiant sans mon accord explicite : termine par « Prêt à appliquer ? » et attends.
````

## Ce que ça donne en pratique

L'IA te rend un résumé, le `docker-compose.yml`, le `.env`, le bloc à ajouter à ton reverse proxy et à Authelia, la liste de commandes et les vérifications, puis te demande ton accord avant d'appliquer. Si elle ne retrouve pas ta charte, elle te le dit et te liste les conventions qu'elle a déduites de tes piles existantes : relis-les avant d'accepter.

**Ce qui est garanti par Lutin** : l'image, le port, l'utilisateur 1000, les volumes et les variables du prompt correspondent exactement à ce que Lutin lit (le fichier [docker-compose.proxy.yml](../docker-compose.proxy.yml) en est la version de référence : l'IA peut s'en servir comme modèle). **Ce qui ne l'est pas** : tout ce qui dépend de ta charte et de ta machine, que l'IA doit découvrir.
