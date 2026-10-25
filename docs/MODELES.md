# Les modèles

## Comment Lutin choisit

1. Il lit ta machine : carte graphique et sa mémoire, RAM, disques.
2. Il calcule un **budget mémoire** : 85 % de la mémoire de la carte (NVIDIA, AMD), 75 % de la mémoire d'un Mac à puce Apple, sinon 60 % de la RAM (sans carte graphique : lent mais utilisable).
3. Pour chaque rôle, il garde le **modèle le mieux noté qui tient** : poids du modèle + mémoire de contexte (réduite de moitié grâce au cache compressé) + une marge. Le contexte est réduit (32 000 jetons, puis 16 000, puis 8 000) tant que ça ne tient pas.
4. Un modèle « à experts » (peu de paramètres actifs par mot) peut déborder en RAM : il est proposé avec la mention « plus lent ».
5. Seuls les modèles qui savent **appeler des outils** sont proposés : sans cela, Lutin ne peut ni lire ni modifier tes fichiers.

Le résultat est affiché par `lutin modeles` et à l'installation guidée. Tu peux toujours choisir autre chose dans l'onglet Modèles.

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

## Mises à jour

Au lancement (au plus une fois par jour, jamais bloquant), puis à la demande avec les boutons de l'onglet Modèles ou `lutin update` :

- **Chercher les mises à jour** : compare l'empreinte de chaque modèle installé avec celle du registre d'Ollama.
- **Chercher de nouveaux modèles** : télécharge le catalogue en ligne (s'il est configuré), puis compare avec ce que tu as installé pour chaque rôle. Une proposition apparaît si un modèle nettement mieux noté tient sur ta machine, ou si le tien ne tient plus.

Rien n'est téléchargé sans ton accord. « Ne plus proposer » mémorise ton refus.
