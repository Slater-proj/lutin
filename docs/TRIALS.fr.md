[English](TRIALS.md) · **Français**

# Essais réels

Les tests automatiques de Lutin utilisent de faux serveurs. Les essais ci-dessous se font **sur du vrai matériel**, par toi, et chacun produit un **rapport** à me renvoyer. Ils correspondent aux « essais » de la [feuille de route](ROADMAP.fr.md). Rien n'est téléchargé sans ton accord (la taille est annoncée avant).

## S1 — llama.cpp sur un poste Windows à carte NVIDIA

**Avant** : une version de Lutin d'au moins la **0.16.3** (`lutin update`, ou le bouton de mise à jour de la page). Facultatif mais utile : `nvidia-smi` dans un terminal affiche ta carte et la version du pilote.

**Étape 1 — le plus petit essai (environ 30 secondes, 1 Mo de modèle).** Il vérifie que le programme s'installe, démarre et répond. Dans un terminal :

```
lutin essai-moteur llamacpp --modele-test
```

Réponds `o` à la question de téléchargement (le programme fait de 25 Mo à environ 700 Mo selon ta carte : la version « CUDA » avec ses bibliothèques est la plus grosse).

**Étape 2 — le vrai essai avec un modèle qui sait appeler des outils (2,5 Go).**

```
lutin essai-moteur llamacpp --modele unsloth/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

Ce que tu dois voir : des lignes `✔` pour la machine, l'installation, le modèle, le démarrage, `/v1/models`, la conversation (avec les **jetons par seconde** et le **temps du premier jeton**), l'appel d'outil, l'arrêt. Une ligne `⚠` sur l'appel d'outil veut dire que le modèle n'a pas appelé l'outil : ce n'est pas une panne, mais c'est à me dire.

**Si ça ne marche pas** : le message dit l'étape qui échoue. Cas utiles à connaître :
- l'installation choisit « CUDA » mais le serveur ne démarre pas → réessaie avec `--variante vulkan` puis `--variante cpu`, et dis-moi lequel passe (et la version de ton pilote NVIDIA) ;
- « llama-server ne répond pas après 180 s » → regarde la fin du journal affichée dans le message (`moteurs/llamacpp/serveur.log` dans le dossier de données de Lutin).

**Ce que tu me renvoies** : tout ce que la commande a affiché (copie-colle), ou le fichier `essai-llamacpp-….json` du dossier `essais/` de ton dossier de données (son chemin est affiché à la fin de la commande). Le rapport ne contient ni tes conversations ni tes clés ; il contient la version de ton système, le matériel détecté et les mesures.

**Pour mesurer la vitesse proprement** : relance l'étape 2 une deuxième fois (le premier chargement est plus long : le fichier n'est pas encore en cache) et donne-moi les chiffres de la deuxième.

## S2 — llama.cpp dans l'image légère de Docker (automatique)

Ce n'est pas toi qui le fais : le workflow `moteurs` de GitHub Actions installe llama.cpp dans `python:3.12-slim` (l'image « légère » de Lutin), lance un modèle de 1 Mo et dit si le programme publié pour Ubuntu démarre avec la bibliothèque système de Debian. Il se déclenche à chaque changement du code des moteurs, chaque semaine, ou à la main (onglet Actions, workflow « moteurs »). Il **ne bloque jamais** une publication. Sa sortie contient le même rapport que ci-dessus.

## Les essais suivants

Les autres essais (S3 à S7 de la feuille de route : comparaison de moteurs, petit PC à GPU Intel, Docker Desktop, réveil à distance…) auront leur guide ici quand leur jalon commencera.
