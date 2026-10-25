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
- **Les accords automatiques sont désactivés**, même si le fichier de réglages les active.
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

## Changer de niveau

`lutin setup --niveau local|reseau|proxy` (avec `--url` et `--proxy-ip` pour le niveau 3). Repasser à un niveau plus fermé est toujours possible ; pour en ouvrir un plus large, lance la commande sur la machine elle-même.

## Signaler une faille

Voir [../SECURITY.md](../SECURITY.md).
