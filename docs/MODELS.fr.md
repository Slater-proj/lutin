[English](MODELS.md) · **Français**

# Les modèles

## Comment Lutin choisit

1. Il lit ta machine : carte graphique et sa mémoire, RAM, disques.
2. Il calcule un **budget mémoire** : 85 % de la mémoire de la carte (NVIDIA, AMD), 75 % de la mémoire d'un Mac à puce Apple, sinon 60 % de la RAM (sans carte graphique : lent mais utilisable).
3. Pour chaque rôle, il garde le **modèle le mieux noté qui tient** : poids du modèle + mémoire de contexte (réduite de moitié grâce au cache compressé) + une marge. Le contexte est réduit (32 000 jetons, puis 16 000, puis 8 000) tant que ça ne tient pas.
4. Un modèle « à experts » (peu de paramètres actifs par mot) peut déborder en RAM : il est proposé avec la mention « plus lent ».
5. Seuls les modèles qui savent **appeler des outils** sont proposés : sans cela, Lutin ne peut ni lire ni modifier tes fichiers.

Le résultat est affiché par `lutin modeles` et à l'installation guidée. Tu peux toujours choisir autre chose dans l'onglet Modèles.

## Sans carte graphique, ou avec une carte intégrée seulement

Une carte graphique n'est **pas obligatoire**, dans Docker comme ailleurs : sans elle, Ollama utilise le processeur et la RAM.

- Une **carte intégrée** (Intel UHD / Iris / Arc Graphics, AMD « Radeon Graphics », Radeon 780M…) est **ignorée** pour choisir les modèles : Ollama ne s'en sert pas (ou mal), et sa « mémoire » n'est qu'une part de la RAM. Un tel PC est traité comme un PC sans carte, et `lutin doctor` le dit. Une carte que tu déclares toi-même (`LUTIN_GPU`) est toujours crue.
- Le budget est alors de **60 % de la RAM** : environ 19 Go sur un PC de 32 Go. Des modèles de cette taille tiennent, mais ils tournent sur le processeur : compte quelques mots par seconde avec un modèle de 7 à 14 milliards de paramètres, plus vite avec un modèle « à experts » (peu de paramètres actifs par mot). Ce sont des ordres de grandeur, **pas des mesures** : `lutin bench` mesure ta machine.
- Dans Docker, la carte NVIDIA demande `--gpus all` (voir [DOCKER.fr.md](DOCKER.fr.md)) ; les cartes AMD et Intel ne sont pas utilisées dans les conteneurs. Sans carte, rien à ajouter.

## Ne pas écraser le PC

Réglages > **Charge de la machine** (et les garde-fous juste au-dessus) :

| Réglage | Ce qu'il fait |
|---|---|
| Profil | des valeurs toutes faites : **Discret** (la moitié des cœurs, modèle gardé 2 minutes, contexte de 8 192 jetons au plus), **Normal** (tout en automatique), **Maximum** (tous les cœurs, modèle gardé 30 minutes) |
| Cœurs du processeur utilisés | combien de cœurs le modèle peut utiliser. Moins de cœurs = réponses plus lentes, mais le reste de l'ordinateur reste réactif. Surtout utile quand le modèle tourne sur le processeur |
| Garder le modèle en mémoire | minutes avant que le modèle soit libéré après la dernière réponse. `0` = libéré tout de suite (la mémoire revient au PC, la réponse suivante démarre plus lentement) |
| Fenêtre de contexte | plus elle est grande, plus il faut de mémoire (et plus les premiers mots sont lents) |
| Garde-fous ressources | avant chaque demande, Lutin vérifie la RAM libre, la mémoire vidéo et le disque, et suspend la demande avec une explication plutôt que de planter le PC |
| Bouton « Libérer la VRAM » (menu ⋯) | libère tous les modèles tout de suite, de la RAM aussi |

Changer les cœurs fait recharger le modèle une fois (quelques secondes).

## Les rôles

| Rôle | Pour | Coché au départ |
|---|---|---|
| Polyvalent | tout faire au quotidien | oui |
| Rapide | réponses presque immédiates | seulement s'il pèse moins de 5 Go |
| Créatif | écriture, histoires, idées | non |
| Code | programmation, scripts | non |
| Images | comprendre images, captures, documents | non |

## Modèles avancés

Certains modèles sont modifiés par la communauté pour ne plus refuser de demandes. Ils sont masqués par défaut, jamais choisis automatiquement, et s'affichent avec un avertissement quand tu actives « Afficher les modèles avancés ». Tu en es responsable.

## Le catalogue

`src/lutin/data/modeles.json` : une donnée, pas du code. Chaque modèle a une description d'une phrase (140 caractères au plus), sa taille, ses capacités, sa licence, et des notes de 1 à 10 par rôle.

**Les notes actuelles sont éditoriales : elles n'ont pas été mesurées.** Elles servent à classer les modèles entre eux pour un même rôle, pas à comparer les rôles. Pour les corriger, ouvre une proposition « Proposer ou corriger un modèle » en expliquant ce qui la justifie. Le champ `verifie` passera à une date quand la CI hebdomadaire (`tools/verifier_catalogue.py`) aura confirmé que le modèle existe dans le registre d'Ollama.

## Le banc d'essai : mesurer au lieu de croire

`lutin bench [modèle]` (ou les boutons « Tester la vitesse » et « Banc complet » de l'onglet Modèles) mesure **ce modèle sur cette machine** :

| Mesure | Comment |
|---|---|
| Vitesse | jetons écrits par seconde sur un texte de 150 mots, durée de chargement du modèle |
| Appel d'outils | 3 demandes : ouvrir un fichier, chercher une fonction, et ne **pas** appeler d'outil pour un simple bonjour |
| Code (lecture) | 4 petits programmes dont il faut donner le résultat |
| Français | une réponse en une phrase, et exactement trois puces |
| Consignes | un objet JSON valide, sans texte autour |

Les réponses sont vérifiées automatiquement ; **aucun code écrit par le modèle n'est jamais exécuté**. Une seule passe à température 0 : c'est un **indicateur**, pas un classement scientifique. Résultats gardés dans le cache, affichés dans la liste des modèles, et exportables (`lutin bench --exporter`) pour proposer une correction de note au catalogue.

Notes mesurées (de 0 à 10) : *code* = 60 % code + 40 % outils ; *créatif* = 60 % français + 40 % consignes ; *polyvalent* = moyenne des quatre ; *rapide* = barème sur les jetons par seconde (plafonné à 4 si le modèle n'appelle pas les outils : inutilisable pour Lutin). Les formules sont dans `lutin/bench.py` : conteste-les.

## Mises à jour

Au lancement (au plus une fois par jour, jamais bloquant), puis à la demande avec les boutons de l'onglet Modèles ou `lutin update` :

- **Chercher les mises à jour** : compare l'empreinte de chaque modèle installé avec celle du registre d'Ollama.
- **Chercher de nouveaux modèles** : télécharge le catalogue en ligne (s'il est configuré), puis compare avec ce que tu as installé pour chaque rôle. Une proposition apparaît si un modèle nettement mieux noté tient sur ta machine, ou si le tien ne tient plus.

Rien n'est téléchargé sans ton accord. « Ne plus proposer » mémorise ton refus.
