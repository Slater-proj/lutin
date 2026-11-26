[English](PUBLISHING.md) · **Français**

# Publications : versions, candidates, images

Tout est automatique ; personne ne fixe un numéro de version à la main.

## Le principe

| Ce qui arrive | Ce qui est produit |
|---|---|
| **Fusion (ou envoi) dans `main`** | **Une publication** : version calculée, **étiquette** `vX.Y.Z`, **GitHub Release** (roue, archive source, `SHA256SUMS.txt`, notes générées), images Docker `:X.Y.Z` et `:latest` (complète), `:X.Y.Z-slim` et `:slim` (légère). |
| **Envoi sur une autre branche** | **Une candidate (rc), sans étiquette ni Release** : roue, archive et installateur Windows joints à l'exécution du workflow (30 jours), images Docker `:rc-<branche>` et `:rc-<branche>-slim`. |
| **Le bouton** (Actions > release > Run workflow, sur une branche) | **Une pré-version de cette branche** : étiquette `vX.Y.ZaN`, GitHub Release marquée *pre-release*, image Docker `:next`. Voir « Le bouton » plus bas. |
| **Pull request** | Les tests seulement (`ci.yml`). |

Les tests (Windows et Linux, Python 3.10 à 3.13), le contrôle du paquet, la construction de l'image Docker et la recherche de secrets passent **avant** toute publication. Si un test échoue, rien n'est publié.

**Construit une fois, testé, publié tel quel.** La version est calculée en premier ; `ci.yml` construit l'interface, la roue, l'archive source et l'installateur Windows une seule fois, avec cette version, et les teste. Ce qui est publié, ce sont ces fichiers-là : rien n'est reconstruit après les tests. La page de chaque exécution dit en haut quelle version elle fabrique et où la prendre.

## Comment le numéro est choisi

`tools/prochaine_version.py` lit l'historique depuis la dernière étiquette `vX.Y.Z` et regarde le titre des commits (forme `type: description`) :

| Dans les commits | Effet | Exemple |
|---|---|---|
| `feat!:` ou `fix!:`, ou « BREAKING CHANGE » dans le message | **majeure** (tant que la majeure est 0 : mineure) | 1.4.2 → 2.0.0 |
| `feat:` | **mineure** | 1.4.2 → 1.5.0 |
| tout le reste (`fix:`, `docs:`, `chore:`, titre libre…) | **correctif** | 1.4.2 → 1.4.3 |

La première publication est **0.1.0**. Chaque fusion dans `main` produit une publication, même un simple correctif de documentation. Si le commit est déjà étiqueté (relance d'un workflow), il n'y a rien à publier.

**Candidates** : la version est `X.Y.ZrcN+branche` (par exemple `0.5.0rc17+ma.branche`) où `N` est le numéro d'exécution du workflow ; c'est une vraie version PEP 440, `pip` l'accepte, et elle est **toujours plus petite** que la version stable qui suivra.

Conseil : pour que la version suive ce que tu as fait, fusionne par **squash** avec un titre conventionnel (`feat: dossiers de travail multiples`).

## Canal de publication : des pré-versions pendant la migration vers la 1.0

Le fichier `tools/release_channel.json`, quand le dépôt en a un, décide de ce que `main` publie ([ADR 0004](adr/0004-release-cadence.md), en anglais) :

| Fichier | Ce que `main` publie |
|---|---|
| aucun (la ligne 0.x) | une version stable par fusion, comme décrit plus haut |
| `{"channel": "alpha", "target": "1.0.0"}` | des **pré-versions** `1.0.0a1`, `1.0.0a2`… (`beta` : `b1`…, `rc` : `rc1`…) : étiquette `v1.0.0a1`, GitHub Release marquée *pre-release*, images Docker `:1.0.0a1` et `:next` — **jamais** `:latest` |
| `{"channel": "stable", "target": "1.0.0"}` | la version stable `1.0.0`, puis le calcul habituel |

Une pré-version n'est jamais « la dernière version » pour GitHub : les scripts d'installation, `lutin update` et l'annonce de mise à jour dans la page demandent tous la dernière version, donc aucun ne la propose. Pour en essayer une, il faut la nommer : `docker pull ghcr.io/slater-proj/lutin:next`, ou la roue de cette Release.

Sur une branche qui porte une cible, la candidate s'appelle `1.0.0.devN+branche` (toujours plus petite que `1.0.0a1`). Un fichier illisible ou incohérent arrête le calcul : rien n'est publié, plutôt qu'une version stable par accident.

Après une version publiée, monte `target` au-dessus de la dernière version stable (la 1.0.1 est sortie : le fichier dit `alpha` / `1.0.2`, donc chaque fusion dans `main` publie `1.0.2a1`, `1.0.2a2`…). Si la cible est déjà publiée, la publication s'arrête avec « la cible … est déjà publiée » : change le fichier. Pour sortir la version stable à ton heure, mets `{"channel": "stable", "target": "1.0.2"}`.

## Utiliser une candidate

```bash
# image Docker de la branche « ma-branche »
docker pull ghcr.io/slater-proj/lutin:rc-ma-branche

# ou la roue : onglet Actions > l'exécution de la branche > Artifacts > lutin-X.Y.ZrcN+…
pip install lutin-0.5.0rc17+ma.branche-py3-none-any.whl
```

L'installateur Windows de la candidate est au même endroit : **Artifacts > `installateur-…`** (GitHub demande d'être connecté pour télécharger un artefact, et le donne en zip).

## Le bouton : une version de test d'une branche que tout le monde peut télécharger

Une candidate est construite à chaque envoi, mais sans étiquette ni Release, et ses fichiers demandent un compte GitHub. Pour donner à quelqu'un une vraie version de test d'une branche de fonctionnalité (alpha/beta/rc selon `tools/release_channel.json`) :

1. ouvrir **[Actions > release](https://github.com/Slater-proj/lutin/actions/workflows/release.yml)** ;
2. cliquer **Run workflow**, choisir la branche ;
3. cliquer le **Run workflow** vert. Il n'y a rien d'autre à remplir.

La version est calculée (`1.0.0a1`, puis `a2`…), tout est construit avec elle et testé, puis l'étiquette `vX.Y.ZaN`, une Release GitHub marquée *pre-release* (roue, archive, installateur Windows, sommes de contrôle) et les images Docker `:X.Y.ZaN` et `:next` sont publiées ; jamais `:latest`, et les installateurs et l'annonce de mise à jour l'ignorent. Le lien vers la Release est en haut de la page de l'exécution. Compter vingt à trente minutes, surtout les tests.

Refusé hors de `main` si le canal dit « stable ». Seul ce bouton le fait : un envoi ne publie jamais depuis une branche, et un envoi sur la branche n'annule pas une publication en cours.

Depuis un terminal, avec [GitHub CLI](https://cli.github.com/) : `gh workflow run release.yml --ref ma-branche`.

## Mise en place sur GitHub (une seule fois)

1. **Réglages > Actions > Général** : « Workflow permissions » = *Read and write permissions* (nécessaire pour créer les étiquettes et publier l'image).
2. **Réglages > Branches** : protéger `main` (exiger une pull request et le succès de la vérification `tests / ci (résultat)`, qui rassemble toutes les autres). Sans protection, un envoi direct sur `main` publie aussi.
   Exiger ce nom exact : c'est l'exécution de `release.yml` à chaque envoi, celle qui teste. Le `ci (résultat)` seul d'une pull request venue de ce dépôt est **sauté** exprès (l'envoi a déjà lancé les tests), et GitHub compte une vérification exigée sautée comme une réussite. Une pull request venue d'un fork n'a que le nom seul : envoyer sa branche dans ce dépôt pour avoir la vraie vérification.
3. **Packages** : après la première image, rendre le paquet `lutin` public (Package settings > Change visibility) pour que `docker pull` marche sans connexion.
4. Facultatif : **Security > Code security** : activer le signalement privé de failles et Dependabot.

## L'installateur Windows n'est pas signé

La signature a été étudiée (SignPath Foundation, gratuite pour l'open source) puis abandonnée pour l'instant : trop de mise en place pour le public actuel. Windows SmartScreen peut avertir au téléchargement du `.exe` (« Informations complémentaires > Exécuter quand même ») ; la somme de contrôle est dans `SHA256SUMS.txt`. Le script `install.ps1` est une alternative qui ne déclenche pas l'avertissement.

## Réparer

| Problème | Que faire |
|---|---|
| Une publication est mauvaise | La supprimer (Release + étiquette), corriger, fusionner : une nouvelle version sort. Ne réutilise jamais un numéro. |
| Le calcul donne une version inattendue | `python tools/prochaine_version.py --mode release` en local (il ne crée rien) ; ajuste le titre du commit. |
| L'image Docker n'a pas été publiée | Actions > l'exécution > le job « image Docker » ; vérifier la permission *packages: write* et la visibilité du paquet. |
