[English](ROLLBACK.md) · **Français**

# Mettre à jour sans risque, et revenir en arrière

## Ce que Lutin fait pour toi

- **Avant toute mise à jour** (`lutin update`, ou le bouton de la page) Lutin sauvegarde tes données (réglages, conversations, mémoire, journal des actions) dans un `.zip` et garde les **trois dernières**. Si cette sauvegarde échoue (disque plein…), tu en es prévenu et la mise à jour continue.
- **Si la mise à jour échoue** (pas de réseau, erreur de pip), ta version actuelle reste en place : Lutin ne laisse rien d'installé à moitié.
- **Un fichier de données abîmé ou modifié à la main** (coupé par une panne de courant, un JSON qui n'est plus un objet…) n'arrête pas Lutin : il reprend les valeurs par défaut pour ce fichier au lieu de planter. Restaure une sauvegarde pour retrouver tes réglages.

## Où sont les sauvegardes automatiques

| Système | Dossier |
|---|---|
| Windows | `%LOCALAPPDATA%\Lutin\cache\avant-mise-a-jour\` |
| Linux | `~/.cache/lutin/avant-mise-a-jour/` |
| macOS | `~/Library/Caches/Lutin/avant-mise-a-jour/` |

Le nom du fichier dit de quelle version il vient : `lutin-0.22.0-20261107-101500.zip`.

## Revenir à une version précédente

1. Arrête Lutin (ferme son serveur, ou `Ctrl+C` dans sa fenêtre).
2. Réinstalle la version publiée voulue :

   ```
   lutin update --revenir-a 0.22.0
   ```

   Cela réinstalle cette publication depuis GitHub (seul un numéro `X.Y.Z` simple est accepté), après avoir de nouveau sauvegardé tes données. Cela marche pour une installation faite par le script d'installation (source GitHub) ; pour un `pip install` manuel d'un fichier, installe toi-même la roue voulue avec `python -m pip install <fichier>.whl`.
3. Si la version précédente ne comprend plus tes données (rare : les fichiers ne font que gagner des champs), remets tes données :

   ```
   lutin restaurer <sauvegarde>.zip
   ```

   Lutin garde d'abord l'état actuel dans une archive « avant-restauration ».
4. Relance Lutin.

> Un `lutin update` normal ne **revient jamais** en arrière : il n'installe qu'une publication strictement plus récente.

## Docker

Les images sont publiées avec une étiquette de version. Pour revenir en arrière, nomme l'étiquette dans ton fichier compose et recrée le conteneur :

```
image: ghcr.io/slater-proj/lutin:0.22.0
docker compose up -d
```

Tes données vivent dans le volume `lutin-data` (et les modèles dans `lutin-models`) : elles survivent au changement d'image, comme la CI le vérifie en détruisant et recréant le conteneur. Ne lance **pas** `docker compose down -v` : `-v` supprime les volumes.

## Ce que ça ne couvre pas

- Les modèles et les moteurs (Ollama, llama.cpp) se mettent à jour et se rétablissent avec leurs propres outils ; Lutin n'y touche pas quand il revient en arrière.
- Les jetons d'appairage des machines (Réglages > Machines) ne sont **pas** dans les sauvegardes : ce sont des secrets. Après une restauration sur un autre ordinateur, appaire de nouveau les machines.
- La commande de retour arrière a été testée avec un installateur simulé, pas avec une vraie publication sur une vraie installation. Essaie-la une fois de ton côté avant d'en avoir besoin.
