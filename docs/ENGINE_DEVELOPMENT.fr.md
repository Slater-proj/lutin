# Ajouter un moteur

Deux cas, du plus simple au plus complet. (English version: [ENGINE_DEVELOPMENT.md](ENGINE_DEVELOPMENT.md).)

## 1. Le serveur parle déjà l'interface OpenAI (`/v1/chat/completions`)

Aucun code. Ajoute une entrée à `tools/moteurs.source.json` (identifiant, nom, `"genre": "openai"`, adresse habituelle, description en français et en anglais, forces/limites facultatives, site), augmente `version` et `date`, puis lance `python tools/signer_catalogue_moteurs.py` (voir [ENGINE_CATALOG.fr.md](ENGINE_CATALOG.fr.md)). Le moteur apparaît alors dans la liste « Choisir un serveur connu… » de la carte du serveur externe. Lutin ne l'installe ni ne le démarre : tu donnes son adresse, il gère ses modèles lui-même.

## 2. Lutin doit installer, démarrer ou mettre à jour le moteur lui-même

Écris une sous-classe de `MoteurOpenAI` (`src/lutin/openai_engine.py`) pour un serveur de type OpenAI, ou de `Moteur` (`src/lutin/engines.py`) sinon, et enregistre-la à côté des autres dans `agent.py`. Le modèle à suivre est `MoteurLlamaCpp` dans `llamacpp_engine.py`. Ce qu'elle doit fournir :

- `actif`, `modeles`, `chat`, `chat_flux` : discuter, au format de messages d'Ollama (la traduction se fait aux frontières du moteur).
- `statut`, `actions` (installer, désinstaller, démarrer, arrêter, mettre à jour, chacune avec `possible` et une `raison` si ce n'est pas possible), `faire` : la carte des Réglages en est construite.
- `telechargeable`, `supprimer_modele` quand Lutin peut gérer les modèles.
- Des tests avec un faux serveur (ni réseau, ni vrai programme) ; ceux de llama.cpp montrent le principe.
- Textes en français dans le code, en anglais dans `src/lutin/langues/messages.en.json` (des tests vérifient que rien ne manque).

## Grille de capacités et suite de conformité

Chaque moteur déclare une grille (`grille()` dans `src/lutin/engines.py`) : pour chaque fonction (discuter, flux, bouton Arrêter, appels d'outils, raisonnement, images, embeddings, plusieurs modèles, téléchargement, installation), **natif** (le moteur le fait lui-même), **adapté** (Lutin traduit ou complète), **non supporté** ou **non testé**, avec une note d'une ligne. La grille s'affiche sur la carte du moteur (Réglages > Moteurs > « Ce que ce moteur sait faire »).

`tests/test_conformite_moteurs.py` joue les **mêmes vérifications sur chaque adaptateur** (Ollama, llama.cpp, serveur externe) contre un faux serveur, et vérifie chaque case « natif » ou « adapté » : la grille ne peut pas promettre ce que l'adaptateur ne sait pas faire. Une nouvelle classe de moteur voit sa grille vérifiée en l'ajoutant à ce fichier. Les fonctions qu'un faux serveur seul ne peut pas vérifier (plusieurs modèles, téléchargement, installation) sont listées dans `VERIFIE_AILLEURS` avec le test qui s'en charge.
