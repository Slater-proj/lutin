[English](CLUSTER_ARCHITECTURE.md) · **Français**

# Machines : faire répondre Lutin avec le moteur d'une autre machine

Un petit PC (une Debian sans carte graphique, par exemple) peut répondre avec le moteur d'un poste à carte NVIDIA. **Chaque Lutin est un nœud** : pas d'agent séparé à installer.

> **Honnêteté.** Le protocole est testé avec deux serveurs Lutin réels dans un même programme de test, pas sur deux ordinateurs. Rien n'a été essayé sur un vrai réseau. Le réveil d'une machine éteinte arrive en 0.24.0.

## Le principe

- Le **nœud** (le poste à carte) prête le moteur de sa machine. Il est **éteint par défaut** ; tu l'actives dans l'onglet Machines (« Prêter le moteur de cette machine aux autres Lutin »), ce qui demande le niveau d'accès « réseau » (au niveau « cette machine seulement », personne d'autre ne pourrait l'atteindre).
- Le **principal** (le petit PC) route la demande de conversation vers lui, **si** le nœud est opérationnel pour ce modèle. Sinon, ou si la machine tombe, **le moteur local répond, en silence**.
- Routage d'abord, répartition ensuite. **Un même modèle n'est jamais réparti entre plusieurs machines** (hors programme de la 1.0).

## Ajouter une machine : validation explicite

1. Sur le nœud : onglet Machines > « Autoriser une machine… » affiche un **code à 8 chiffres**, valable 5 minutes, à usage unique.
2. Sur le principal : onglet Machines > « Ajouter une machine » : l'adresse du nœud (`192.168.1.20` ou `http://poste:8777`) et ce code.
3. Le nœud échange le code contre un **jeton de nœud**, propre à cette machine. Il ne garde que son empreinte (SHA-256). Le principal garde le jeton, **sans jamais l'afficher**.

Jamais d'acceptation automatique, jamais de découverte du réseau. Trop d'essais de code depuis une même adresse sont bloqués (comme pour le code PIN). **Révoquer** une machine (côté nœud) coupe son accès tout de suite.

## Ce que le jeton ouvre — et rien d'autre

`GET /api/noeud/etat`, `POST /api/noeud/chat`, et c'est tout — plus, seulement si le propriétaire a coché le droit *mener des conversations* décrit plus bas, la porte étroite `/api/noeud/relais/…`. Sans ce droit le jeton n'ouvre **ni conversations, ni fichiers, ni réglages, ni mémoire** : tous les autres chemins répondent « authentification requise » (test automatique). Le nœud ne garde rien des demandes : il fait tourner son moteur et renvoie la réponse. Il ne transmet à son moteur que les champs d'une conversation (modèle, messages, outils, options…), pas autre chose, et ne relaie jamais vers une troisième machine.

## Les quatre états

| État | Sens |
|---|---|
| injoignable | pas de réponse (éteinte, hors réseau, Lutin arrêté), ou plus la même machine à cette adresse |
| réveil envoyé | un paquet de réveil est parti (0.24.0) |
| nœud joignable | la machine répond, mais son moteur est arrêté ou n'a pas le modèle voulu |
| moteur opérationnel | la machine peut faire tourner ce modèle : la demande y part |

L'état est vérifié (gardé 10 s) avant d'envoyer quoi que ce soit, et **l'identifiant du nœud est comparé à celui de l'appairage** : si une autre machine a pris l'adresse, rien ne lui est envoyé.

## Conversations menées sur l'autre machine

Une machine peut ouvrir et continuer les **conversations d'une autre machine** (entrées jaunes 🖥 de la liste) une fois que celle-ci a coché *Laisser les machines appairées mener des conversations ici* (onglet Machines, **décoché par défaut**).

- **Tout le tour s'exécute sur l'hôte** : son modèle, ses outils, ses addons (images, voix…), ses dossiers autorisés. La conversation y est stockée ; rien n'est copié sur la machine où tu écris, donc rien à synchroniser et aucune divergence possible.
- **Les fichiers restent sur l'hôte** : images, fichiers générés et pièces jointes sont demandés à l'hôte **quand tu les regardes ou les télécharges** (`/h/<machine>/…` sur ta page, transmis à l'hôte), jamais gardés chez toi. Les pièces que tu ajoutes sont envoyées à l'hôte.
- **Une porte étroite** : `POST|GET /api/noeud/relais/…` avec le jeton de nœud, le droit ci-dessus et une courte liste blanche (lire une conversation, envoyer un message, arrêter, répondre à un accord, envoyer une pièce, servir une image ou un fichier). Les réglages, le niveau d'accès, les dossiers et les mises à jour ne sont **pas** joignables ainsi. Le tour ignore tout modèle, mode, accord automatique ou troisième machine envoyé de l'extérieur : les réglages de l'hôte s'appliquent. Chaque tour est noté dans le journal des machines.
- **Accords** : les règles de l'hôte s'appliquent ; la carte d'accord apparaît là où tu écris et ta réponse repart vers l'hôte.
- **Hôte éteint** : la conversation disparaît de la liste (et revient quand l'hôte répond de nouveau).

## Une machine injoignable ne dit rien dans la conversation

Pas d'erreur, pas d'avertissement : le moteur local répond. L'état est visible dans l'onglet Machines, et le journal des machines ne note qu'**un trait à chaque changement d'état** (jamais à chaque sonde, jamais le contenu d'une conversation). Une panne en plein milieu d'une réponse déjà commencée ne peut pas être rattrapée par le moteur local : elle se voit comme n'importe quelle réponse interrompue.

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

## La page Machines (menu Réglages ▾)

La page **Machines** est dans le menu **Réglages ▾** en haut, à côté d'Automatisation, Santé et Accès. Elle est désactivée par défaut : elle explique ce qu'est le mode multi-machines et propose un bouton pour l'activer. Ensuite, pour chaque machine :

- **l'étape où elle en est, en direct** : *réveil envoyé → machine allumée → Lutin démarré → synchronisation → prête* (une connexion refusée distingue « allumée, Lutin pas lancé » de « éteinte ou injoignable »), et *extinction dans N s* avec un bouton Annuler. La page vérifie toutes les 2 secondes tant qu'une machine change d'étape, toutes les 8 secondes sinon ;
- **sa version de Lutin**, et un bouton **Mettre à jour Lutin** quand elle a une version plus ancienne que celle-ci. Le propriétaire de la machine distante doit avoir coché « Autoriser les machines appairées à mettre Lutin à jour » (décoché par défaut, depuis cette machine seulement, noté dans son journal). Elle redémarre ensuite toute seule si Lutin a été lancé par la commande `lutin`, et la page la suit (*mise à jour en cours*). Sous Docker, c'est l'image qu'on remplace (`docker compose pull && docker compose up -d`) ;
- **des détails repliés** : adresse MAC, charge mémoire, import de ses skills et de sa mémoire.

Quand une machine ne répond plus, ou qu'on l'éteint d'ici, **ses modèles et ses conversations disparaissent des listes tout de suite** : on ne peut plus lui parler. Quand elle répond de nouveau, ils sont relus (étape *synchronisation*).

Pas encore vérifié sur deux vrais ordinateurs : les étapes, le nettoyage et la mise à jour distante sont testés avec de faux nœuds et un vrai navigateur.
