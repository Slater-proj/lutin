[English](TUTO-DOCKER-DEBIAN.md) · **Français**

# Installer Lutin avec Docker sur Debian, pas à pas

Ce tutoriel va de « Debian vierge » à « Lutin joignable en `https://lutin.exemple.fr` derrière ton reverse proxy et Authelia ». Chaque étape dit **quoi taper**, **ce que tu dois voir**, et **quoi faire sinon**. Pour la référence complète (variables, volumes, cartes graphiques), voir [DOCKER.fr.md](DOCKER.fr.md).

> **Honnêteté.** Les images sont construites et démarrées par la CI, et le montage « reverse proxy + Authelia » a été vérifié avec un faux proxy. Rien de tout cela n'a tourné avec **ton** Debian, **ton** Authelia ni **ton** processeur : suis les étapes en vérifiant chaque résultat, et dis-moi où ça coince.

## 0. Ce qu'il te faut

| Quoi | Détail |
|---|---|
| Un serveur Debian 12 ou 13 | un mini PC suffit ; accès `sudo` |
| Place disque | 5 Go pour Lutin et Ollama, **+ 3 à 10 Go par modèle** (un modèle de 4 milliards de paramètres pèse environ 3 Go) |
| Mémoire | de quoi faire tourner un modèle : **8 Go libres** permettent les petits modèles (3 à 4 milliards de paramètres) et, à la limite, 7 à 8 milliards |
| Un nom de domaine | par exemple `lutin.exemple.fr`, qui pointe vers ton serveur (ou ton routeur) |
| Un reverse proxy + Authelia | nginx, Traefik ou Caddy, déjà installés ; sinon, saute l'étape 7 et utilise le code PIN (étape 8) |

## 1. Installer Docker (s'il n'y est pas déjà)

Vérifie d'abord :

```bash
docker --version && docker compose version
```

Si les deux commandes répondent, passe à l'étape 2. Sinon, installe Docker Engine depuis le dépôt officiel :

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Pour utiliser Docker sans `sudo` (attention : appartenir au groupe `docker` revient à avoir les droits administrateur sur la machine) :

```bash
sudo usermod -aG docker $USER      # puis déconnecte-toi et reconnecte-toi
```

*Tu dois voir* : `docker run --rm hello-world` affiche « Hello from Docker! ».

## 2. Préparer les dossiers

Lutin tourne dans le conteneur sous l'utilisateur **1000**. Les dossiers de ton serveur qu'il doit pouvoir écrire lui appartiennent donc :

```bash
sudo mkdir -p /opt/lutin/travail
sudo chown -R 1000:1000 /opt/lutin/travail
cd /opt/lutin
```

`/opt/lutin/travail` est le **seul endroit que Lutin peut lire et modifier** (ses missions, les documents qu'il crée…). Mets-y ce que tu veux lui confier. Les conversations, la mémoire et les réglages sont dans un volume Docker (`lutin-data`) ; les modèles dans un autre (`lutin-models`).

## 3. Le réseau partagé avec ton reverse proxy

Lutin ne publie **aucun port** : ton reverse proxy le joint par un réseau Docker commun. Crée-le une fois, avec un sous-réseau fixe (Lutin n'accepte l'identité d'Authelia que si elle vient de ce réseau) :

```bash
docker network create --subnet 172.30.0.0/24 proxy
docker network ls | grep proxy
```

Si ton reverse proxy a déjà un réseau, **utilise-le** au lieu d'en créer un : `docker network inspect <nom> | grep Subnet` te donne son sous-réseau. Ton reverse proxy doit être connecté à ce même réseau.

## 4. Le fichier `docker-compose.yml`

```bash
curl -fsSL -o docker-compose.yml https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.proxy.yml
nano docker-compose.yml
```

Modifie ces lignes (le reste convient à un petit serveur partagé) :

| Ligne | Mets |
|---|---|
| `LUTIN_URL_PUBLIQUE` | ton adresse, avec `https://` : `https://lutin.exemple.fr` |
| `LUTIN_PROXY_IP` | le sous-réseau de l'étape 3 : `172.30.0.0/24` |
| `LUTIN_ADMINS` | ton identifiant **Authelia** (celui de `Remote-User`) : `clement` |
| `LUTIN_LANGUE` | `fr` |
| `mem_limit` et `LUTIN_BUDGET_GO` | la mémoire que tu veux réserver à Lutin : `10g` et `"8"` pour environ 10 Go libres |
| `./travail:/travail` | `/opt/lutin/travail:/travail` |

Vérifie le fichier sans rien lancer :

```bash
docker compose config > /dev/null && echo "fichier valide"
```

## 5. Démarrer

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail 30 lutin
```

*Tu dois voir* : `lutin` en état `Up (healthy)` après une minute environ. Dans les journaux : « Démarrage de Lutin » et l'adresse publique.

*Si ça ne démarre pas* :
- « les volumes … accessibles en écriture » → l'étape 2 (`chown 1000:1000`) n'a pas été faite sur ce dossier.
- `network proxy declared as external, but could not be found` → l'étape 3.
- Le conteneur redémarre en boucle → `docker compose logs lutin` dit pourquoi.

## 6. Installer un modèle

```bash
docker compose exec lutin lutin modeles                    # les modèles conseillés pour cette machine
docker compose exec lutin lutin modeles installer qwen3:4b
```

Avec un budget de 8 Go et un processeur seul, Lutin conseille `qwen3:4b` ou `llama3.2:3b` (confortables) ; `qwen3:8b` est « à la limite » (lent). Le téléchargement est dans le volume `lutin-models`. Tu peux aussi le faire depuis la page (onglet Modèles).

## 7. Brancher le reverse proxy et Authelia

Trois exigences, quel que soit le proxy : **Authelia devant** (qui transmet l'identité dans `Remote-User`), le **`Host` d'origine transmis**, et **pas de tampon** sur les réponses (Lutin affiche la réponse mot à mot). Voir les exemples nginx, Traefik et Caddy dans [DOCKER.fr.md](DOCKER.fr.md), section « Homelab ».

Côté Authelia, ajoute une règle d'accès pour ton domaine (à adapter à ta configuration) :

```yaml
access_control:
  rules:
    - domain: 'lutin.exemple.fr'
      policy: 'two_factor'
```

Puis recharge Authelia et ton reverse proxy.

## 8. Premier essai

1. Ouvre `https://lutin.exemple.fr` : Authelia te demande de te connecter, puis la page de Lutin s'ouvre.
2. En haut à gauche, à côté de « Lutin », choisis le modèle installé.
3. Écris « Bonjour, tu m'entends ? » : la réponse doit s'afficher **mot à mot**. Si elle n'apparaît qu'à la fin, le proxy met les réponses en mémoire tampon (étape 7).
4. Essaie « Crée un petit compte rendu en PDF dans le dossier de travail » : une carte avec **Télécharger** apparaît sous le message.

*Sans reverse proxy* (essai sur ton réseau) : remplace dans le fichier `LUTIN_NIVEAU: proxy` par `reseau`, retire `LUTIN_URL_PUBLIQUE`, `LUTIN_PROXY_IP` et `LUTIN_ADMINS`, ajoute `ports: ["8777:8777"]`, puis `docker compose exec lutin lutin pin` te donne un code à saisir sur la page (lis d'abord [SECURITY.fr.md](SECURITY.fr.md)).

## 9. Au quotidien

| Besoin | Commande |
|---|---|
| Mettre à jour | `docker compose pull && docker compose up -d` (les volumes sont gardés) |
| Voir les journaux | `docker compose logs -f lutin` |
| Sauvegarder | `docker compose exec lutin lutin sauvegarde /data/sauvegarde.zip && docker compose cp lutin:/data/sauvegarde.zip .` |
| Arrêter | `docker compose down` (les volumes restent ; `down -v` les **efface**) |
| Diagnostic à coller dans un rapport | `docker compose exec lutin lutin doctor` |
| Voir ce que Lutin a modifié | `docker compose exec lutin lutin journal` |

Sauvegarde le volume `lutin-data` (conversations, mémoire, réglages) et ton dossier `/opt/lutin/travail`. Les modèles se retéléchargent.

## 10. Dépannage rapide

| Symptôme | Piste |
|---|---|
| « nom d'hôte non autorisé » | le proxy ne transmet pas le `Host` d'origine, ou `LUTIN_URL_PUBLIQUE` ne correspond pas à l'adresse tapée |
| Page de connexion de Lutin au lieu d'Authelia | Authelia n'est pas devant, ou `LUTIN_PROXY_IP` n'est pas le réseau que Lutin voit (`docker network inspect proxy`) |
| Tout marche mais je ne peux pas créer de mission ni supprimer de fichier | ton identifiant n'est pas dans `LUTIN_ADMINS` |
| Réponses saccadées ou tout d'un coup | tampon du proxy (`proxy_buffering off` pour nginx) |
| Réponses très lentes | modèle trop gros pour le processeur ; prends un modèle plus petit et baisse la fenêtre de contexte (Réglages) |
| « Ollama ne répond pas » | `docker compose exec lutin tail /data/ollama.log` |

Pour désinstaller : `docker compose down -v` efface les volumes (conversations comprises), puis `docker rmi ghcr.io/slater-proj/lutin:latest` ; supprime enfin `/opt/lutin`.
