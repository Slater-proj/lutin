# Le catalogue des moteurs

(English version: [ENGINE_CATALOG.md](ENGINE_CATALOG.md).)

Lutin connaît des serveurs de modèles (LM Studio, Colibri, Strata…) grâce à un **catalogue** : un fichier de données, jamais du code. Dans Réglages > Moteurs, la carte « Serveur compatible OpenAI » propose ces serveurs d'un clic : l'adresse habituelle se remplit, avec une courte description, les forces, les limites et un lien vers le site.

Un moteur peut porter `"experimental": true` : la page l'étiquette « expérimental », le range en dernier et ne le préselectionne ni ne le recommande jamais (voir [EXPERIMENTAL_ENGINES.fr.md](EXPERIMENTAL_ENGINES.fr.md)).

## Pourquoi c'est signé

Le catalogue peut être mis à jour en ligne sans nouvelle version de Lutin. Pour que personne ne puisse y glisser une adresse piégée, il est **signé** (Ed25519, RFC 8032) :

- Lutin embarque **deux clés publiques** (`2026a`, `2026b`) : une seule sert, la seconde permet de changer de clé sans casser les installations existantes.
- La vérification est écrite en Python pur (`src/lutin/ed25519.py`, environ 6 ms), sans dépendance, et testée avec les vecteurs du RFC 8032.
- Un catalogue **modifié d'une virgule**, signé par une autre clé, ou qui ne respecte pas le schéma est **refusé**. Le schéma est strict : un champ inconnu est refusé, les adresses doivent être en `http(s)`, les sites en `https`.
- Aucun code distant n'est exécuté : le catalogue ne contient que des textes et des adresses.

## D'où vient le catalogue

1. La copie **livrée avec Lutin** (`src/lutin/data/moteurs.json`) : toujours valide, elle suffit hors ligne.
2. Une copie **récupérée en ligne** (au plus une fois par semaine, en arrière-plan, seulement si les mises à jour ne sont pas désactivées et hors mode hors ligne) : elle n'est gardée que si elle est bien signée, valide et plus récente. Réglage `catalogue_moteurs_url` dans la configuration pour changer d'adresse (vide : pas de lecture en ligne).

## Format

```json
{
  "catalogue": { "version": 1, "date": "2026-11-06", "moteurs": [ { "id": "lmstudio", "nom": "LM Studio", "genre": "openai",
      "adresse_defaut": "http://127.0.0.1:1234/v1", "site": "https://lmstudio.ai", "plateformes": ["windows", "linux", "macos"],
      "description": { "fr": "…", "en": "…" }, "points_forts": [ { "fr": "…", "en": "…" } ], "points_faibles": [ … ] } ] },
  "cle": "2026a",
  "signature": "<base 64>"
}
```

La signature porte sur le texte JSON trié et compact de `catalogue` (voir `catalogue_moteurs.canonique`). Champs : `id` (minuscules, chiffres, `-` et `_`, jamais `ollama`, `llamacpp` ou `openai`), `nom`, `genre` (seul `openai` existe), `description` obligatoires ; `adresse_defaut`, `cle_requise`, `points_forts`, `points_faibles`, `plateformes`, `site`, `remarque` facultatifs. Les textes sont une chaîne ou `{ "fr": …, "en": … }` (le français est obligatoire).

## Signer (mainteneur)

Les clés privées (graines de 32 octets en hexadécimal) restent **hors du dépôt**, par défaut dans `~/.lutin-signature/cle-a.seed` et `cle-b.seed`. Sauvegarde-les ailleurs : sans elles, plus de mise à jour en ligne du catalogue.

```
# 1. modifier tools/moteurs.source.json (et augmenter "version" et "date")
python tools/signer_catalogue_moteurs.py            # signe -> src/lutin/data/moteurs.json
python tools/signer_catalogue_moteurs.py --verifier # vérifie le fichier livré
```

Un test échoue si la source et le fichier livré ne correspondent pas : on ne peut pas oublier de re-signer.

**Changer de clé** : signer avec `--cle 2026b`, publier ; quand toutes les installations ont cette version, remplacer la clé `2026a` par une nouvelle dans `CLES_PUBLIQUES` à la version suivante.

**Perte ou fuite de la clé privée** : retirer la clé concernée de `CLES_PUBLIQUES` dans une nouvelle version de Lutin (les installations à jour refusent alors ses signatures) et signer avec l'autre.

## Moteurs gérés par Lutin et veille des versions

Les cartes d'**Ollama** et de **llama.cpp** (que Lutin installe et pilote) viennent aussi du catalogue : description, forces, faiblesses, site et `version_testee` (la version essayée avec Lutin, quand elle est connue). Leur entrée a `"type": "gere"` ; le code qui les installe et les démarre reste dans Lutin. Si le catalogue est illisible ou ne contient pas le moteur, la page garde les textes écrits dans le code.

Champs en plus pour les moteurs : `depot` (propriétaire/nom sur GitHub, pour la veille), `etiquette` (expression régulière des étiquettes de version, par exemple `^b[0-9]+$` pour llama.cpp), `version_testee`.

**Veille hebdomadaire** : `.github/workflows/veille.yml` lance `tools/veille_moteurs.py`, qui compare la dernière version publiée de chaque moteur à `tools/veille_moteurs.json`. S'il y a du neuf, le workflow ouvre une **demande de fusion** à relire. Il ne teste rien, ne signe rien (la clé n'est pas sur GitHub), ne fusionne rien et ne publie rien : une personne lit les notes de publication, met à jour `tools/moteurs.source.json` (`version_testee`, notes), relance `tools/signer_catalogue_moteurs.py`, puis fusionne. Une panne réseau n'est jamais prise pour une nouvelle version.
