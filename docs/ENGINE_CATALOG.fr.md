# Le catalogue des moteurs

Lutin connaît des serveurs de modèles (LM Studio, vLLM, SGLang, LocalAI, llama-swap…) grâce à un **catalogue** : un fichier de données, jamais du code. Dans Réglages > Moteurs, la carte « Serveur compatible OpenAI » propose ces serveurs d'un clic : l'adresse habituelle se remplit, avec une courte description, les forces, les limites et un lien vers le site.

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

## Ce que le catalogue ne fait pas encore

Les cartes d'Ollama et de llama.cpp (que Lutin installe et pilote) viennent encore du code ; elles passeront au catalogue avec les versions testées et les fichiers à télécharger (0.18.0 et suivantes). La veille automatique des nouvelles versions de moteurs (une demande de fusion à relire, jamais publiée toute seule) viendra aussi plus tard.
