# Lutin

Un assistant IA qui tourne **sur ta machine**, sans compte ni abonnement. Il regarde ta configuration (carte graphique, mémoire, disques), te propose les modèles qui y tiennent, les installe, et s'utilise dans le **navigateur** ou dans le **terminal**, comme un assistant de code (il lit et modifie les fichiers d'un dossier que tu choisis, avec ton accord).

> **État : version 0.1, en développement.** Testé sur Windows avec un faux Ollama ; pas encore sur machine AMD / Intel / Mac ni sur un vrai Linux. Les notes du catalogue de modèles sont un point de départ, pas des mesures (voir [docs/DECISIONS.md](docs/DECISIONS.md)).

## Installation

Il faut seulement Python 3.10 ou plus (le script de Windows peut l'installer pour toi). Rien d'autre : Lutin n'a aucune dépendance.

**Windows (PowerShell)**
```powershell
$env:LUTIN_SOURCE = "git+https://github.com/<proprietaire>/lutin"
irm https://raw.githubusercontent.com/<proprietaire>/lutin/main/installateur/install.ps1 | iex
```

**Linux / macOS**
```bash
export LUTIN_SOURCE="git+https://github.com/<proprietaire>/lutin"
curl -fsSL https://raw.githubusercontent.com/<proprietaire>/lutin/main/installateur/install.sh | bash
```

Pas d'administrateur nécessaire. **Relancer le script est sans risque** : si Lutin est déjà installé à la même version, il le dit et ne change rien ; si une version plus récente existe, il met à jour (tes réglages, conversations et modèles ne sont pas touchés).

Le script crée un environnement privé, ajoute la commande `lutin`, puis lance l'**installation guidée** (sans effet si Lutin est déjà configuré : `lutin setup --reconfigurer` pour la refaire, sans retélécharger ce qui est déjà là) : 

1. analyse de ta machine ;
2. **qui peut utiliser Lutin** : cette machine seulement, ton réseau local (code PIN), ou derrière un proxy (Authelia…) ;
3. où ranger le dossier de travail et les modèles (les modèles pèsent plusieurs Go : tu choisis le disque) ;
4. les modèles conseillés, chacun avec une phrase d'explication ;
5. installation d'Ollama si besoin (sur Windows, la signature de l'installateur est vérifiée), puis téléchargement des modèles choisis.

## Utilisation

| Commande | Rôle |
|---|---|
| `lutin` | démarre et ouvre l'interface dans le navigateur ; relance le serveur tout seul s'il s'arrête sur une erreur (`serve --sans-superviseur` pour l'éviter) |
| `lutin update` | met à jour Lutin (avec la source mémorisée à l'installation) et cherche des mises à jour de modèles ; ne change rien si tout est à jour |
| `lutin chat` | discuter dans le terminal (`/aide` pour les commandes) |
| `lutin chat "ta question"` | une question, une réponse |
| `lutin modeles` | modèles conseillés pour ta machine ; `lister`, `installer <id>`, `supprimer <id>`, `maj` |
| `lutin pin` | code PIN pour connecter un téléphone (niveau réseau) |
| `lutin appareils` | appareils connectés ; `revoquer [id]` |
| `lutin securite` | niveau d'accès actuel |
| `lutin doctor` | diagnostic à coller dans un rapport de problème (sans contenu personnel) |

## Les modèles

Lutin propose cinq rôles et choisit pour chacun **le mieux noté qui tient dans ta mémoire** :

| Rôle | Pour |
|---|---|
| Polyvalent | tout faire au quotidien (coché par défaut) |
| Rapide | réponses presque immédiates |
| Créatif | écriture, histoires, idées |
| Code | programmation et scripts |
| Images | comprendre des images, captures et documents |

Au démarrage, une vérification discrète (au plus une fois par jour, jamais bloquante, désactivable) cherche des **mises à jour** de tes modèles et de **meilleurs modèles** pour ta machine, et te les *propose*. Rien n'est téléchargé sans ton accord. À tout moment, l'onglet Modèles a deux boutons : **Chercher les mises à jour** et **Chercher de nouveaux modèles**. Détails : [docs/MODELES.md](docs/MODELES.md).

Une option « Afficher les modèles avancés » (onglet Modèles, ou `lutin modeles lister --avance`) montre des modèles modifiés par la communauté pour ne plus refuser de demandes. Ils ne sont jamais choisis automatiquement et s'affichent avec un avertissement.

## Sécurité

| Niveau | Qui peut accéder | Protection |
|---|---|---|
| 1. Cette machine | toi, sur cet ordinateur | écoute sur `127.0.0.1` seulement ; jeton ; vérification du nom d'hôte et de l'origine |
| 2. Réseau local | tes appareils appairés | code PIN à 6 chiffres (10 min, 5 essais), session par appareil révocable |
| 3. Proxy | ce que ton proxy laisse passer | l'identité n'est crue que si elle vient de l'adresse du proxy déclaré |

Aux niveaux 2 et 3, **les accords automatiques (écriture, commandes) sont désactivés**. Détails, avertissements et exemples de proxy : [docs/SECURITE.md](docs/SECURITE.md).

## Où sont mes fichiers ?

| Quoi | Windows | Linux |
|---|---|---|
| Configuration, mémoire, conversations | `%APPDATA%\Lutin` | `~/.config/lutin`, `~/.local/share/lutin` |
| Cache (supprimable) | `%LOCALAPPDATA%\Lutin\cache` | `~/.cache/lutin` |
| Dossier de travail | celui que tu as choisi (`~/Lutin` par défaut) | idem |

`LUTIN_HOME=<dossier>` range tout sous un seul dossier (mode portable).

Le dossier de travail peut contenir un dossier `skills/` (fiches Markdown que tu écris : Lutin en voit la liste et les lit à la demande) et un dossier `docs/` (interrogeable avec l'outil « rappeler »).

## Développement

```bash
python tests/lancer_tests.py     # tous les tests, un processus par fichier
python -m pip install ruff && python -m ruff check src tests tools
python tools/verifier_catalogue.py   # les modèles du catalogue existent-ils encore ? (réseau)
```

Voir [CONTRIBUER.md](CONTRIBUER.md).

## Licence

MIT. Lutin n'embarque aucun modèle : chaque modèle garde sa propre licence, affichée dans le catalogue.
