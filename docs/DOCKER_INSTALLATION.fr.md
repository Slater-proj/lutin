[English](DOCKER_INSTALLATION.md) · **Français**

# Installer Lutin avec Docker, moteurs compris

Pour l'image « tout-en-un » (Lutin et Ollama dans un conteneur), lis d'abord [DOCKER.fr.md](DOCKER.fr.md). Cette page couvre le cas où **le moteur est un conteneur à côté de Lutin** (Ollama ou llama.cpp), et ce qu'il faut savoir sur Docker Linux et Docker Desktop (Windows, WSL2).

> **Honnêteté.** Les profils Ollama et llama.cpp du fichier `docker-compose.moteurs.yml` sont **vérifiés sur le papier et par des tests de fichiers**, **pas sur du vrai matériel**. Les profils `llamacpp-cuda`, `llamacpp-vulkan` et `llamacpp-intel` n'ont jamais tourné avec une vraie carte : si tu les essaies, dis-moi ce qui s'est passé.

## 1. Choisir son moteur : les profils Compose

Un seul fichier, un profil par moteur :

```bash
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.moteurs.yml
mkdir travail && sudo chown 1000:1000 travail            # Linux : le conteneur tourne avec l'utilisateur 1000

docker compose -f docker-compose.moteurs.yml --profile ollama up -d            # Ollama (le plus simple)
docker compose -f docker-compose.moteurs.yml --profile llamacpp-cpu up -d      # llama.cpp sur le processeur
docker compose -f docker-compose.moteurs.yml --profile llamacpp-cuda up -d     # carte NVIDIA
docker compose -f docker-compose.moteurs.yml --profile llamacpp-vulkan up -d   # carte AMD ou Intel
docker compose -f docker-compose.moteurs.yml --profile llamacpp-intel up -d    # Intel (SYCL)
```

Lutin sait déjà où est le moteur : le fichier règle `OLLAMA_URL` et `LUTIN_LLAMACPP_URL`. La carte du moteur dans **Réglages > Moteurs** est préremplie, rien à taper. Une adresse que tu règles dans la page l'emporte sur la variable.

**Ne sais-tu pas lequel prendre ?** Ollama. Pour comparer sur ta machine, voir [BENCH_MOTEURS.fr.md](BENCH_MOTEURS.fr.md).

### llama.cpp : un fichier de modèle à la fois

Le conteneur llama.cpp sert **un** fichier GGUF. Dépose-le dans le volume `lutin-models`, puis donne son nom :

```bash
LUTIN_GGUF=qwen3-8b-q4_k_m.gguf docker compose -f docker-compose.moteurs.yml --profile llamacpp-cuda up -d
```

Changer de modèle = relancer avec un autre `LUTIN_GGUF`. (Le mode routeur, plusieurs modèles sans redémarrer, est réservé au llama.cpp que Lutin gère lui-même hors Docker.)

### Cartes graphiques

| Carte | Profil | Il faut |
|---|---|---|
| NVIDIA | `llamacpp-cuda` (ou Ollama avec `docker-compose.gpu.yml`) | le [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) sur l'hôte |
| AMD, Intel (Vulkan) | `llamacpp-vulkan` | `/dev/dri` ; `RENDER_GID` = groupe de `/dev/dri/renderD*` (`getent group render \| cut -d: -f3`) |
| Intel (SYCL) | `llamacpp-intel` | pareil |
| aucune | `llamacpp-cpu` ou `ollama` | rien |

Mesure, ne suppose pas : une puce graphique intégrée peut être **plus lente** que le processeur (essai fait sur un Core Ultra 5 : environ 8 contre 11 jetons/s).

## 2. Docker sous Linux

Docker Engine 24 ou plus et le plugin Compose v2 (`docker compose`, avec un espace). Pas à pas depuis un Debian vierge : [TUTO-DOCKER-DEBIAN.fr.md](TUTO-DOCKER-DEBIAN.fr.md).

## 3. Docker Desktop sous Windows (WSL2)

- Docker Desktop utilise **WSL2**, qui prend par défaut la moitié de la mémoire du PC. Un modèle de taille moyenne demande plus : crée `%UserProfile%\.wslconfig` avec

  ```ini
  [wsl2]
  memory=24GB
  ```

  puis `wsl --shutdown` et relance Docker Desktop.
- **Garde tes volumes dans Docker** (volumes nommés, comme dans nos fichiers) : un dossier Windows monté (`C:\...`) est beaucoup plus lent pour des fichiers de plusieurs Go.
- La carte NVIDIA est donnée aux conteneurs par le pilote Windows (pas de Toolkit à installer dans WSL2 avec Docker Desktop récent). AMD et Intel ne sont pas fiables dans ce cas : utilise plutôt llama.cpp installé par Lutin directement sous Windows.

## 4. Vérifier : `lutin doctor`

```bash
docker compose exec lutin lutin doctor      # dans le conteneur
lutin doctor                                # sur l'hôte : version de Docker, Compose, mémoire donnée à Docker
```

Dans le conteneur, le diagnostic dit : si `/data` et `/models` sont de **vrais volumes** (sinon tes réglages, conversations et modèles disparaissent quand le conteneur est recréé), s'ils sont accessibles en écriture, la mémoire vue par le conteneur, si les moteurs à côté répondent, et la carte visible. Il ne contient aucune donnée personnelle : tu peux le coller dans un rapport de problème.

## 5. Redémarrer, recréer, mettre à jour : rien ne se perd

Les réglages, les conversations, la mémoire et les moteurs sont dans `lutin-data` ; les modèles dans `lutin-models`. Ces deux **volumes nommés** survivent à `docker compose down`, à `docker compose up -d --force-recreate` et à `docker compose pull` (seul `docker compose down -v` les supprime : ne l'écris pas à la légère). Le démarrage du conteneur **réapplique** la configuration depuis les variables d'environnement (il ne réinstalle rien et n'efface rien). Un test de CI le vérifie : il crée un conteneur, y écrit une donnée, le recrée, et contrôle qu'elle est toujours là.

Pour mettre à jour : `docker compose pull && docker compose up -d`.

## 6. Premier lancement

Tant qu'**aucun moteur n'est prêt**, la page ne t'envoie pas dans l'onglet Modèles (où rien ne marcherait) : l'onglet est grisé avec la raison, et une carte propose d'installer le moteur conseillé, d'en choisir un autre ou de remettre à plus tard. Avec le profil Compose du moteur, le moteur est prêt dès que son conteneur répond.
