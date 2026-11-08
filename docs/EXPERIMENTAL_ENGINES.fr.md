[English](EXPERIMENTAL_ENGINES.md) · **Français**

# Moteurs expérimentaux (Colibri, Strata)

Deux moteurs récents sont proposés comme **préréglages externes** : Réglages > Moteurs > carte « Serveur compatible OpenAI » > « Choisir un serveur connu… ». Ils sont marqués **expérimental**, rangés en dernier dans la liste, **jamais préselectionnés, jamais recommandés** (ni par les règles de la recommandation, ni par le banc).

> **Colibri s'installe depuis la page** (Réglages > Moteurs > « Serveur compatible OpenAI » > choisir Colibri : Installer, Mettre à jour, Désinstaller, Démarrer, Arrêter, dossier du modèle et port) **et en ligne de commande.** `lutin colibri install` télécharge l'archive officielle de Colibri et **vérifie sa somme SHA-256** (le `SHA256SUMS.txt` de la publication est obligatoire), `lutin colibri start --model <dossier>` le lance sur `127.0.0.1` seulement, `lutin colibri stop` l'arrête. **L'installation a été essayée pour de vrai** (v2.1.0 téléchargée, vérifiée, décompressée) ; **le démarrage ne l'a pas été** : il exige un modèle de plusieurs dizaines de Go préparé par Colibri, et personne ne l'a lancé avec Lutin. L'essai S3 (Ollama, llama.cpp et Colibri sur le même modèle) reste à faire.

## Comment s'en servir

1. Installe et lance le serveur du moteur (suis ses instructions : Lutin ne l'installe ni ne le démarre).
2. Dans la page : choisis-le dans « Choisir un serveur connu… », vérifie l'adresse, enregistre.
3. Choisis ensuite le moteur « Serveur compatible OpenAI » et un de ses modèles.

Chaque moteur est **indépendant** : en régler un ne touche ni à Ollama, ni à llama.cpp, ni à l'autre.

## Colibri (JustVugg/colibri)

- **Pour quoi faire** : très gros modèles « à experts » : experts chauds sur la carte, tièdes en mémoire vive, froids lus sur le disque. API compatible OpenAI, adresse habituelle `http://127.0.0.1:8000/v1`. Lit les GGUF après conversion.
- **Limites** : projet de recherche ; les chiffres publiés viennent de ses auteurs et n'ont pas été refaits ici ; avec 32 Go de RAM, les très gros modèles vont sur le disque et deviennent lents ; incohérences relevées dans ses chiffres (voir [ENGINE_STUDY.fr.md](ENGINE_STUDY.fr.md)).
- **Vérifié sur sa page publique (2026-11-07, sans l'exécuter)** : licence Apache-2.0 ; archives pour Windows, Linux (x86-64) et macOS (Apple Silicon) avec un `SHA256SUMS.txt` ; démarré par son propre script (`start-here.sh` / `START-HERE.bat`), qui affiche les adresses du navigateur et « OpenAI base URL » ; **un fichier GGUF doit d'abord être converti** (`coli import model.gguf`), il n'est pas lu tel quel ; aucune option `--version` documentée.
- **Ce que Lutin fait pour lui** (`lutin colibri`) : installer avec une somme vérifiée, lancer `coli serve --host 127.0.0.1 --port 8000 --model <dossier>`, arrêter avec `coli stop`. Il ne prépare ni ne télécharge **aucun modèle** (utilise `coli setup` ou `coli import` de Colibri ; le dossier qu'il crée est celui qu'on donne à `--model`), et ne l'expose jamais sur le réseau. Ces commandes viennent de la lecture du script `coli` de Colibri (v2.1.0), **pas de son exécution** ; il demande Python, que Lutin a. Ensuite, choisis-le dans la page comme décrit plus haut. Essai : [TRIALS.fr.md](TRIALS.fr.md), S3.

## Strata (Niko1221/Strata)

- **Pour quoi faire** : application de bureau et ligne de commande avec une API locale compatible OpenAI. Cartes NVIDIA RTX 20 à 50 (Windows, Linux), AMD et Intel Arc sur Linux.
- **Limites** : le **port de son API n'est pas vérifié** (adresse vide : copie celle que Strata affiche) ; chiffres auto-mesurés sur d'autres modèles ; demande beaucoup de mémoire (12 Go de carte et 32 Go de RAM au minimum selon ses auteurs).

## Ce qui est testé

Un faux serveur compatible OpenAI : le préréglage, le réglage d'adresse, la liste des modèles et une réponse. **Aucun de ces deux moteurs n'a été essayé pour de vrai** avec Lutin.

## Ajouter un autre moteur

Un moteur de plus est une entrée du catalogue signé (voir [ENGINE_CATALOG.fr.md](ENGINE_CATALOG.fr.md)) : `type` `externe`, `genre` `openai`, `experimental` `true`. Pas de code à écrire.
