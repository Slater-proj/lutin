# Changelog

The following versions are published automatically (generated notes on the Releases page); this file keeps the first versions and the main changes. / Les versions suivantes sont publiées automatiquement (notes générées sur la page des Releases) ; ce fichier garde les premières versions et les changements principaux.

## 0.8.3

- **Générer une image ne demande plus ton accord à chaque fois** si « Commandes automatiques » est coché (et dans une mission autonome).
- **Le modèle d'image choisi dans les réglages de ComfyUI est respecté** : il l'emportait sur lui à tort quand le modèle de langage en proposait un autre. Le réglage s'appelle maintenant « Modèle à utiliser » ; un modèle que tu nommes toi-même (même approximativement, « en SDXL »), dans ta demande ou dans le cahier d'une mission, est respecté.
- Une mission en attente d'une place de réponse ne tourne plus à vide ; l'aperçu de page supprime son profil temporaire même si le navigateur n'a pas fini de le lâcher.

**English.** Generating an image no longer asks for approval every time when “Automatic commands” is ticked (and in an autonomous mission). The image model chosen in ComfyUI's settings is now respected (the language model's suggestion used to override it by mistake); the setting is now called “Model to use”. A mission waiting for a free answer slot no longer spins; the page preview removes its temporary profile even if the browser has not released it yet.

## 0.8.0

- **Missions longues** (nouvel addon) : un cahier des charges confié pour des heures (un jeu complet, une refonte…), mené tour après tour sans toi, avec tous les outils, autonome ou à blanc, avec limites, pause, consigne en route, question du modèle, bilan, reprise après un redémarrage. Le « Travail de fond » devient « Traitement de documents ».
- **PDF et Word** : l'outil `creer_document` écrit des .pdf, .docx, .md, .txt, .html, .csv (Markdown simple), sans bibliothèque, et relit le fichier.
- **Les images créées avec ComfyUI s'affichent dans la conversation** (cliquables en grand).
- **Sous l'image : son chemin, Télécharger, Supprimer.** Erreurs de ComfyUI détaillées (message, nœud fautif, exception). Nouvel outil **apercu_page** : capture d'une page HTML dans Chrome/Edge/Chromium sans fenêtre, avec le texte affiché et les erreurs de la console.
- **Les fichiers créés (PDF, Word, Markdown, vidéo, son) apparaissent dans la conversation** : une carte avec Ouvrir (l'application choisie dans Windows, depuis cette machine seulement), Télécharger et Supprimer.
- **Guide d'essai pas à pas** (`docs/GUIDE-ESSAI.fr.md`) : 45 minutes pour vérifier chaque nouveauté sur ta machine. Les pièces jointes ont aussi ⬇ et ↗.
- **Les addons s'ouvrent vite** : la page de ComfyUI mettait 5 à 12 s quand il est éteint (six connexions refusées, ~2 s chacune sous Windows) ; un test de port de 0,3 s suffit.
- **Recherche par le sens (facultative)** : un petit modèle d'embeddings d'Ollama (installable d'un clic) permet au rappel du fil de retrouver un passage qui n'emploie pas les mots de la question ; fusion avec la recherche par mots, retour aux mots sans erreur si le modèle manque, vecteurs gardés sur le disque, vectorisation bornée en temps.

**English.** Long missions (new addon): a specification entrusted for hours (a complete game, a refactoring…), carried out turn after turn without you, with all tools, autonomous or dry-run, with limits, pause, instructions on the way, model question, summary, resuming after a restart; “Background work” becomes “Document processing”. PDF and Word: the `creer_document` tool writes .pdf, .docx, .md, .txt, .html, .csv (simple Markdown) with no library and reads the file back. Images made with ComfyUI are shown in the conversation. Addons open fast (ComfyUI's panel took 5-12 s when it was off: six refused connections, ~2 s each on Windows; a 0.3 s port check is enough). Search by meaning (optional): a small Ollama embeddings model (one-click install) lets the conversation recall find a passage that does not use the question's words; merged with word search, falls back to words without error, vectors kept on disk, time-bounded.

## 0.7.16

- **Messages épinglés** : un bouton 📌 sur chaque message le garde toujours sous les yeux du modèle (jamais retiré à la réduction du contexte, laissé tel quel par le résumé), huit au plus par conversation et dans la limite d'un quart de la fenêtre.

**English.** Pinned messages: a 📌 button on every message keeps it always in front of the model (never dropped when the context is trimmed, left untouched by the summary), eight per conversation at most and within a quarter of the window.

## 0.7.15

- **Détecteur de boucle** : le même appel d'outil refait trois fois n'est plus exécuté (le modèle reçoit l'ordre de passer à autre chose), cinq fois arrête la réponse ; une réponse qui répète la précédente presque mot pour mot est signalée, et la demande suivante ordonne d'exécuter l'étape en cours au lieu de replanifier.

**English.** Loop detector: the same tool call made three times is no longer run (the model is told to move on), five times stops the answer; an answer that repeats the previous one almost word for word is flagged, and the next request orders the model to carry out the current step instead of re-planning.

## 0.7.14

- Documentation : les addons dans le conteneur Docker.

## 0.7.13

- **ComfyUI : la liste des modèles est lisible.** Au lieu de 36 noms collés bout à bout : une ligne par modèle, groupés (modèles d'images, modèles de diffusion avec leur famille Flux / Qwen-Image / Z-Image ou « famille inconnue »), une longue liste défile ; les styles, encodeurs de texte et VAE sont repliés avec leur nombre.
- **Plus de refermeture en lisant.** L'état ouvert ou fermé de chaque bloc replié est retenu et la liste n'est plus reconstruite quand rien n'a changé. Les boutons des cartes sont espacés et le titre de la section est court.

**English.** ComfyUI: the models list is readable. Instead of 36 names run together: one line per model, grouped (image models, diffusion models with their family Flux / Qwen-Image / Z-Image or “unknown family”), a long list scrolls; styles, text encoders and VAEs are folded with their count. No more closing while you read: each folded block's open or closed state is remembered and the list is no longer rebuilt when nothing changed. Card buttons are spaced and the section title is short.

## 0.7.12

- **ComfyUI : les modèles de diffusion marchent.** Lutin n'envoyait toujours que le workflow « checkpoint » : avec des modèles rangés dans `diffusion_models` (Flux, Qwen-Image, Z-Image…), il tombait sur un dossier checkpoints vide. Maintenant le modèle choisi décide du workflow (nœuds UNETLoader, encodeur de texte, VAE choisis parmi ceux qui sont installés), avec un message clair si un fichier manque ou si la famille est inconnue ; le modèle voit à quelle famille appartient chaque fichier.
- **Format des listes** : le nouveau format de ComfyUI (« COMBO ») est compris, en plus de l'ancien ; une marque comme `{clip2}` (avec un chiffre) n'était pas remplacée, c'est corrigé.
- **Boucles d'écoute testées** : les fils de Telegram, courriel et X (lecture, réponse, panne, arrêt propre) ont maintenant leurs tests.

**English.** ComfyUI: diffusion models work. Lutin always sent the “checkpoint” workflow: with models stored in `diffusion_models` (Flux, Qwen-Image, Z-Image…) it hit an empty checkpoints folder. Now the chosen model decides the workflow (UNETLoader nodes, text encoder and VAE picked among the installed ones), with a clear message when a file is missing or the family is unknown; the model sees each file's family. List format: ComfyUI's new “COMBO” format is understood besides the old one; a mark like `{clip2}` (with a digit) was not replaced, now fixed. Listening loops tested: the Telegram, email and X threads (read, reply, outage, clean stop) now have tests.

## 0.7.11

- **Correction : les panneaux des addons ne clignotent plus.** La liste se reconstruisait toutes les 4 secondes en vidant d'abord l'écran, puis les panneaux (dossier de ComfyUI, boutons Détecter…) réapparaissaient après un appel au serveur : ils semblaient disparaître et revenir. La liste est maintenant construite hors de la page, échangée d'un coup, et seulement si elle a changé ; un chargement plus récent annule le précédent. Un test de navigateur surveille pendant 11 secondes qu'aucun panneau ne disparaît.

**English.** Fix: addon panels no longer flicker. The list was rebuilt every 4 seconds by emptying the screen first, and the panels (ComfyUI folder, Detect buttons…) came back after a server call, so they seemed to vanish and return. The list is now built off-page, swapped in one go, and only when it changed; a newer load cancels the previous one. A browser test watches for 11 seconds that no panel disappears.

## 0.7.10

- **ComfyUI : Lutin le lance et le referme lui-même.** Tu demandes une image dans la conversation ; Lutin rend d'abord la mémoire au modèle de langage, lance ComfyUI avec son propre Python, génère, puis le referme (réglable ; il ne ferme jamais un ComfyUI que tu as lancé toi-même).
- **Configuration assistée** : activer l'addon cherche ComfyUI tout seul et retient le dossier ; le panneau dit si le dossier est bon (ou pourquoi non), avec « Détecter » et « Choisir le dossier… » toujours visibles ; le dossier parent de la version portable est accepté.
- **Moins de texte, moins de rouge** : les descriptions et étapes de tous les addons sont réduites à l'essentiel ; « pas encore configuré » s'affiche en orange neutre, le rouge est réservé aux vraies erreurs ; une activation impossible ouvre la configuration avec la raison.

**English.** ComfyUI: Lutin starts and closes it itself. You ask for an image in the conversation; Lutin first gives the memory back from the language model, starts ComfyUI with its own Python, generates, then closes it (configurable; it never closes a ComfyUI you started yourself). Assisted setup: enabling the addon finds ComfyUI by itself and remembers the folder; the panel says whether the folder is right (or why not), with “Detect” and “Choose the folder…” always visible; the portable version's parent folder is accepted. Less text, less red: every addon's description and steps are cut to the essentials; “not set up yet” is shown in neutral orange, red is kept for real errors; a failed activation opens the setup with the reason.

## 0.7.9

- **Addons** : cocher un addon qui n'est pas encore configuré ouvre sa configuration (avec ce qu'il manque) au lieu d'une erreur ; après « Enregistrer et vérifier », un bouton « Activer maintenant ». Les redirections ne sont plus jamais suivies par un addon (elles pouvaient mener hors de ses sites autorisés).
- **ComfyUI plus facile** : « Choisir le dossier… » avec le navigateur de dossiers, et « Ajouter un modèle » qui télécharge depuis Hugging Face ou Civitai dans le bon dossier (rien d'écrasé, annulable).
- **Interface** : la barre de contexte et la vitesse retrouvent leur place, sans cadre (une règle de la jauge de disque la touchait par erreur) ; les traits de séparation des colonnes redeviennent fins, tout en restant faciles à attraper ; chaque conversation n'a plus qu'un menu « ⋯ » (épingler, renommer, fiche de suivi ou résumé, avec le choix coché) et la croix ; la jauge de disque des modèles est une vraie barre en segments (modèles, autres fichiers, libre) avec sa légende.

**English.** Addons: ticking an addon that is not set up yet opens its setup (with what is missing) instead of an error; after “Save and check”, an “Enable now” button. Addons never follow redirects any more. Easier ComfyUI: “Choose the folder…” with the folder browser, and “Add a model” downloading from Hugging Face or Civitai into the right folder (nothing overwritten, cancellable). Interface: the context bar and speed are back in place without a frame; column splitters are thin again yet easy to grab; each conversation has a single “⋯” menu (pin, rename, tracking sheet or summary with the choice ticked) plus the cross; the models disk gauge is a real segmented bar with a legend.

## 0.7.8

- **Rappel automatique du fil** : avant chaque réponse, les passages de toute la conversation (début archivé compris) qui touchent à la demande sont remis au modèle sans qu'il les demande ; un « oui » est complété par la dernière réponse et l'étape en cours.
- **Le scribe** : toutes les trois réponses, un appel court et séparé met la fiche de suivi à jour (décisions, étape, fait, questions ouvertes), contrôlé et désactivable. La fiche ne dépend plus de la bonne volonté du modèle qui répond.
- **Robustesse du serveur** : un corps de requête qui n'était pas un objet JSON (liste, texte, `null`, imbrication énorme) coupait la connexion sur chaque route ; il reçoit maintenant une erreur claire. Un test lance des requêtes absurdes (types inattendus, textes énormes, chemins piégés) sur toutes les routes d'un vrai serveur.

**English.** Automatic thread recall: before each answer, passages from the whole conversation (archived start included) that relate to the request are put in front of the model without it asking; a bare “yes” is completed with the last answer and the current step. The scribe: every three answers a short separate call updates the tracking sheet (decisions, step, done, open questions), checked and switchable. Server robustness: a request body that was not a JSON object (list, text, `null`, huge nesting) dropped the connection on every route; it now gets a clear error. A test sends absurd requests to every route of a real server.

## 0.7.7

- **Fiche de suivi : part du contexte réglable** (5 à 25 %, 10 par défaut) dans Réglages > Mémoire des longues conversations ; l'avertissement de lenteur suit le plafond choisi.

**English.** Tracking sheet: the share of the context window it may take is now adjustable (5 to 25 %, 10 by default) in Settings > Long conversation memory; the slowness warning follows the chosen cap.

## 0.7.6

- **Correction : le bouton « Envoyer »** de la page, quand on cliquait dessus (au lieu d'appuyer sur Entrée), déclenchait une erreur au lieu d'envoyer le message. Un test de navigateur réel clique maintenant sur le bouton.
- Un parcours réel dans Chrome couvre la question « fiche de suivi ou résumé ? » : la carte s'affiche, un clic répond, le choix est gardé et la réponse arrive.

**English.** Fix: clicking the page's “Send” button (instead of pressing Enter) raised an error instead of sending the message. A real-browser test now clicks the button. A real Chrome journey also covers the “tracking sheet or summary?” question: the card appears, one click answers, the choice is kept and the reply arrives.

## 0.7.5

- **Robustesse des addons** : les réglages, les secrets et les vérifications ne s'écrasent plus quand la page, la vérification quotidienne et les fils d'écoute écrivent en même temps ; un document de plus de 80 Mo est signalé au lieu de figer le travail de fond.

**English.** Addon robustness: settings, secrets and checks no longer overwrite each other when the page, the daily check and the listening threads write at the same time; a document over 80 MB is reported instead of freezing the background work.

## 0.7.4

- **Addon X** : publier sur ton compte (Lutin rédige un à cinq brouillons, tu publies ou programmes — rien ne part sans ton clic, 25 par jour au plus) et répondre aux mentions selon tes règles de tri (brouillons à valider, réponses seules plafonnées), signature OAuth 1.0a vérifiée sur l'exemple de la documentation de X. Lire les mentions demande une formule payante de l'API de X.

**English.** X addon: post on your account (Lutin writes one to five drafts, you publish or schedule — nothing leaves without your click, 25 a day at most) and answer mentions following your sorting rules (drafts to approve, capped automatic replies), OAuth 1.0a signing checked against the example in X's documentation. Reading mentions needs a paid X API plan.

## 0.7.3

- **Addon Courriel** : Lutin surveille ta boîte (IMAP) et prépare des réponses (SMTP) selon tes règles de tri (expéditeur, sujet, texte, ton jugé par le modèle) ; brouillon à valider par défaut, réponse seule possible (20 par jour au plus). Un courriel est une donnée, jamais un ordre : le modèle n'a aucun outil ; messages automatiques, doublons et arriéré ignorés ; mot de passe rangé à part.

**English.** Email addon: Lutin watches your inbox (IMAP) and prepares replies (SMTP) following your sorting rules (sender, subject, text, tone judged by the model); draft to approve by default, automatic reply possible (20 a day at most). An email is data, never an order: the model has no tool; automatic messages, duplicates and the existing backlog are ignored; password stored apart.

## 0.7.2

- **Addon ComfyUI** : détection de ComfyUI (version, carte graphique, dossier d'installation prérempli en un clic), liste des modèles installés (par ComfyUI ou par le dossier), génération d'images à la demande du modèle avec ton accord, workflows modifiables (vidéo et son : colle le tien). Éditeur de flux « Flux… » pour tous les addons.

**English.** ComfyUI addon: detection (version, graphics card, installation folder prefilled in one click), installed models list (from ComfyUI or from the folder), image generation on the model's request with your approval, editable workflows (video and sound: paste your own). A “Flow…” editor for every addon.

## 0.7.1

- **Addon Telegram** : parle à Lutin depuis ton téléphone. Appairage par code ; tes messages sont des demandes traitées en lecture seule ; les autres personnes sont ignorées, ou reçoivent un brouillon que tu valides, ou une réponse seule — toujours sans aucun outil. Le flux est corrigeable si Telegram change. Les addons peuvent désormais avoir des choix et des textes longs dans leurs réglages, un panneau propre et des actions.

**English.** Telegram addon: talk to Lutin from your phone. Pairing by code; your messages are requests handled read-only; other people are ignored, get a draft you approve, or an automatic answer — always with no tool at all. The flow can be fixed if Telegram changes. Addons can now have choices and long texts in their settings, their own panel and actions.

## 0.7.0

- **Les addons** : des fonctions facultatives livrées avec Lutin, désactivées par défaut, avec guide d'installation, vérification avant activation, revérification quotidienne, et un **flux** éditable (les appels faits à un service). Si un service change, l'addon passe en « à réparer » et Lutin propose une correction que tu valides (jamais appliquée seule, version livrée rétablissable). Un addon ne joint que les sites de son manifeste ; les secrets sont rangés à part.
- **Premier addon : le travail de fond** — une consigne appliquée à tous les documents d'un dossier de travail (PDF, Word, notes), en lecture seule, reprenable, avec pause, rapport, mode régulier ; il cède la place aux conversations et s'arrête sur les erreurs.
- Prochains addons prévus : Telegram, ComfyUI, puis courriel et X.

**English.** Addons: optional features shipped with Lutin, off by default, with a setup guide, a check before enabling, a daily re-check and an editable **flow** (the calls made to a service). When a service changes, the addon shows “needs repair” and Lutin proposes a fix you approve (never applied on its own, shipped version restorable). An addon only reaches the sites of its manifest; secrets are stored apart. First addon: background work, one instruction applied to every document of a work folder, read-only, resumable, with pause, report and regular mode.

## 0.6.4

- **Fiche de suivi ou résumé : Lutin te demande** au premier résumé automatique (réglage « Demander au premier résumé », par défaut), avec une case pour garder le choix pour toute la conversation ; passer à la fiche la remplit à partir du début de la conversation.
- **Rien n'est vraiment perdu** : le résumé archive les messages qu'il retire, et `rappeler` (avec `ici=true`) les retrouve ; le modèle est prévenu qu'il peut le faire. L'index du rappel ne relit que les fichiers modifiés et lit désormais les très longues conversations.
- **CI plus rapide** : trois séries de tests (Python 3.10 et 3.13 sur Linux, 3.12 sur Windows) au lieu de huit.

**English.** Tracking sheet or summary: Lutin now asks at the first automatic summary (new default “Ask at the first summary”), with a box to keep the choice for the whole conversation; switching to the sheet fills it from the start of the conversation. Nothing is really lost: the summary archives the messages it removes and `rappeler` (with `ici=true`) finds them again; the recall index only re-reads changed files and now reads very long conversations. Faster CI: three test series instead of eight.

## 0.6.3

- **Longues conversations** : deux méthodes au choix, par conversation, à tout moment — résumé automatique, ou **fiche de suivi** (objectif, décisions, plan, étape en cours…) tenue par le modèle et par Lutin, bornée, mesurée, supprimée avec la conversation. Un « oui » ordonne d'exécuter l'étape en cours au lieu de replanifier.
- **Mise à jour en un clic** depuis la page, les Réglages ou l'icône : installe, redémarre Lutin et recharge la page ; la ligne de commande reste.
- **Dossier des modèles d'Ollama** : analyse (réseau, débit, place), copie des modèles existants, redémarrage d'Ollama ; avertissements sur les dossiers réseau.
- **Reprise d'un ancien assistant** : l'avertissement disparaît une fois les données reprises (un statut « déjà dans Lutin » le remplace).
- **Interface** : colonne de gauche et séparation liste/options redimensionnables, réglages en groupes repliables, onglet Automatisation (tâches planifiées).
- **Solidité** : tests de la fiche de suivi, de la copie des modèles, de la mise à jour, des séparateurs et de la reprise dans un vrai navigateur.

**English.** Long conversations: choose per conversation, at any time, between automatic summary and a capped, measured **tracking sheet** that disappears with the conversation; a \"yes\" runs the current step instead of re-planning. One-click update from the page, Settings or the tray icon (command line kept). Ollama models folder: analysis (network, speed, space), copy of existing models, Ollama restart. The old-assistant warning disappears once its data is taken over. Resizable left column and list/options split, collapsible settings groups, an Automation tab.

## 0.6.2

- **Dossiers de travail** : après l'ajout, Lutin dit ce qu'il a trouvé et utilise (fichiers, consignes, skills) et détecte un ancien assistant avec un bouton « Reprendre ses données… » ; bouton Actualiser ; « Retirer » demande confirmation et peut nettoyer les copies de conversations.
- **Modèles** : pastille d'adéquation à la machine, phrase d'explication par famille, jauge de place disque, avertissement si le modèle ne tiendrait pas sur le disque.
- **Emplacements** : tous les dossiers utilisés avec leur taille et la place libre ; le dossier des modèles d'Ollama est visible et modifiable (un `null` dans la configuration est ignoré, Ollama lancé par Lutin reçoit ce dossier).
- **Accès** : un navigateur appairé par QR code ou adresse n'est plus nommé « QR » mais d'après son navigateur (« Cet ordinateur (Chrome · Windows) »).

**English.** Workspace folders now report what Lutin found and detect an old assistant (with a *Take over its data…* button), have a Refresh button, and *Remove* asks for confirmation and can clean the conversation copies. Models get a suitability badge for the machine, a one-sentence explanation per family, a disk-space gauge and a warning when a model would not fit. A Locations list shows every folder with its size and free space, and the Ollama models folder is visible and editable. A paired browser is no longer named « QR ».

## 0.6.1

- **Bibliothèque d'Ollama** (onglet Modèles) : les modèles récents ou populaires d'ollama.com, avec recherche, capacités et tailles, installables en un clic. Le catalogue de Lutin ne peut pas connaître un modèle sorti hier ; cette liste, si.
- **Tests** : chaque option des Réglages est changée et relue par l'API ; le conteneur Docker est vérifié de bout en bout dans la CI (réglages, pièce jointe, santé, dossiers de travail).

**English.** Models tab: an **Ollama library** browser (newest or most popular, with search, abilities and sizes, one-click install), because Lutin's hand-written catalogue cannot know a model released yesterday. Every Settings option is now changed and read back by a test, and the Docker container is checked end to end in the CI.

## 0.6.0

- **Plus aucune fenêtre noire** : tout programme lancé par Lutin sans console (nvidia-smi, git, commandes…) l'est sans fenêtre ; une règle unique (`sansconsole.py`), mesurée, au lieu d'un correctif par appel.
- **Serveur joignable partout où il doit l'être** : en plus de l'adresse du réseau, il répond toujours sur `127.0.0.1` ; le navigateur de la machine s'appaire tout seul (`#pin=`), et « Code PIN » de l'icône marche (le serveur *est* la machine).
- **Dossiers de travail** : dossiers réseau (UNC, NAS) acceptés avec la vraie raison en cas de refus, navigateur de dossiers, déplacement d'un dossier (copie vérifiée, retour arrière), changement de chemin, copie Markdown des conversations dans le dossier de travail.
- **Reprise d'un autre assistant** : un seul chemin donne skills, données et mémoire de l'ancienne instance, y compris sur un partage réseau.
- **Modèles** : liste regroupée par famille, deux lignes par modèle ; le catalogue « avancé » propose enfin des modèles sans restriction (dix ajoutés, vérifiés sur le registre d'Ollama).
- **Modes** : cinq (polyvalent par défaut, travail, écriture, recherche, discussion), expliqués dans les Réglages, `/mode` dans le chat.
- **Pièces jointes** : en plus des images, documents (PDF, Word, LibreOffice, PowerPoint, Excel, HTML) et fichiers texte ou code, lus une fois et bornés à une part du contexte.
- **Garde-fous plus rapides** : les mesures lentes (carte graphique, ComfyUI, disques) sont faites en parallèle et gardées quelques secondes, la taille du dossier de données se refait en arrière-plan, la taille du modèle chargé n'ajoute plus de requête.
- **Installation et désinstallation** : l'installateur et le désinstalleur arrêtent d'abord le Lutin qui tourne (c'était la cause de « des dossiers n'ont pas pu être supprimés » et d'un lancement final qui n'ouvrait rien) ; s'il reste quelque chose, la liste et la cause sont affichées ; la désinstallation propose de supprimer aussi les données (non par défaut).
- **Robustesse** : un `Content-Length` négatif ou illisible est refusé tout de suite au lieu de bloquer le serveur.

**English.** No more black windows (one rule for every program Lutin starts without a console). The server now always answers on `127.0.0.1` as well as on the network address, the local browser pairs itself, and the tray icon's PIN works. Workspace folders: network folders (UNC, NAS) with the real reason when refused, a folder browser, moving a folder, changing its path, a Markdown copy of conversations. Taking over another assistant: one path for skills, data and memory, also on a network share. Models: grouped by family on two lines each; the advanced catalogue finally offers uncensored models. Five modes with `/mode`. Attachments: documents and text or code files in addition to images. Faster safeguards (parallel, short-lived measurements). The installer and uninstaller stop the running Lutin first (the cause of « some folders could not be removed » and of a final launch that opened nothing), list what is left and why, and offer to delete your data (No by default).

## 0.5.2

- **Version affichée** : la page affichait une ancienne version (0.4.1) alors que la 0.5.1 était installée, quand une mise à jour laissait les métadonnées de l'ancienne à côté de la nouvelle. La plus haute est maintenant retenue, et l'installateur Windows nettoie les anciens fichiers de Lutin avant de copier les nouveaux.
- **Vérifier les mises à jour** (Réglages > Version de Lutin) : montre la version installée et la dernière publiée ; si GitHub ne répond pas, la vraie cause est affichée (pare-feu, certificat, hors ligne strict…) ; si l'API de GitHub est bloquée, la page publique des publications sert de repli.
- **Icône de zone de notification** : le menu du clic droit s'ouvre sur une vraie fenêtre cachée (pas une fenêtre « message seul »), l'icône revient si l'Explorateur redémarre, les erreurs vont dans `donnees/zone.log`. Au premier lancement, la configuration guidée s'ouvre dans une console ; l'installateur propose « Lancer Lutin maintenant » au lieu de « Configurer maintenant ».
- **Dossier de travail** : plus de liste déroulante dans la barre latérale ; tout se règle dans Réglages > Dossiers de travail (« Utiliser ce dossier », ajouter, retirer).
- **Réglages** : la langue n'a plus un double cadre ; « Version de Lutin », « Dossiers de travail », « Ajouter un dossier », « Nouveau code PIN », « Adresse publique », « Chercher » sont traduits en anglais (ils restaient en français : l'ancien test ne repérait que les phrases avec des accents).
- **Tests** : des parcours réels dans Chrome (reprise d'un autre assistant, dossiers, vérification de version, PIN et QR) ; les logos, les icônes et la zone de notification ont leurs tests ; la page anglaise des Réglages est enfin vérifiée.

**English.** The page showed an old version (0.4.1) with 0.5.1 installed when an update left the old version's metadata beside the new one: the highest is now used, and the Windows installer cleans Lutin's old files before copying the new ones. Settings > Lutin version has a **Check for updates** button that shows the installed and latest versions and, when GitHub does not answer, the real cause (firewall, certificate, strict offline…), with the public releases page as a fallback if the GitHub API is blocked. The notification-area menu now opens on a real hidden window, the icon comes back if Explorer restarts, errors go to `donnees/zone.log`, the guided setup opens in a console on the first start, and the installer offers « Start Lutin now ». The workspace drop-down is gone from the sidebar (Settings > Workspace folders does it all), the language selector no longer has a double frame, and several Settings texts that stayed French in English are translated. Real-browser tests now cover the take-over dialog, folders, the version check, and the PIN and QR code.

## 0.5.1

- **Vérifier les mises à jour** (premier bouton, Réglages) et correction du test `/api/conseil` sur Windows.

## 0.5.0

- **Icône dans la zone de notification (Windows)** : le raccourci Lutin tourne sans fenêtre de console ; clic droit : code PIN, ouvrir l'interface, redémarrer, quitter (`lutin zone`).
- **Onglet Accès** : le code PIN et son QR code s'affichent tout de suite au niveau réseau.
- **Dossiers de travail** : n'importe quel dossier se retire de la liste, le principal aussi ; le dossier utilisé s'ouvre aussi au démarrage.
- **Reprise d'un autre assistant** : erreurs et résultats s'affichent dans la fenêtre, qui dit où iront les skills.
- **Logos** : mascotte sans fond (onglet du navigateur, en-tête, icônes Windows, images de l'installateur) ; les icônes d'application gardent leur tuile pour le téléphone.
- **Images jointes** : le trombone remplit son bouton.

## 0.4.0

- **Access tab**: who can use Lutin, PIN code with a **QR code** to connect a phone, connected devices, restart banner when a change needs it. Changing access, workspace folders, restoring or scheduling is only possible from this machine (see docs/SECURITY.md).
- **Test my PC** (`/pc`): speed measurement and plain advice (lighter model, context window, load profile).
- **Dry run** (`/essai`): Lutin shows what it would write or run, without doing it.
- **Memory notes** list with *Delete*; **Claude project commands** available as `/commands`.
- **Documents**: PDF, Word, LibreOffice text, PowerPoint, Excel and HTML searched offline, with the page quoted.
- **Scheduled tasks**: a request handled by itself at a set time, read-only, result in a conversation.
- **Images**: attach, paste or drop an image; automatic switch to a model that can see it.
- **Docker and GPU**: NVIDIA (`--gpus all`), AMD (`:rocm`, `docker-compose.amd.yml`), diagnostics at startup; see docs/DOCKER.md.
- Maintenance: the engine is split into modules; monthly grouped Dependabot; automatic cleanup of release-candidate images. Code signing (SignPath) abandoned for now.
- All of it in [docs/FEATURES.md](docs/FEATURES.md).

**Français.** **Onglet Accès** (qui peut utiliser Lutin, code PIN avec **QR code**, appareils, bandeau de redémarrage) ; **Tester mon PC** (`/pc`) ; **essai à blanc** (`/essai`) ; liste des **notes** supprimables ; **commandes des projets Claude** en `/commandes` ; **documents** (PDF, Word, texte LibreOffice, PowerPoint, Excel, HTML) cherchés hors ligne avec la page citée ; **tâches planifiées** en lecture seule ; **images** jointes avec bascule vers un modèle qui les voit ; **Docker et carte graphique** (NVIDIA, AMD) ; moteur découpé en modules, Dependabot mensuel groupé, nettoyage automatique des images candidates. Signature de code (SignPath) abandonnée pour l'instant. Détails : [docs/FEATURES.fr.md](docs/FEATURES.fr.md).

## 0.2.0

- **English and French**: the whole application (page, messages, terminal, memory templates) and the repository docs. `lutin langue [fr|en|auto]`, a language question at the start of the guided installation, a selector in the page settings, `LUTIN_LANGUE`. Tests fail if a text has no translation.
- **Docker: one complete image** (Lutin + Ollama in the same container, `:latest`) and a slim one (`:slim`, Lutin alone). New volume `/models`, `docker run` in one command.
- **Take over another assistant**: `lutin reprendre` (and Memory > Take over another assistant in the page) brings conversations, memory, skills and settings, one category at a time, without overwriting anything. See docs/MIGRATION.md.
- **Machine load**: CPU cores used, how long the model stays in memory, ready-made profiles (Quiet / Normal / Maximum). Integrated graphics are ignored when choosing models (a PC with only integrated graphics is chosen by its RAM).
- **Claude projects**: `lutin importer <folder>` (and Memory > Claude project in the page) takes over a repository with `CLAUDE.md` and `.claude/` (skills, commands, agents, rules), working in it or in a copy. See docs/CLAUDE-PROJECTS.md.
- **New version notice**: a banner in the page (once a day at most, silent offline, can be skipped); nothing is installed without you.
- Fix: `install.ps1` no longer fails with `irm … | iex` (ASCII file, no BOM) (0.1.1).

**Français.** **Français et anglais** : toute l'application (page, messages, terminal, mémoire de départ) et les docs du dépôt. `lutin langue [fr|en|auto]`, une question de langue au début de l'installation guidée, un sélecteur dans les réglages de la page, `LUTIN_LANGUE`. Les tests échouent si un texte n'a pas de traduction. **Reprendre un autre assistant** : `lutin reprendre` (et Mémoire > Reprendre… dans la page) apporte conversations, mémoire, skills et réglages, une catégorie à la fois, sans rien écraser. **Charge de la machine** : cœurs utilisés, durée de garde du modèle, profils (Discret / Normal / Maximum) ; les cartes graphiques intégrées sont ignorées pour choisir les modèles. **Projets Claude** : `lutin importer <dossier>` (et Mémoire > Projet Claude dans la page) reprend un dépôt avec `CLAUDE.md` et `.claude/` (skills, commandes, agents, règles), dedans ou dans une copie. **Nouvelle version** : un bandeau dans la page (une fois par jour au plus, silencieux hors ligne, ignorable). **Docker : une image complète** (Lutin + Ollama dans le même conteneur, `:latest`) et une légère (`:slim`, Lutin seul). Nouveau volume `/models`, `docker run` en une commande. Correction : `install.ps1` ne plante plus avec `irm … | iex` (fichier ASCII, sans BOM) (0.1.1).

## 0.1.0 (first release / première publication)

Première version : extraite de l'assistant d'un projet personnel, rendue indépendante.

- Détection de la machine (NVIDIA, AMD, Intel, Apple ; RAM ; disques) et sélection de modèles par rôle selon la mémoire disponible.
- Catalogue de modèles en données, validé, avec une phrase de description par modèle.
- Trois niveaux d'accès : cette machine, réseau local (code PIN), proxy (identité du proxy de confiance).
- Installation guidée (`lutin setup`), interactive ou automatique (`--oui`).
- Ligne de commande : `lutin`, `chat`, `modeles`, `pin`, `appareils`, `securite`, `doctor`.
- Vérification des mises à jour de modèles au lancement (au plus une fois par jour, jamais bloquante).
- Scripts d'installation Windows (PowerShell) et Linux / macOS (shell).
- Installation idempotente : relancer le script ou `lutin setup` sur une machine déjà installée ne change rien (ou met à jour si une version plus récente existe) ; les modèles déjà téléchargés ne sont jamais retéléchargés.
- `lutin update` ; boutons « Chercher les mises à jour » et « Chercher de nouveaux modèles » dans l'onglet Modèles ; relance automatique du serveur après une erreur (`lutin serve`).
- Linux et macOS : lectures sans accord (`ls`, `cat`, `pwd`, `which`), refus des chemins absolus, arrêt des commandes avec leurs sous-processus.
- **Mode hors ligne strict** : aucune connexion vers Internet, vérifiée sur les connexions réelles.
- **Dossiers de travail multiples** : un dossier actif à la fois, chaque conversation garde le sien ; ajout réservé à cette machine.
- **Banc d'essai** des modèles sur la machine (vitesse, appel d'outils, code, français, consignes), exportable.
- **Journal des actions** (fichiers modifiés, commandes lancées, accord, personne), **sauvegarde et restauration** des données en un `.zip`.
- **Image Docker** (Lutin + Ollama, GPU NVIDIA en option) et `docker-compose.yml`.
- **Publications automatiques** : fusion dans `main` = version + étiquette + Release + image ; autre branche = candidate sans étiquette.
- Logo, bannière, captures d'écran ; icônes du téléphone aux couleurs de Lutin ; liens directs `/#modeles`, `/#conv=…`.
- Page : pastille verte « réponse terminée, pas lue », réponse qui reste dans sa conversation quand on en ouvre une autre, resynchronisation automatique, liste de tâches qui se ferme quand tout est fait.
