# Publications : versions, candidates, images

Tout est automatique ; personne ne fixe un numéro de version à la main.

## Le principe

| Ce qui arrive | Ce qui est produit |
|---|---|
| **Fusion (ou envoi) dans `main`** | **Une publication** : version calculée, **étiquette** `vX.Y.Z`, **GitHub Release** (roue, archive source, `SHA256SUMS.txt`, notes générées), image Docker `:X.Y.Z` et `:latest`. |
| **Envoi sur une autre branche** | **Une candidate (rc), sans étiquette ni Release** : roue et archive jointes à l'exécution du workflow (30 jours), image Docker `:rc-<branche>`. |
| **Pull request** | Les tests seulement (`ci.yml`). |

Les tests (Windows et Linux, Python 3.10 à 3.13), le contrôle du paquet, la construction de l'image Docker et la recherche de secrets passent **avant** toute publication. Si un test échoue, rien n'est publié.

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

## Utiliser une candidate

```bash
# image Docker de la branche « ma-branche »
docker pull ghcr.io/slater-proj/lutin:rc-ma-branche

# ou la roue : onglet Actions > l'exécution de la branche > Artifacts > lutin-X.Y.ZrcN+…
pip install lutin-0.5.0rc17+ma.branche-py3-none-any.whl
```

## Mise en place sur GitHub (une seule fois)

1. **Réglages > Actions > Général** : « Workflow permissions » = *Read and write permissions* (nécessaire pour créer les étiquettes et publier l'image).
2. **Réglages > Branches** : protéger `main` (exiger une pull request et le succès des vérifications `ci / …`). Sans protection, un envoi direct sur `main` publie aussi.
3. **Packages** : après la première image, rendre le paquet `lutin` public (Package settings > Change visibility) pour que `docker pull` marche sans connexion.
4. Facultatif : **Security > Code security** : activer le signalement privé de failles et Dependabot.

## Réparer

| Problème | Que faire |
|---|---|
| Une publication est mauvaise | La supprimer (Release + étiquette), corriger, fusionner : une nouvelle version sort. Ne réutilise jamais un numéro. |
| Le calcul donne une version inattendue | `python tools/prochaine_version.py --mode release` en local (il ne crée rien) ; ajuste le titre du commit. |
| L'image Docker n'a pas été publiée | Actions > l'exécution > le job « image Docker » ; vérifier la permission *packages: write* et la visibilité du paquet. |
