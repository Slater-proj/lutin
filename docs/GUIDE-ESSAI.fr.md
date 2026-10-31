[English](GUIDE-ESSAI.md) · **Français**

# Essayer Lutin 0.8 pas à pas

Un parcours de 45 minutes environ pour vérifier, sur ta machine, ce qui est nouveau. Chaque étape dit **quoi faire**, **ce que tu dois voir**, et **quoi faire si ce n'est pas le cas**. Tout est annulable : rien n'écrit en dehors du dossier d'essai que tu choisis à l'étape 0.

Les fonctions suivantes n'ont été testées qu'avec de faux services (fausse API Telegram, faux Ollama…) : ce parcours est le premier vrai contact. Si une étape échoue, copie le résultat de `lutin doctor` (aucun contenu personnel) dans un rapport de problème.

## 0. Préparer un dossier d'essai

1. Crée un dossier **vide**, par exemple `C:\essai-lutin`.
2. Dans Lutin : *Réglages > Dossiers de travail > Ajouter*, choisis-le, puis appuie sur *Utiliser* pour le rendre actif.

*Tu dois voir* son nom dans la barre latérale. *Sinon* : le dossier doit exister et être lisible par ton compte Windows ; Lutin le dit en une phrase.

## 1. Le menu des extensions est rapide

Onglet **Automatisation** : la section *Extensions facultatives* doit apparaître en **moins d'une seconde**, même si ComfyUI est éteint (c'était 5 à 12 s avant la 0.8.0).

*Si c'est lent* : note si ComfyUI est activé, puis ouvre `donnees/serveur.log` ; un service qui ne répond pas est essayé une fois, pas six.

## 2. Un PDF et un document Word

Dans une conversation (mode *Polyvalent*), écris :

> Crée un petit compte rendu de réunion en PDF, puis le même en Word. Titre, trois points, une liste d'actions. Dans le dossier d'essai.

*Tu dois voir* : Lutin demande ton accord pour chaque fichier (une fenêtre avec le nom et la taille), puis **une carte par fichier sous le message** : nom, taille, chemin, boutons **Ouvrir**, **Télécharger**, **Supprimer**.

- **Ouvrir** : ton lecteur PDF et Word s'ouvrent comme après un double-clic. Vérifie les accents (é, à, œ, « »).
- **Télécharger** : le fichier arrive dans ton dossier de téléchargements, sous son vrai nom.
- **Supprimer** : confirme ; la carte disparaît et le fichier aussi du disque.

*Limites connues* : pas d'images ni de tableaux mis en forme dans le PDF ; un emoji devient « ? ».

## 3. Une image avec ComfyUI

1. *Automatisation > Extensions facultatives > ComfyUI* : coche la case. Lutin cherche ComfyUI tout seul. Si le panneau dit « ✔ », passe à la suite ; sinon *Choisir le dossier…* (le dossier qui contient `main.py`).
2. Demande : *Génère une image d'un phare dans la brume.*

*Tu dois voir* : l'accord, puis ComfyUI qui démarre **tout seul** (le modèle de langage lui cède la mémoire), puis **l'image directement dans la conversation**, avec son chemin dessous, **Télécharger** et **Supprimer**. Un clic sur l'image l'ouvre en grand dans un onglet. ComfyUI se referme ensuite.

*Si ça échoue* : le message doit maintenant nommer le **nœud fautif** (« Nœud 4 (CheckpointLoaderSimple) : Value not in list… ») et l'exception. Colle-le dans la conversation : le modèle sait quoi corriger. Un modèle de `diffusion_models` (Flux, Qwen-Image, Z-Image) utilise le workflow de sa famille ; « famille inconnue » veut dire qu'il faut préciser le modèle dans les réglages de l'addon.

## 4. Vérifier le rendu d'une page

Dans le dossier d'essai, demande : *Crée une page `essai.html` avec un titre et un bouton qui affiche l'heure, puis vérifie-la avec un aperçu.*

*Tu dois voir* : l'accord, puis la **capture** dans la conversation, et le modèle qui cite le texte affiché. Pour tester les erreurs, demande ensuite : *Ajoute un appel à une fonction qui n'existe pas et refais l'aperçu* : il doit relever « Uncaught ReferenceError … is not defined ».

*Si « Aucun navigateur… »* : installe Chrome ou Edge, ou donne le chemin de l'exécutable dans la variable d'environnement `LUTIN_NAVIGATEUR`.

## 5. Une première mission, courte

*Automatisation > Missions longues* (rien à activer) : *Nouvelle mission*. Ou écris la demande dans le champ de saisie et clique sur **🎯**.

- **Nom** : `Essai`
- **Dossier** : le dossier d'essai
- **Durée maximale** : `1` heure
- **Cahier des charges** : *Crée un petit jeu « pierre-feuille-ciseaux » en un seul fichier HTML, avec un fichier de tests en Python qui vérifie la règle du jeu. Lance les tests. Quand tout passe, termine la mission avec un bilan.*
- **Autonome** : **décoché** la première fois (essai à blanc : Lutin montre ce qu'il ferait, rien n'est écrit).

*Tu dois voir*, au fil des tours (le panneau se met à jour seul) : l'état, le nombre de tours et d'actions, puis un **bilan**. La conversation « 🎯 Essai » raconte tout, étape par étape.

Recommence ensuite avec **Autonome coché** : cette fois Lutin écrit les fichiers et lance les tests seul, dans ce dossier seulement. À la fin, regarde le dossier : le jeu et ses tests doivent y être.

Pendant qu'elle tourne, essaie :
- **Ajouter une consigne** (« mets le score en haut ») : prise en compte au tour suivant.
- **Mettre en pause**, puis **Reprendre**.
- **Arrêter Lutin** (icône de la zone de notification > Quitter), le relancer : la mission reprend là où elle était.

*Si la mission s'arrête avec « Je n'avance plus… »* : le modèle a répondu trois fois sans rien faire. Réponds à sa question, ou précise le cahier des charges. *Si elle se met en pause après trois erreurs* : le message dit laquelle (modèle arrêté, disque plein…).

**Pour une vraie mission d'une nuit** : un cahier des charges précis (ce qui est attendu, comment le tester, ce qui rend le travail « terminé »), un dossier à toi, une durée de 8 à 12 h, un modèle qui sait utiliser les outils (voir *Modèles*), et la mise en veille du PC désactivée.

## 6. Retrouver un passage par le sens

1. *Réglages > Mémoire des longues conversations* : coche **Recherche par le sens**, puis **Installer** (environ 270 Mo, avec une progression).
2. Dans une conversation longue (ou celle de l'étape 5), parle d'un sujet avec un mot, puis pose plus tard une question avec un **synonyme** (« prison » puis « détention »).

*Tu dois voir* : le passage retrouvé dans le rappel automatique du fil. *Sans le modèle installé* ou si Ollama est éteint, Lutin retombe sur la recherche par mots, sans erreur.

## 7. Garde-fous de longues conversations

- **Épingler** : sous un message, *📌 Épingler* ; il reste sous les yeux du modèle même quand le contexte est réduit.
- **Détecteur de boucle** : si le modèle refait le même appel cinq fois, la réponse s'arrête avec « Le modèle tourne en rond ».
- **Fiche de suivi** : au premier résumé, Lutin demande *fiche de suivi ou résumé*. La fiche est lisible et modifiable.

## 8. Telegram, courriel, X (si tu les utilises)

Chaque addon a ses étapes dans sa carte et un bouton **Vérifier** : il teste réellement le service et dit ce qui manque. Active-les un par un. Ces trois addons n'ont jamais parlé aux vrais services avant ton essai : signale tout comportement inattendu.

## Faire le ménage

*Réglages > Dossiers et données > Fichiers créés par Lutin* liste tout ce que ces essais ont produit (PDF, Word, images…) : sélectionne, supprime.

## Remettre à zéro

- Supprimer un fichier ou une image créés : le bouton **Supprimer** de leur carte.
- Supprimer une mission : *Supprimer* sur sa carte (la conversation reste dans la liste).
- Désactiver une extension : décoche sa case ; ses réglages sont gardés.
- Tout effacer : supprime le dossier d'essai et ses conversations ; rien d'autre n'a été touché.
