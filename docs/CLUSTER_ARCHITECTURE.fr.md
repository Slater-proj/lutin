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

## Alimentation : réveiller, éteindre, démarrer tout seul (0.24.0)

- **Réveiller** : le bouton « Réveiller » envoie un paquet magique (Wake-on-LAN, UDP, bibliothèque standard) à l'adresse MAC de la machine (à renseigner). L'état passe à **réveil envoyé**, puis suit la machine : **nœud joignable**, **moteur opérationnel**. Si rien ne répond au bout de trois minutes, la page liste ce qu'il faut vérifier : Wake-on-LAN dans le BIOS, carte réseau autorisée à réveiller, câble Ethernet (le Wi-Fi réveille rarement), « démarrage rapide » de Windows désactivé, adresse MAC exacte, et ouverture de session automatique.
- **Éteindre** : action **explicite**. La machine à éteindre doit avoir coché « Autoriser les machines appairées à l'éteindre » (décoché par défaut, réglable depuis cette machine seulement). L'extinction a **30 secondes de délai**, se laisse **annuler** (depuis l'autre machine ou depuis la machine elle-même), et est **notée dans le journal des deux côtés**.
- **Démarrer Lutin tout seul** : « Démarrer Lutin à l'ouverture de ma session » (ou `lutin autostart install`). Windows : une **clé « Run » de ta session (sans droits d'administrateur)** (pas un service : un service tourne dans la session 0, sans carte graphique ni bureau). Linux : une **unité systemd utilisateur** (`sudo loginctl enable-linger $USER` pour démarrer sans session). macOS : non pris en charge.
- **Limites à connaître** : pour qu'un PC démarre sans personne devant, il faut aussi l'**auto-connexion Windows** et, dans le BIOS, « redémarrer après une coupure de courant » ; un PC en **veille prolongée ou en arrêt complet** n'accepte pas toujours le paquet magique (selon le BIOS) ; le réveil ne traverse pas un routeur (même réseau local seulement).
- **Non vérifié sur du vrai matériel** : le paquet de réveil est testé par un vrai envoi UDP local et la logique par des tests, pas par le réveil d'un vrai PC (essai S6 à faire).

## Limites connues

- Le modèle choisi doit porter **le même nom** sur le nœud (sinon la machine reste « joignable » et le local répond).
- Le réseau est en HTTP clair sur le réseau local : le jeton et les conversations y circulent sans chiffrement. Pour sortir de chez toi, passe par un proxy HTTPS (voir SECURITY.fr.md). Ne publie jamais le port d'un nœud sur Internet.
- Seul le moteur choisi sur le nœud est prêté.
- Les embeddings, les images et les fonctions de fond restent locaux.
