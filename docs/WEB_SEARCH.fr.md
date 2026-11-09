[English](WEB_SEARCH.md) · **Français**

# Recherche web

Avec l'option **Web** cochée, le modèle a deux outils : `web_chercher` (chercher) et `web_lire` (lire une page). Rien n'est envoyé quand la case est décochée ou en mode hors ligne strict ([PRIVACY.fr.md](PRIVACY.fr.md)).

> **Honnêteté.** Toute la chaîne est testée avec de **faux serveurs** (un faux SearXNG, un faux Brave, de fausses pages). **L'image réelle de SearXNG et l'API réelle de Brave n'ont pas été lancées par le projet** : utilise le bouton **Tester la recherche** (Réglages > Recherche web) pour voir ce qui marche chez toi.

## Quel moteur répond

Les moteurs sont essayés **dans cet ordre** ; le premier qui rend des résultats l'emporte, les suivants prennent le relais s'il échoue.

| # | Moteur | Demande | Pourquoi |
|---|---|---|---|
| 1 | **SearXNG** | une instance chez toi (quelques minutes avec Docker, gratuit) | agrège plusieurs moteurs, pas de HTML à décortiquer, **tes requêtes restent sous ton contrôle** |
| 2 | **Brave Search** | une clé d'API personnelle (offre gratuite, brave.com/search/api) | index indépendant, API officielle |
| 3 | **Tavily** | une clé d'API personnelle (offre gratuite, tavily.com) | conçu pour les agents, extraits propres |
| 4 | **Exa** | une clé d'API personnelle (exa.ai, crédit gratuit au départ : vérifie ses conditions) | recherche par le sens, bon pour les questions précises |
| 5 | **Perplexity** (API de recherche) | une clé d'API personnelle (**payante** à l'usage, pas d'offre gratuite connue : inutile si tu ne veux rien payer) | résultats classés d'un grand index |
| 6 | DuckDuckGo | rien | marche tout de suite, mais son HTML peut changer ou limiter les robots |
| 7 | Bing | rien | secours |

Un moteur qui ne rend rien est laissé tranquille 10 minutes ; la même recherche est servie par un cache de 10 minutes. Les résultats sont **nettoyés** : paramètres de suivi (`utm_…`, `fbclid`…) et ancres retirés, doublons supprimés, deux résultats au plus par site (sauf si tu demandes un site).

## Lutin cherche à la place du modèle

Un petit modèle local n'appelle souvent pas l'outil de recherche : il répond de mémoire qu'il « n'a pas d'outils ». Lutin ne dépend donc pas de lui. Avec la case **Web** cochée :

- **Tu demandes de chercher** (« cherche… », « trouve des liens… », « sur internet… ») : Lutin cherche lui-même, lit les premières pages, t'affiche les **sources trouvées** (titre et adresse), et le modèle n'a plus qu'à répondre d'après elles en les citant [1], [2]. Valable pour tous les modèles.
- **Une question qui suppose le web** (« qui est… », « le dernier… », « prix de… », « météo… ») : pareil, pour les petits modèles seulement (10 milliards de paramètres ou moins, ou taille inconnue). Un modèle plus grand décide seul.
- **Tu colles une adresse** : Lutin lit la page et le modèle répond à son sujet.
- **Les actualités** : inchangé (petits modèles).
- Pas déclenché pour les messages qui parlent de code, de fichiers ou d'erreurs, ni pour les messages longs. Si rien n'est trouvé, la boucle habituelle reprend la main.

## Ce que ça coûte (léger exprès)

- **Un seul moteur par recherche** : les moteurs ci-dessus forment un *ordre de repli*, pas quatre recherches à la fois. Si le premier répond, rien d'autre n'est demandé ; s'il est muet, le suivant est essayé **après** lui, jamais en même temps.
- En plus de la réponse du moteur, Lutin lit le **début** des premières pages (3 par défaut, `lire=0` pour s'en passer) : 500 Ko au plus chacune, en parallèle, dans un budget de 12 secondes.
- **La mémoire est bornée** : le cache de pages garde 24 pages et 32 Mo au plus (la plus ancienne part d'abord) ; une page énorme n'y entre pas.
- **Aucun processus de fond, aucune dépendance nouvelle, aucune interrogation périodique** : rien ne tourne entre deux recherches. Seul le bouton **Tester la recherche** interroge tous les moteurs d'un coup, et seulement quand tu cliques.
- Le nettoyage des résultats prend bien moins d'une milliseconde.

## Ce que le modèle peut demander

`web_chercher` : `requete` (mots-clés courts), `nombre` (10 au plus), `lire` (combien de premières pages lire d'un coup), **`periode`** (`jour`, `semaine`, `mois`, `an`), **`site`** (par exemple `docs.python.org`), **`actualites`**. La langue suit celle de l'interface. Chaque réponse se termine par le moteur utilisé, et les résultats portent leur **date** quand le moteur la donne, pour que le modèle cite ses sources.

`web_lire` : `url`, `debut` (suite d'une page longue ; la page est gardée 10 minutes, la suite ne la retélécharge pas), **`liens`** (les liens de la page, pour explorer un site). Il lit les **pages web, les fichiers texte et les PDF** (jusqu'à 15 Mo, même extraction que les pièces jointes), ignore menus et pieds de page quand il y a un vrai contenu, retente une fois après une erreur passagère du serveur, et suit le jeu de caractères annoncé par la page.

## Installer SearXNG (recommandé)

```
SEARXNG_SECRET=$(openssl rand -hex 32) docker compose -f docker-compose.searxng.yml up -d
```

Le fichier [docker-compose.searxng.yml](../docker-compose.searxng.yml) n'écoute que sur `127.0.0.1:8080`, et [docker/searxng/settings.yml](../docker/searxng/settings.yml) active le format **json** (celui que Lutin lit ; sans lui SearXNG répond en HTML et Lutin te dit de l'activer). Ensuite, **depuis cette machine** : Réglages > Recherche web > adresse de SearXNG = `http://127.0.0.1:8080` (`http://searxng:8080` si Lutin est dans le même réseau Docker), Enregistrer, **Tester la recherche**.

**Sécurité.** SearXNG vit en général sur ton réseau, et Lutin **refuse normalement toute adresse locale** (une page piégée ne doit pas lire tes services internes). L'adresse que tu règles est la **seule exception**, seulement pour chercher (jamais pour lire des pages), et elle ne se règle que **depuis cette machine**, pas depuis un appareil appairé.

## Brave Search

Crée une clé (offre gratuite) sur brave.com/search/api et colle-la dans Réglages > Recherche web > Brave Search. Elle est rangée dans `recherche.json` à côté de tes données, lisible par toi seul (là où le système le permet), et **jamais renvoyée à la page** (seuls ses quatre derniers caractères le sont). Réglable depuis cette machine seulement.

## Tavily, Exa, Perplexity (clés)

Colle une clé dans Réglages > Recherche web ; chacune est gardée dans `recherche.json` comme celle de Brave, jamais renvoyée à la page. **Seuls les résultats (titre, adresse, extrait) servent : la réponse que ces services peuvent rédiger eux-mêmes est ignorée**, donc tout repasse par le modèle de Lutin, qui lit, compare et cite. **Chaque recherche part chez ce service** (elle n'est plus privée, contrairement à un SearXNG chez toi) et le mode hors ligne les coupe. Perplexity est utilisé par son API de *recherche* (résultats classés), pas par ses modèles qui répondent. Les formats de requête sont écrits d'après la documentation de chacun et **testés avec de faux serveurs seulement**, pas avec une vraie clé : si l'un change, le bouton « Tester la recherche » montre quel moteur échoue.

## Ce qu'elle ne sait pas faire

- **Les pages construites par JavaScript** (Reddit, beaucoup d'applications web) paraissent vides. Lutin lit ce que le serveur annonce (titre, description) et fait demander au modèle de **copier-coller le texte** ou d'**enregistrer la page et la joindre**. Voir [FEATURES.fr.md](FEATURES.fr.md).
- **Les sites qui refusent les lectures automatiques** ne sont pas contournés, pas plus que les pages derrière une connexion ou un abonnement.
- Les résultats dépendent des moteurs : un moteur qui limite est écarté, un SearXNG arrêté laisse la main au suivant (visible dans le test).
