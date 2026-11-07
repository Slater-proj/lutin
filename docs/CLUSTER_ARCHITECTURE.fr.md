[English](CLUSTER_ARCHITECTURE.md) · **Français**

# Machines : faire répondre Lutin avec le moteur d'une autre machine

Un petit PC (une Debian sans carte graphique, par exemple) peut répondre avec le moteur d'un poste à carte NVIDIA. **Chaque Lutin est un nœud** : pas d'agent séparé à installer.

> **Honnêteté.** Le protocole est testé avec deux serveurs Lutin réels dans un même programme de test, pas sur deux ordinateurs. Rien n'a été essayé sur un vrai réseau. Le réveil d'une machine éteinte arrive en 0.24.0.

## Le principe

- Le **nœud** (le poste à carte) prête le moteur de sa machine. Il est **éteint par défaut** ; tu l'actives dans Réglages > Machines (« Prêter le moteur de cette machine aux autres Lutin »), ce qui demande le niveau d'accès « réseau » (au niveau « cette machine seulement », personne d'autre ne pourrait l'atteindre).
- Le **principal** (le petit PC) route la demande de conversation vers lui, **si** le nœud est opérationnel pour ce modèle. Sinon, ou si la machine tombe, **le moteur local répond, en silence**.
- Routage d'abord, répartition ensuite. **Un même modèle n'est jamais réparti entre plusieurs machines** (hors programme de la 1.0).

## Ajouter une machine : validation explicite

1. Sur le nœud : Réglages > Machines > « Autoriser une machine… » affiche un **code à 8 chiffres**, valable 5 minutes, à usage unique.
2. Sur le principal : Réglages > Machines > « Ajouter une machine » : l'adresse du nœud (`192.168.1.20` ou `http://poste:8777`) et ce code.
3. Le nœud échange le code contre un **jeton de nœud**, propre à cette machine. Il ne garde que son empreinte (SHA-256). Le principal garde le jeton, **sans jamais l'afficher**.

Jamais d'acceptation automatique, jamais de découverte du réseau. Trop d'essais de code depuis une même adresse sont bloqués (comme pour le code PIN). **Révoquer** une machine (côté nœud) coupe son accès tout de suite.

## Ce que le jeton ouvre — et rien d'autre

`GET /api/noeud/etat`, `POST /api/noeud/chat`, et c'est tout. Le jeton n'ouvre **ni conversations, ni fichiers, ni réglages, ni mémoire** : tous les autres chemins répondent « authentification requise » (test automatique). Le nœud ne garde rien des demandes : il fait tourner son moteur et renvoie la réponse. Il ne transmet à son moteur que les champs d'une conversation (modèle, messages, outils, options…), pas autre chose, et ne relaie jamais vers une troisième machine.

## Les quatre états

| État | Sens |
|---|---|
| injoignable | pas de réponse (éteinte, hors réseau, Lutin arrêté), ou plus la même machine à cette adresse |
| réveil envoyé | un paquet de réveil est parti (0.24.0) |
| nœud joignable | la machine répond, mais son moteur est arrêté ou n'a pas le modèle voulu |
| moteur opérationnel | la machine peut faire tourner ce modèle : la demande y part |

L'état est vérifié (gardé 10 s) avant d'envoyer quoi que ce soit, et **l'identifiant du nœud est comparé à celui de l'appairage** : si une autre machine a pris l'adresse, rien ne lui est envoyé.

## Une machine injoignable ne dit rien dans la conversation

Pas d'erreur, pas d'avertissement : le moteur local répond. L'état est visible dans Réglages > Machines, et le journal des machines ne note qu'**un trait à chaque changement d'état** (jamais à chaque sonde, jamais le contenu d'une conversation). Une panne en plein milieu d'une réponse déjà commencée ne peut pas être rattrapée par le moteur local : elle se voit comme n'importe quelle réponse interrompue.

## Limites connues

- Le modèle choisi doit porter **le même nom** sur le nœud (sinon la machine reste « joignable » et le local répond).
- Le réseau est en HTTP clair sur le réseau local : le jeton et les conversations y circulent sans chiffrement. Pour sortir de chez toi, passe par un proxy HTTPS (voir SECURITY.fr.md). Ne publie jamais le port d'un nœud sur Internet.
- Seul le moteur choisi sur le nœud est prêté.
- Les embeddings, les images et les fonctions de fond restent locaux.
