# Comparer les moteurs (Ollama, llama.cpp) sur ta machine

(English version: [BENCH_MOTEURS.md](BENCH_MOTEURS.md).)

Lutin sait faire tourner un même modèle avec Ollama ou avec llama.cpp (les modèles d'Ollama sont des fichiers GGUF que llama.cpp lit tels quels, sous les mêmes noms). Lequel est le plus rapide **sur ta machine** ? Le banc comparatif le mesure, et la recommandation te dit quel moteur choisir **et pourquoi**.

## Utiliser

- **Dans la page** : Réglages > Moteurs, carte « Quel moteur pour ma machine ? » : la recommandation et sa raison, puis « Comparer les moteurs » (environ 1 minute) ou « Comparaison approfondie » (environ 5 minutes).
- **En ligne de commande** : `lutin bench-engines [modèle] [--mode rapide|approfondi] [--output resultat.json]`.

Il faut que le modèle existe sur chaque moteur comparé (un modèle d'Ollama apparaît tel quel dans llama.cpp). Le banc ne tourne **jamais tout seul**, jamais au premier lancement, et ne télécharge rien. Avant de mesurer un moteur, il décharge le modèle de l'autre pour que la mémoire et la carte graphique soient à lui seul.

## Ce qui est mesuré

Pour chaque moteur : le chargement à froid, le premier jeton, la vitesse d'écriture (jetons par seconde, médiane de plusieurs passes), la vitesse de lecture du texte envoyé, la mémoire vive et vidéo prises, et la stabilité (une passe en échec rend le moteur « non recommandable »).

## La recommandation

- **Avec un banc valable** (au moins deux moteurs réussis, matériel et versions inchangés) : on recommande le plus rapide **seulement s'il gagne d'au moins 10 %** sur le plus simple (Ollama) ; en dessous, on garde le plus simple. La raison cite les chiffres.
- **Sans banc** : des règles générales (carte NVIDIA, carte AMD ou Intel, carte intégrée, pas de carte, Docker), toujours présentées comme **non mesurées**, avec leurs limites. Rien n'est téléchargé pour les établir.
- Un résultat est **à refaire** quand le processeur, la mémoire, les cartes graphiques ou la version d'un moteur change ; un résultat périmé ne décide plus rien.

## Partager un résultat

Le fichier produit par `--output` ne contient ni chemin ni nom d'utilisateur : seulement le matériel (processeur, mémoire, cartes), les versions des moteurs et les chiffres. C'est ce qui permettra de trancher les questions encore ouvertes sur des mesures réelles : l'image Docker par défaut, le petit PC à carte graphique intégrée (processeur, Vulkan ou Ollama), et llama.cpp contre Ollama sur une carte NVIDIA avec des modèles à experts. **Ces décisions ne sont pas prises tant qu'il n'y a pas de chiffres de plusieurs machines réelles.**
