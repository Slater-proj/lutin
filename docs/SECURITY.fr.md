[English](SECURITY.md) · **Français**

# Sécurité

Lutin peut lire des fichiers et lancer des commandes sur ta machine, à la demande d'un modèle de langage. C'est utile, et c'est exactement ce qu'il ne faut pas laisser à n'importe qui. Cette page explique ce qui protège, niveau par niveau, et ce qui reste ta responsabilité.

## Règles valables partout

- **Ollama (port 11434) n'est jamais exposé par Lutin.** Il reste sur `127.0.0.1`. Ne le change pas.
- Chaque modification de fichier et chaque commande demandent ton **accord**, sauf si tu actives les cases « accord automatique ».
- Lutin ne lit et ne modifie que le **dossier de travail** choisi à l'installation.
- Le jeton écrit dans la page protège contre les requêtes venues d'**autres sites web** (CSRF). Le nom d'hôte (`Host`) et l'origine (`Origin`) sont vérifiés : un site malveillant ne peut pas faire parler ton navigateur à Lutin (« DNS rebinding »).
- Le contenu lu sur le web est considéré comme **non fiable** : après une lecture web, l'accord automatique est suspendu pour la suite de la demande.

## Niveau 1 : cette machine seulement (défaut)

Le serveur écoute sur `127.0.0.1`. Personne d'autre ne peut ouvrir de connexion. Aucun mot de passe.

## Niveau 2 : réseau local

- Le serveur écoute sur l'adresse du réseau local.
- **Appairage** : `lutin pin` (ou l'affichage au démarrage) donne un code à 6 chiffres valable 10 minutes, utilisable une fois. Cinq erreurs invalident le code et bloquent les essais 5 minutes. Les tentatives sont aussi limitées par adresse.
- Chaque appareil reçoit une session (cookie `HttpOnly`, `SameSite=Strict`, 30 jours). `lutin appareils` les liste, `lutin appareils revoquer [id]` les coupe. Seules les **empreintes** des sessions sont stockées.
- Le nom d'hôte demandé doit être une adresse privée ou un nom local.
- **Les accords automatiques sont désactivés** pour tous les appareils appairés, même si le fichier de réglages les active. Une seule exception : le **navigateur de la machine où tourne Lutin** garde ses cases « Accord auto » et « Commandes auto » (un appareil appairé ne peut ni les cocher ni les décocher). Au niveau « proxy », jamais. Quand les cases sont cochées mais sans effet, la page et la conversation le disent.
- Pare-feu : à ouvrir **uniquement** pour ton réseau privé. Sous Windows, une règle limitée au profil « Privé » et à ton sous-réseau ; ne l'ouvre jamais au profil « Public ».
- HTTP simple sur ton réseau : le PIN et la session circulent en clair sur ton Wi-Fi. Pour un réseau partagé ou peu sûr, utilise le niveau 3 avec HTTPS.

> Toute personne qui connaît un PIN valide sur ton réseau peut demander à Lutin de lire les fichiers du dossier de travail. Ne mets pas de secrets dans ce dossier.

## Niveau 3 : derrière un proxy inverse

Lutin n'est pas exposé : c'est le proxy (Authelia, Authentik, oauth2-proxy…) qui l'est, et qui authentifie.

À l'installation, tu donnes :

- l'**adresse publique** (`https://lutin.exemple.fr`), qui sert à valider `Host` et `Origin` ;
- l'**adresse du proxy de confiance**, c'est-à-dire celle que Lutin voit quand le proxy lui parle.

Lutin n'accepte l'identité (`Remote-User` par défaut) **que si la connexion vient de l'adresse du proxy déclarée**. N'importe qui peut écrire `Remote-User: admin` dans une requête : si elle ne vient pas du proxy, l'en-tête est ignoré (testé).

> **Avertissement.** Exposer à Internet un assistant capable de lire des fichiers et de lancer des commandes est risqué. Ne le fais que derrière une authentification forte (idéalement avec second facteur), un HTTPS valide, et garde les accords manuels (ils sont imposés à ce niveau). Une faille dans ton proxy, ou une mauvaise configuration, ouvre ton dossier de travail.

### Ce que le proxy doit faire

1. **Authentifier** avant de transmettre.
2. **Écraser** l'en-tête d'identité (`Remote-User`) avec la valeur issue de l'authentification, jamais celle du client.
3. **Transmettre l'en-tête `Host` d'origine** (sinon `Host` et `Origin` ne correspondent plus et les écritures sont refusées).
4. Ne **pas mettre les réponses en mémoire tampon** (elles arrivent en continu) et accepter de **longues durées** (une réponse peut durer plusieurs minutes).

### Exemples (à adapter, non testés ici)

**Nginx avec Authelia** (le fragment `authelia-authrequest.conf` est celui de la documentation d'Authelia et définit `$user`) :

```nginx
server {
    listen 443 ssl;
    server_name lutin.exemple.fr;
    # certificats ...
    location / {
        include /config/nginx/authelia-authrequest.conf;
        proxy_pass http://127.0.0.1:8777;
        proxy_set_header Host $host;
        proxy_set_header Remote-User $user;      # remplace tout en-tête envoyé par le client
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

**Caddy** :

```caddyfile
lutin.exemple.fr {
    forward_auth authelia:9091 {
        uri /api/authz/forward-auth
        copy_headers Remote-User Remote-Groups
    }
    reverse_proxy 127.0.0.1:8777 {
        flush_interval -1
    }
}
```

**Traefik** : middleware `forwardAuth` vers Authelia avec `authResponseHeaders: [Remote-User]`, puis le service vers `http://127.0.0.1:8777`.

Dans tous les cas, déclare à Lutin l'adresse que le proxy utilise pour lui parler : `127.0.0.1` si le proxy tourne sur la même machine, l'adresse du conteneur ou de la machine du proxy sinon.

## Addons

Les addons facultatifs (Telegram, courriel, X, ComfyUI, travail de fond) sont **désactivés par défaut** et ne se gèrent que depuis cette machine (comme le niveau d'accès). Leurs règles :

- Un message venu de l'extérieur (Telegram d'une autre personne, un courriel, une mention sur X) est **une donnée, jamais un ordre** : le modèle qui y répond n'a **aucun outil** et tourne en lecture seule. Seul ton propre chat Telegram appairé peut envoyer des demandes, et même celles-ci tournent en lecture seule.
- Rien ne part sans toi par défaut : les réponses sont des **brouillons que tu valides** ; le mode automatique est plafonné (20 par jour pour le courriel et les tiers Telegram, 10 pour X) et les publications sur X demandent ton clic (25 par jour au plus).
- Un addon ne peut joindre que les sites déclarés par son manifeste livré ; un flux corrigé (même proposé par le modèle après lecture d'une page de documentation) est validé contre cette liste et appliqué seulement après ton acceptation de la différence.
- Les identifiants (jetons, mots de passe, clés) sont rangés dans un fichier à part, jamais renvoyés à la page, masqués dans les messages d'erreur et jamais écrits dans le journal. Utilise des mots de passe d'application, pas celui de ton compte.
- Le mode hors ligne strict les bloque tous (seul ComfyUI sur cette machine reste joignable).

## Mode hors ligne strict

`lutin hors-ligne oui` (ou la case « Hors ligne » de l'interface, ou `LUTIN_HORS_LIGNE=1`) : **plus aucune connexion vers Internet**.

- Autorisés : cette machine, **Ollama** (l'adresse `OLLAMA_URL`), et les extensions que tu as déclarées (`LUTIN_OUTIL_URL`, `COMFY_URL`).
- Bloqués : recherche et lecture web (les outils ne sont même plus proposés au modèle), catalogue en ligne, mises à jour de modèles et de Lutin, téléchargement de modèles (Ollama les télécharge lui-même : l'action est refusée).
- Un seul endroit du code décide (`lutin/horsligne.py`) et un test surveille les **connexions réelles** (`tests/test_hors_ligne.py`) : aucune vers autre chose que cette machine.
- Il se **coupe** seulement depuis cette machine (pas à distance, même avec une session valide).
- Limites honnêtes : Lutin ne contrôle pas Ollama lui-même ni le reste de ton système. Pour une garantie totale, coupe aussi le réseau du conteneur ou de la machine.

## Dossiers de travail

Lutin ne lit et ne modifie que **le dossier de travail** de la conversation. Plusieurs dossiers sont possibles ; un seul est actif à la fois (si une réponse travaille dans un dossier, on ne peut pas en changer avant sa fin, ni en lancer une dans un autre).

- Un dossier doit exister, ne pas être la racine d'un disque, ni **contenir ou être dans les dossiers de Lutin** (configuration, données, mémoire, cache).
- **Ajouter ou retirer** un dossier ne se fait que depuis cette machine : au niveau « machine seulement », ou avec `lutin travaux`. Un appareil appairé (niveau réseau) ou une identité de proxy peut **choisir** un dossier déjà déclaré, jamais en ajouter : sinon un accès à distance pourrait déclarer `/` ou `C:\`.

## Ce que seule cette machine peut changer

Les dossiers de travail, la reprise des données d'un autre assistant ou d'un projet Claude, la restauration d'une sauvegarde, les **tâches planifiées** et le niveau d'accès lui-même se gèrent **depuis cette machine seulement** : au niveau « machine seulement », ou, au niveau réseau local, depuis le navigateur **de cette machine** (adresse de boucle locale, sans en-tête de proxy). Un appareil appairé et une identité de proxy peuvent **utiliser** Lutin mais jamais changer cela : sinon un accès à distance pourrait ouvrir la machine plus largement, planifier du travail ou déclarer `/` comme dossier de travail. L'onglet **Accès** est le même partout mais ne propose ces changements que là où ils sont permis.

## Journal des actions

Chaque fichier modifié, chaque commande lancée, chaque module installé est inscrit dans `journal-actions.jsonl` : **quand, quel outil, sur quelle cible, dans quel dossier, avec quel accord (manuel, automatique, aucun pour une lecture simple), pour qui** (console, local, nom donné par le proxy, appareil) et l'issue (ok, refusé, erreur, arrêté). Jamais le contenu des fichiers ni la sortie des commandes. Visible avec `lutin journal` ou le menu « ⋯ > Journal des actions ». Il tourne à 5 Mo.

## Changer de niveau

`lutin setup --niveau local|reseau|proxy` (avec `--url` et `--proxy-ip` pour le niveau 3). Repasser à un niveau plus fermé est toujours possible ; pour en ouvrir un plus large, lance la commande sur la machine elle-même.

## Docker

Dans le conteneur, « cette machine seulement » n'existe pas (le port est publié par Docker) : le niveau est `reseau` (code PIN) ou `proxy`. Dans l'image complète, Ollama n'écoute que sur `127.0.0.1` du conteneur et son port n'est jamais publié. Voir [DOCKER.fr.md](DOCKER.fr.md).

## Signaler une faille

Voir [../SECURITY.md](../SECURITY.md).
