# Changelog

The following versions are published automatically (generated notes on the Releases page); this file keeps the first versions and the main changes. / Les versions suivantes sont publiées automatiquement (notes générées sur la page des Releases) ; ce fichier garde les premières versions et les changements principaux.

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
