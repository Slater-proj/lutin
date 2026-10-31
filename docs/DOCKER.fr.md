[English](DOCKER.md) · **Français**

# Lutin avec Docker

Une image prête à l'emploi : **Lutin et Ollama dans le même conteneur**. Tu la lances, tu ouvres la page, tu installes un modèle : c'est tout. Pratique sous Linux, sur un serveur ou un NAS.

> **Honnêteté.** Les images sont construites et démarrées par la CI (page de connexion, code PIN, Ollama dans l'image complète) et publiées sur `ghcr.io`. Elles n'ont **jamais été lancées avec une vraie carte NVIDIA** ni sur un NAS : si quelque chose ne marche pas, ouvre un [bug](https://github.com/Slater-proj/lutin/issues/new/choose) avec `docker compose logs`.

## Deux images

| Étiquette | Contenu | Taille | Pour |
|---|---|---|---|
| `ghcr.io/slater-proj/lutin:latest` (ou `:X.Y.Z`) | **Lutin + Ollama** | plusieurs Go (les bibliothèques d'Ollama) + les modèles | **la plupart des gens** : rien d'autre à installer |
| `ghcr.io/slater-proj/lutin:slim` (ou `:X.Y.Z-slim`) | Lutin seul | quelques centaines de Mo | si Ollama tourne déjà ailleurs (machine hôte, autre conteneur) : [docker-compose.slim.yml](../docker-compose.slim.yml) |

## Prérequis

| Quoi | Détail |
|---|---|
| Docker | Docker Engine 24 ou plus (Linux), ou Docker Desktop (Windows, macOS), avec **Docker Compose v2** (`docker compose`). |
| Place disque | **8 à 60 Go pour les modèles** (volume `lutin-models`), 4 Go pour le reste. |
| Mémoire | Celle des modèles que tu choisis : 8 Go de RAM au minimum pour un petit modèle, bien plus pour un grand. |
| Carte graphique (facultatif) | NVIDIA + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) sur l'hôte. Sans carte, Ollama utilise le processeur (plus lent). AMD : voir la documentation d'Ollama (image ROCm). |
| Port | `8777`, publié sur `127.0.0.1` de l'hôte uniquement (voir « Sécurité »). |

## Démarrage rapide

**Une commande** (sans carte, modèles gardés dans un volume Docker, tes fichiers dans `./travail`) :

```bash
mkdir -p lutin/travail && cd lutin
sudo chown 1000:1000 travail          # Linux : le conteneur tourne sous l'utilisateur 1000
docker run -d --name lutin --restart unless-stopped \
  -p 127.0.0.1:8777:8777 \
  -v lutin-data:/data -v lutin-models:/models -v "$PWD/travail":/travail \
  ghcr.io/slater-proj/lutin:latest
```

Avec une carte NVIDIA, ajoute `--gpus all`.

**Ou avec Compose** (un fichier que tu peux garder et modifier) :

```bash
mkdir lutin && cd lutin
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.gpu.yml   # seulement avec une carte NVIDIA
mkdir travail && sudo chown 1000:1000 travail

docker compose up -d                                              # sans carte graphique
# ou avec une carte NVIDIA :
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

1. **Le code PIN** : `docker logs lutin 2>&1 | grep PIN` (`docker compose logs lutin | grep PIN` avec Compose), ou `docker exec lutin lutin pin` pour en obtenir un nouveau.
2. Ouvre **http://localhost:8777**, entre le PIN : ton navigateur est appairé.
3. **Installe un modèle** : `docker exec lutin lutin modeles` montre les modèles conseillés pour ta machine, puis  
   `docker exec lutin lutin modeles installer qwen3:8b`  
   (ou l'onglet Modèles de l'interface). Le téléchargement passe par l'Ollama du conteneur et reste dans le volume `lutin-models`.

Dans le terminal : `docker exec -it lutin lutin chat`.

**Langue** : anglais par défaut. Pour le français : dans la page (Réglages > Langue), avec `docker exec lutin lutin langue fr`, ou avec `-e LUTIN_LANGUE=fr`.

## Les volumes

| Volume | Dans le conteneur | Contenu | À sauvegarder ? |
|---|---|---|---|
| `lutin-data` | `/data` | configuration, conversations, mémoire, journal des actions, appareils appairés, journal d'Ollama (`ollama.log`) | **oui** |
| `./travail` | `/travail` | **ton dossier de travail** : le seul endroit que Lutin peut lire et modifier | c'est ton projet : déjà chez toi |
| `lutin-models` | `/models` | les modèles (image complète) | non (retéléchargeables), mais lourd |

Pour mettre les modèles sur un autre disque, remplace `lutin-models:/models` par un chemin (`/mnt/gros-disque/modeles:/models`).

**Droits sur les dossiers.** Le conteneur n'est pas administrateur : il tourne sous l'utilisateur **1000**. Un dossier monté depuis l'hôte (`./travail`, et un dossier de modèles) doit lui être accessible en écriture : `sudo chown 1000:1000 travail`. Sans cela, Lutin refuse de démarrer avec un message clair.

**Plusieurs dossiers de travail.** Monte-les sous `/travail` et déclare-les :

```yaml
    environment:
      LUTIN_TRAVAUX: /travail/projet-2,/travail/documents
    volumes:
      - ./travail:/travail
      - ./projet-2:/travail/projet-2
      - ./documents:/travail/documents
```

## Les variables

| Variable | Défaut | Rôle |
|---|---|---|
| `LUTIN_LANGUE` | – (anglais) | `fr` ou `en`. Impose la langue (sinon, le réglage de la page s'applique). |
| `LUTIN_NIVEAU` | `reseau` | `reseau` (code PIN) ou `proxy`. « machine seulement » n'existe pas dans un conteneur : le port ne doit pas être ouvert sans protection. |
| `LUTIN_URL_PUBLIQUE`, `LUTIN_PROXY_IP` | – | niveau `proxy` : adresse publique (`https://…`) et adresse(s) du proxy telles que Lutin les voit (séparées par des virgules). |
| `LUTIN_TRAVAUX` | – | autres dossiers de travail (virgules). |
| `LUTIN_HORS_LIGNE` | – | `1` : mode hors ligne strict (aucune connexion vers Internet ; il faudra avoir téléchargé les modèles avant). |
| `LUTIN_GPU` | – | carte déclarée à la main si elle n'est pas détectée : `24` ou `NVIDIA RTX 4090=24` (mémoire en Go). |
| `LUTIN_PORT` | `8777` | port dans le conteneur. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` (complète) · `http://ollama:11434` (légère) | où est Ollama. Pour un Ollama sur la machine hôte (image légère) : `http://host.docker.internal:11434` (ajoute `extra_hosts: ["host.docker.internal:host-gateway"]` sous Linux). |

Ces variables sont **réappliquées à chaque démarrage** : elles sont la source de vérité pour l'accès et les dossiers de travail.

## Sécurité

- Le port est publié sur **`127.0.0.1:8777`** : seule la machine hôte y accède. Pour ton réseau local, écris `"8777:8777"` dans `ports` (le code PIN protège, mais lis [SECURITY.fr.md](SECURITY.fr.md)) ; pour Internet, passe **derrière un proxy** avec authentification forte (`LUTIN_NIVEAU=proxy`).
- Les accords automatiques (écriture, commandes) sont **désactivés** aux niveaux `reseau` et `proxy`.
- Le conteneur n'est pas administrateur ; les commandes que Lutin lance s'exécutent **dans le conteneur** (avec seulement ce qu'il contient : Python, git, sh) et ne voient que `/travail`, `/data` et `/models`. C'est une protection de plus, et une limite : pour qu'il lance les outils de ton projet (compilateur, tests…), installe-les dans une image dérivée.
- Dans l'image complète, Ollama n'écoute que sur le `127.0.0.1` du conteneur, et son port `11434` n'est jamais publié. Ne le publie jamais.

## Carte graphique dans le conteneur

Un conteneur ne voit pas la carte graphique tant qu'on ne la lui donne pas. Sans elle, tout tourne sur le processeur (plus lent, mais ça marche).

| Ta carte | Quoi faire | Image |
|---|---|---|
| **NVIDIA** (Linux) | installer le [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) sur l'hôte, puis `docker run --gpus all …` ou `-f docker-compose.gpu.yml` | `:latest` |
| **NVIDIA** (Windows) | Docker Desktop avec le moteur WSL 2 et un pilote NVIDIA récent ; puis le même `--gpus all` | `:latest` |
| **AMD** (Linux, carte gérée par ROCm) | pilote amdgpu sur l'hôte, puis `--device /dev/kfd --device /dev/dri --group-add video --group-add <id du groupe render>` ou `-f docker-compose.amd.yml` | `:rocm` |
| **Intel / carte intégrée** | non utilisée par Ollama dans les conteneurs : le processeur travaille (budget = RAM) | `:latest` |
| **Mac** | Docker sous macOS ne peut pas donner le GPU Apple à un conteneur : lance Ollama directement sur le Mac et prends l'image `:slim` avec `OLLAMA_URL=http://host.docker.internal:11434` | `:slim` |

**Vérifier que ça marche** (ne pas croire, vérifier) :

1. NVIDIA : `docker run --rm --gpus all ubuntu nvidia-smi` doit lister la carte ; puis `docker exec lutin nvidia-smi` aussi.
2. Les premières lignes de `/data/ollama.log` (`docker exec lutin head -20 /data/ollama.log`) disent quelle carte le conteneur voit (NVIDIA, `/dev/kfd`, `/dev/dri`) ; les lignes d'Ollama disent ensuite s'il a trouvé un périphérique de calcul.
3. Dans la page, **Santé > mémoire vidéo** montre la carte, et une fois un modèle chargé, « modèle chargé à … % sur la carte » : **100 %** = la carte travaille ; **0 %** = c'est le processeur (carte non donnée ou non gérée).
4. `docker exec lutin lutin doctor` dit « Pas de carte graphique utilisable » et quoi ajouter si le conteneur n'en voit aucune.

AMD : ROCm gère une liste limitée de cartes ; pour les autres, la documentation d'Ollama explique `HSA_OVERRIDE_GFX_VERSION`. L'image `:rocm` et `docker-compose.amd.yml` n'ont **jamais été essayés sur une vraie carte AMD** : dis-moi ce que tu obtiens.

Si Lutin ne voit pas la carte mais qu'Ollama la voit, déclare-la à la main pour que les modèles conseillés tiennent : `LUTIN_GPU="Ma carte=16"` (mémoire en Go).

## Homelab : un mini PC Debian derrière un reverse proxy et Authelia

Le cas d'un petit serveur partagé (par exemple un mini PC Intel Core Ultra 5 avec 32 Go de RAM dont une dizaine seulement est libre), sous Debian, où Lutin est joignable en `https://lutin.exemple.fr` derrière ton reverse proxy et **Authelia**.

> **Honnêteté.** Ce montage a été vérifié avec un **faux proxy** (en-têtes `Host` et `Remote-User` simulés : accès, refus sans identité, refus d'un mauvais nom d'hôte, droits d'administration) et par les tests de la CI. Il n'a **jamais tourné avec un vrai Authelia, un vrai Debian ni ce processeur** : les temps de réponse ci-dessous sont des ordres de grandeur, pas des mesures.

### 1. Lancer Lutin

```bash
docker network create --subnet 172.30.0.0/24 proxy      # une fois ; ton reverse proxy doit être sur ce réseau aussi
mkdir -p travail && sudo chown 1000:1000 travail
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.proxy.yml
# édite : LUTIN_URL_PUBLIQUE, LUTIN_PROXY_IP (le réseau du proxy), LUTIN_ADMINS (ton identifiant Authelia)
docker compose -f docker-compose.proxy.yml up -d
```

Le fichier [docker-compose.proxy.yml](../docker-compose.proxy.yml) ne publie **aucun port** : le reverse proxy joint `http://lutin:8777` sur le réseau partagé. Si ton proxy tourne sur l'hôte et non dans Docker, publie `127.0.0.1:8777:8777` et mets `LUTIN_PROXY_IP: 172.17.0.1`.

| Variable | Rôle ici |
|---|---|
| `LUTIN_NIVEAU=proxy` | l'identité vient du proxy (en-tête `Remote-User` posé par Authelia) ; Lutin ne croit cet en-tête **que** s'il arrive d'une adresse de `LUTIN_PROXY_IP` |
| `LUTIN_URL_PUBLIQUE` | l'adresse publique : tout autre nom d'hôte est refusé (le proxy doit donc **transmettre le `Host` d'origine**) |
| `LUTIN_PROXY_IP` | l'adresse ou le réseau du proxy tel que Lutin le voit (`docker network inspect proxy`) |
| `LUTIN_ADMINS` | les identifiants Authelia qui peuvent **configurer depuis la page** : dossiers de travail, extensions, missions, suppression des fichiers créés. Vide : tout se configure par `docker exec lutin lutin …` et la page ne sert qu'à discuter. Les autres utilisateurs d'Authelia ne font que discuter. |
| `mem_limit` | la mémoire que le conteneur peut prendre : **Lutin s'y adapte** (sans limite, il verrait les 32 Go de la machine et conseillerait des modèles trop gros) |
| `LUTIN_BUDGET_GO` | impose le maximum pour les modèles (Go) si tu préfères ne pas limiter le conteneur |
| `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=5m` | une demande à la fois, un modèle à la fois, la RAM rendue après 5 minutes de silence |

### 2. Régler le reverse proxy

Trois points comptent pour Lutin, quel que soit le proxy :

1. **Authelia devant**, qui transmet l'identité dans `Remote-User` (et le proxy **écrase** tout `Remote-User` envoyé par le client).
2. **Le `Host` d'origine est transmis** (`lutin.exemple.fr`), sinon Lutin répond « nom d'hôte non autorisé ».
3. **Pas de tampon sur les réponses** : Lutin affiche la réponse mot à mot (un flux continu). Un proxy qui met tout en mémoire jusqu'à la fin donne l'impression que rien ne se passe. Lutin envoie `X-Accel-Buffering: no` (nginx le respecte) ; les autres proxys ne tamponnent pas par défaut. Prévois aussi de **longs délais** (une réponse sur processeur peut durer plusieurs minutes) et **30 Mo** d'envoi (pièces jointes).

nginx (avec les extraits habituels d'Authelia pour `auth_request`) :

```nginx
location / {
    include /config/nginx/authelia-location.conf;       # ou ton équivalent : auth_request + $user depuis Remote-User
    proxy_pass http://lutin:8777;
    proxy_set_header Host $host;
    proxy_set_header Remote-User $user;                 # l'identité vue par Authelia, jamais celle du client
    proxy_buffering off;
    proxy_read_timeout 3600s;
    client_max_body_size 30m;
}
```

Traefik (étiquettes du service, avec ton middleware `authelia` qui expose `Remote-User` dans `authResponseHeaders`) :

```yaml
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy
      - traefik.http.routers.lutin.rule=Host(`lutin.exemple.fr`)
      - traefik.http.routers.lutin.entrypoints=websecure
      - traefik.http.routers.lutin.tls.certresolver=letsencrypt
      - traefik.http.routers.lutin.middlewares=authelia@docker
      - traefik.http.services.lutin.loadbalancer.server.port=8777
```

Caddy :

```caddy
lutin.exemple.fr {
    forward_auth authelia:9091 {
        uri /api/authz/forward-auth
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }
    reverse_proxy lutin:8777 {
        flush_interval -1
    }
}
```

### 3. Choisir des modèles pour ce genre de machine

Sans carte graphique utilisable (la puce graphique intégrée Intel n'est pas utilisée par Ollama dans un conteneur), tout tourne sur le processeur. Avec ~8 Go pour les modèles, Lutin conseille :

| Modèle | Verdict de Lutin | À quoi s'attendre (estimation) |
|---|---|---|
| `qwen3:4b`, `llama3.2:3b`, `qwen3:1.7b` | confortable | quelques mots par seconde ; le bon choix pour discuter et pour les missions simples |
| `qwen3:8b`, `qwen2.5-coder:7b` | à la limite | plus lent ; faisable pour du code ou un texte soigné, pas pour une conversation vive |
| `qwen3:14b` et plus | trop gros | ne tient pas dans le budget |

`docker exec lutin lutin modeles` donne la liste pour ta machine. Baisse la **fenêtre de contexte** à 8 192–12 288 jetons dans Réglages : sur processeur, relire 24 000 jetons à chaque réponse se compte en minutes.

### 4. Ce qui marche, ce qui ne marche pas dans ce montage

| Fonction | Dans le conteneur |
|---|---|
| Conversation, outils, fichiers de `/travail`, PDF et Word, missions longues (elles tournent **dans le conteneur** : elles ne voient que `/travail`) | ✔ |
| Telegram, courriel, X, recherche web | ✔ (connexions sortantes) |
| Télécharger un fichier créé, la liste « Fichiers créés » et le ménage | ✔ |
| **Ouvrir** un fichier avec une application | ✘ caché : un serveur n'a pas de bureau, utilise Télécharger |
| Accord auto / Commandes auto dans la conversation | ✘ désactivés au niveau proxy (règle de sécurité) : chaque commande demande ton clic. Une **mission « Autonome »** tourne seule, dans le conteneur. |
| Aperçu d'une page (`apercu_page`) | ✘ pas de navigateur dans l'image : le message le dit |
| ComfyUI (images) | ✘ ComfyUI ne tourne pas dans le conteneur, et un processeur seul est trop lent pour générer des images |
| Carte graphique Intel intégrée | ✘ non utilisée par Ollama dans un conteneur |

**Mises à jour et sauvegarde** : voir plus bas ; sauvegarde les volumes `lutin-data` et ton dossier `travail`.

## Les addons dans le conteneur

Les réglages, secrets et états des addons sont dans le volume `/data` : ils survivent à une mise à jour. **Telegram, courriel, X et travail de fond** marchent comme sur la machine (le travail de fond ne voit que les dossiers de travail montés dans le conteneur). **ComfyUI** ne peut pas être lancé par un conteneur qui ne le contient pas : lance Lutin directement sur la machine pour cet addon, ou installe ComfyUI dans ta propre image et monte son dossier.

## Mettre à jour, sauvegarder, arrêter

```bash
docker compose pull && docker compose up -d                       # mise à jour (les volumes ne sont pas touchés)
docker compose exec lutin lutin sauvegarde /data/sauvegarde.zip   # puis : docker compose cp lutin:/data/sauvegarde.zip .
docker compose down                                               # arrêt (les volumes restent) ; « down -v » les EFFACE
```

Restaurer : copie le `.zip` dans `/data` (`docker compose cp sauvegarde.zip lutin:/data/`), arrête Lutin (`docker compose stop lutin`), puis  
`docker compose run --rm lutin restaurer /data/sauvegarde.zip --oui` et `docker compose start lutin`.

Les images publiées : `ghcr.io/slater-proj/lutin:latest` (dernière version, complète), `:X.Y.Z` (une version précise), `:slim` et `:X.Y.Z-slim` (Lutin seul), `:rocm` et `:X.Y.Z-rocm` (complète, pour les cartes AMD), `:rc-<branche>` et ses variantes `-slim` / `-rocm` (candidate d'une branche, pour tester avant fusion).

## Dépannage

| Symptôme | Piste |
|---|---|
| Lutin s'arrête avec « volumes … accessibles en écriture » | `sudo chown 1000:1000 travail` (et `docker compose down` puis `up` si le volume `lutin-data` a été créé par un autre utilisateur : `docker compose run --rm --user root lutin chown -R 1000:1000 /data /models`) |
| « Ollama ne répond pas » | Image complète : regarde `/data/ollama.log` (`docker compose exec lutin tail /data/ollama.log`). Image légère : `docker compose logs ollama` ; avec Ollama sur l'hôte : `OLLAMA_URL=http://host.docker.internal:11434`. |
| La page répond « nom d'hôte non autorisé » | Tu accèdes par un nom que Lutin ne connaît pas. Utilise `localhost`, une adresse privée, ou (niveau `proxy`) l'adresse déclarée dans `LUTIN_URL_PUBLIQUE`. |
| Les modèles conseillés sont trop petits | La carte n'est pas vue par Lutin : `--gpus all` / `-f docker-compose.gpu.yml`, ou `LUTIN_GPU`. |
| Téléchargement de modèle impossible | `LUTIN_HORS_LIGNE=1` est actif, ou pas d'accès à Internet. |
