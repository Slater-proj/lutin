[English](EXPERIMENTAL_ENGINES.md) · **Français**

# Moteurs expérimentaux (Colibri, Strata)

Deux moteurs récents sont proposés comme **préréglages externes** : Réglages > Moteurs > carte « Serveur compatible OpenAI » > « Choisir un serveur connu… ». Ils sont marqués **expérimental**, rangés en dernier dans la liste, **jamais préselectionnés, jamais recommandés** (ni par les règles de la recommandation, ni par le banc).

> **Pourquoi pas une intégration gérée ?** La feuille de route ne prévoit d'installer et de démarrer Colibri depuis Lutin que si l'essai S3 (Ollama, llama.cpp et Colibri sur le même GGUF, sur une machine réelle) le justifie. **Cet essai n'a pas été fait.** Colibri reste donc un serveur que tu lances toi-même ; Lutin sait seulement lui parler.

## Comment s'en servir

1. Installe et lance le serveur du moteur (suis ses instructions : Lutin ne l'installe ni ne le démarre).
2. Dans la page : choisis-le dans « Choisir un serveur connu… », vérifie l'adresse, enregistre.
3. Choisis ensuite le moteur « Serveur compatible OpenAI » et un de ses modèles.

Chaque moteur est **indépendant** : en régler un ne touche ni à Ollama, ni à llama.cpp, ni à l'autre.

## Colibri (JustVugg/colibri)

- **Pour quoi faire** : très gros modèles « à experts » : experts chauds sur la carte, tièdes en mémoire vive, froids lus sur le disque. API compatible OpenAI, adresse habituelle `http://127.0.0.1:8000/v1`. Lit les GGUF.
- **Limites** : projet de recherche ; les chiffres publiés viennent de ses auteurs et n'ont pas été refaits ici ; avec 32 Go de RAM, les très gros modèles vont sur le disque et deviennent lents ; incohérences relevées dans ses chiffres (voir [ENGINE_STUDY.fr.md](ENGINE_STUDY.fr.md)).

## Strata (Niko1221/Strata)

- **Pour quoi faire** : application de bureau et ligne de commande avec une API locale compatible OpenAI. Cartes NVIDIA RTX 20 à 50 (Windows, Linux), AMD et Intel Arc sur Linux.
- **Limites** : le **port de son API n'est pas vérifié** (adresse vide : copie celle que Strata affiche) ; chiffres auto-mesurés sur d'autres modèles ; demande beaucoup de mémoire (12 Go de carte et 32 Go de RAM au minimum selon ses auteurs).

## Ce qui est testé

Un faux serveur compatible OpenAI : le préréglage, le réglage d'adresse, la liste des modèles et une réponse. **Aucun de ces deux moteurs n'a été essayé pour de vrai** avec Lutin.

## Ajouter un autre moteur

Un moteur de plus est une entrée du catalogue signé (voir [ENGINE_CATALOG.fr.md](ENGINE_CATALOG.fr.md)) : `type` `externe`, `genre` `openai`, `experimental` `true`. Pas de code à écrire.
