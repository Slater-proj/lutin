# Lutin avec Docker

Une image prête à l'emploi : Lutin dans un conteneur, Ollama dans un autre, un seul fichier `docker-compose.yml`. Pratique sous Linux, sur un serveur ou un NAS.

> **Honnêteté.** L'image et le fichier Compose ont été écrits et relus, et le script de démarrage a été exécuté en local (hors conteneur), mais **l'image n'avait pas encore été construite ni lancée au moment de l'écriture** : la CI (`docker build` puis démarrage et contrôle de la page de connexion) en est le premier essai. Si quelque chose ne marche pas, ouvre un [bug](https://github.com/Slater-proj/lutin/issues/new/choose) avec `docker compose logs`.

## Prérequis

| Quoi | Détail |
|---|---|
| Docker | Docker Engine 24 ou plus (Linux), ou Docker Desktop (Windows, macOS), avec **Docker Compose v2** (`docker compose`). |
| Place disque | **8 à 60 Go pour les modèles** (volume `ollama`), 1 Go pour le reste. |
| Mémoire | Celle des modèles que tu choisis : 8 Go de RAM au minimum pour un petit modèle, bien plus pour un grand. |
| Carte graphique (facultatif) | NVIDIA + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) sur l'hôte. Sans carte, Ollama utilise le processeur (plus lent). AMD : voir la documentation d'Ollama (image `ollama/ollama:rocm`). |
| Port | `8777`, publié sur `127.0.0.1` de l'hôte uniquement (voir « Sécurité »). |

## Démarrage rapide

```bash
mkdir lutin && cd lutin
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.gpu.yml   # seulement avec une carte NVIDIA
mkdir travail                                                     # ton dossier de travail
sudo chown 1000:1000 travail                                      # Linux : le conteneur tourne sous l'utilisateur 1000

docker compose up -d                                              # sans carte graphique
# ou avec une carte NVIDIA :
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

1. **Le code PIN** : `docker compose logs lutin | grep PIN` (ou `docker compose exec lutin lutin pin` pour en obtenir un nouveau).
2. Ouvre **http://localhost:8777**, entre le PIN : ton navigateur est appairé.
3. **Installe un modèle** : `docker compose exec lutin lutin modeles` montre les modèles conseillés pour ta machine, puis  
   `docker compose exec lutin lutin modeles installer qwen3:8b`  
   (ou l'onglet Modèles de l'interface). Le téléchargement passe par le conteneur `ollama` et reste dans son volume.

Dans le terminal : `docker compose exec lutin lutin chat`.

## Les volumes

| Volume | Dans le conteneur | Contenu | À sauvegarder ? |
|---|---|---|---|
| `lutin-data` | `/data` | configuration, conversations, mémoire, journal des actions, appareils appairés | **oui** |
| `./travail` | `/travail` | **ton dossier de travail** : le seul endroit que Lutin peut lire et modifier | c'est ton projet : déjà chez toi |
| `ollama` | `/root/.ollama` (conteneur Ollama) | les modèles | non (retéléchargeables), mais lourd |

Pour mettre les modèles sur un autre disque, remplace `ollama:/root/.ollama` par un chemin (`/mnt/gros-disque/modeles:/root/.ollama`).

**Droits sur les dossiers.** Le conteneur Lutin n'est pas administrateur : il tourne sous l'utilisateur **1000**. Un dossier monté depuis l'hôte (`./travail`) doit lui être accessible en écriture : `sudo chown 1000:1000 travail`. Sans cela, Lutin refuse de démarrer avec un message clair.

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
| `OLLAMA_URL` | `http://ollama:11434` | où est Ollama. Sur la machine hôte : `http://host.docker.internal:11434` (ajoute `extra_hosts: ["host.docker.internal:host-gateway"]` sous Linux). |
| `LUTIN_NIVEAU` | `reseau` | `reseau` (code PIN) ou `proxy`. « machine seulement » n'existe pas dans un conteneur : le port ne doit pas être ouvert sans protection. |
| `LUTIN_URL_PUBLIQUE`, `LUTIN_PROXY_IP` | – | niveau `proxy` : adresse publique (`https://…`) et adresse(s) du proxy telles que Lutin les voit (séparées par des virgules). |
| `LUTIN_TRAVAUX` | – | autres dossiers de travail (virgules). |
| `LUTIN_HORS_LIGNE` | – | `1` : mode hors ligne strict (aucune connexion vers Internet ; il faudra avoir téléchargé les modèles avant). |
| `LUTIN_GPU` | – | carte déclarée à la main si elle n'est pas détectée : `24` ou `NVIDIA RTX 4090=24` (mémoire en Go). |
| `LUTIN_PORT` | `8777` | port dans le conteneur. |

Ces variables sont **réappliquées à chaque démarrage** : elles sont la source de vérité pour l'accès et les dossiers de travail.

## Sécurité

- Le port est publié sur **`127.0.0.1:8777`** : seule la machine hôte y accède. Pour ton réseau local, écris `"8777:8777"` dans `ports` (le code PIN protège, mais lis [SECURITE.md](SECURITE.md)) ; pour Internet, passe **derrière un proxy** avec authentification forte (`LUTIN_NIVEAU=proxy`).
- Les accords automatiques (écriture, commandes) sont **désactivés** aux niveaux `reseau` et `proxy`.
- Le conteneur n'est pas administrateur ; les commandes que Lutin lance s'exécutent **dans le conteneur** (avec seulement ce qu'il contient : Python, git, sh) et ne voient que `/travail` et `/data`. C'est une protection de plus, et une limite : pour qu'il lance les outils de ton projet (compilateur, tests…), installe-les dans une image dérivée.
- N'expose jamais le port d'Ollama (`11434`) : il n'est pas publié dans ce Compose, ne le change pas.

## Carte NVIDIA

1. Installe le NVIDIA Container Toolkit sur l'hôte et redémarre Docker (`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`).
2. Vérifie : `docker run --rm --gpus all ubuntu nvidia-smi`.
3. Démarre avec `-f docker-compose.gpu.yml`. Lutin **lit** la carte (il n'en a pas besoin pour calculer) pour conseiller des modèles qui tiennent dedans ; Ollama l'utilise.

Si la carte n'est pas détectée (AMD, configuration particulière) : `LUTIN_GPU="Ma carte=16"`.

## Mettre à jour, sauvegarder, arrêter

```bash
docker compose pull && docker compose up -d                       # mise à jour (les volumes ne sont pas touchés)
docker compose exec lutin lutin sauvegarde /data/sauvegarde.zip   # puis : docker compose cp lutin:/data/sauvegarde.zip .
docker compose down                                               # arrêt (les volumes restent) ; « down -v » les EFFACE
```

Restaurer : copie le `.zip` dans `/data` (`docker compose cp sauvegarde.zip lutin:/data/`), arrête Lutin (`docker compose stop lutin`), puis  
`docker compose run --rm lutin restaurer /data/sauvegarde.zip --oui` et `docker compose start lutin`.

Les images publiées : `ghcr.io/slater-proj/lutin:latest` (dernière version), `:X.Y.Z` (une version précise), `:rc-<branche>` (candidate d'une branche, pour tester avant fusion).

## Dépannage

| Symptôme | Piste |
|---|---|
| Lutin s'arrête avec « volumes … accessibles en écriture » | `sudo chown 1000:1000 travail` (et `docker compose down` puis `up` si le volume `lutin-data` a été créé par un autre utilisateur : `docker compose run --rm --user root lutin chown -R 1000:1000 /data`) |
| « Ollama ne répond pas » | `docker compose logs ollama` ; le conteneur Lutin attend qu'Ollama soit prêt (`depends_on`). Avec Ollama sur l'hôte : `OLLAMA_URL=http://host.docker.internal:11434`. |
| La page répond « nom d'hôte non autorisé » | Tu accèdes par un nom que Lutin ne connaît pas. Utilise `localhost`, une adresse privée, ou (niveau `proxy`) l'adresse déclarée dans `LUTIN_URL_PUBLIQUE`. |
| Les modèles conseillés sont trop petits | La carte n'est pas vue par Lutin : `-f docker-compose.gpu.yml` ou `LUTIN_GPU`. |
| Téléchargement de modèle impossible | `LUTIN_HORS_LIGNE=1` est actif, ou pas d'accès à Internet. |
