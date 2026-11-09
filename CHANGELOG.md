# Changelog

The following versions are published automatically (generated notes on the Releases page); this file keeps the first versions and the main changes. / Les versions suivantes sont publiées automatiquement (notes générées sur la page des Releases) ; ce fichier garde les premières versions et les changements principaux.

## Conversations menées sur l'autre machine

- **Les conversations d'une autre machine s'ouvrent au lieu de se copier** : tout le tour (modèle, outils, addons d'images ou de voix, dossiers autorisés) s'exécute sur la machine qui les héberge ; les fichiers générés et les pièces jointes y restent et sont servis à la demande. Plus de copie, donc plus de divergence. Nouveau droit sur l'hôte, **décoché par défaut** : « Laisser les machines appairées mener des conversations ici ».
- **Une porte étroite** : liste blanche de chemins, jeton de nœud ; réglages, accès et mises à jour restent hors d'atteinte. Le tour garde les réglages de l'hôte (modèle, mode, accords) et chaque tour est journalisé.
- **Les anciennes copies locales jamais continuées sont supprimées** automatiquement ; celles qui ont continué ici restent.
- **À savoir** : testé avec une seule instance qui joue les deux rôles et un vrai navigateur ; pas encore entre deux vrais ordinateurs. Pas encore de « nouvelle conversation » démarrée directement sur une autre machine : on continue une conversation existante.

## Machines réactives, recherche gratuite expliquée

- **Une machine éteinte disparaît vraiment** : Lutin la surveille en arrière-plan, même page Machines fermée. Si elle n'a pas répondu depuis ~40 s, ses modèles et ses conversations ne sont plus proposés ; à son retour ils reviennent. Les copies déjà importées restent utilisables ici, grisées avec une explication tant que leur machine ne répond pas.
- **Désactiver le mode multi-machines** vide aussitôt les listes distantes gardées en mémoire.
- **Recherche web** : la page dit clairement ce qui est gratuit (DuckDuckGo, Bing et SearXNG sans clé ; Tavily et Brave avec une offre gratuite limitée) et que Perplexity est payant.

## Navigation repensée, page Machines complète

- **Une barre du haut qui tient partout** : Conversation, Modèles, Mémoire et un menu **Réglages ▾** (Réglages, Automatisation, Machines, Santé, Accès). Le bouton affiche la page ouverte dans le menu, un point de couleur y signale un problème de santé, et sur téléphone le menu prend la largeur de l'écran. Le clavier marche (flèches, Échap).
- **Des pages moins chargées** : Réglages devient un sous-menu (Général, Moteur, Conversation, Recherche web, Dossiers, Avancé), une rubrique à la fois ; Mémoire, Automatisation et Accès ont le même sous-menu, bâti sur leurs titres. La dernière rubrique ouverte est retenue ; la recherche des Réglages cherche partout.
- **La page Machines** s'active depuis elle-même (la case des Réglages disparaît) ; chaque machine montre où elle en est, en direct : *réveil envoyé → allumée → Lutin démarré → synchronisation → prête*, et *extinction dans N s* avec Annuler. Une connexion refusée distingue « allumée, Lutin pas lancé » de « éteinte ».
- **Des listes propres** : quand une machine ne répond plus ou qu'on l'éteint d'ici, ses modèles et ses conversations disparaissent tout de suite ; à son retour, ils sont relus.
- **Mettre à jour Lutin à distance** : la machine affiche sa version, et un bouton apparaît si elle a une version plus ancienne. Le propriétaire doit avoir coché « Autoriser les machines appairées à mettre Lutin à jour » (décoché par défaut, noté dans son journal).
- **À savoir** : testé avec de faux nœuds et un vrai navigateur ; pas encore essayé entre deux vrais ordinateurs. Aucune mesure ne montre de ralentissement dû à l'application : les appels de la page au repos sont rares (3 toutes les 12 s), les plus lents sont la page Santé (~2 s à froid) et Automatisation (~0,5 s).

## Un onglet Machines, réveil et état des machines

- **Un onglet Machines** (réglage « Utiliser plusieurs machines » dans Réglages > Moteur) : les machines appairées, celle-ci quand tu la prêtes, le réveil, l'extinction et les imports y sont rassemblés ; les Réglages sont plus courts. L'onglet apparaît tout seul dès qu'une machine est appairée ou prêtée, et se cache sinon.
- **Le réveil (Wake-on-LAN) part par chaque carte réseau** (un VPN, Hyper-V, WSL ou Docker faisaient partir le paquet par la mauvaise) ; le bouton Réveiller dit toujours quelle adresse MAC et quelles cartes ont servi. Sous Docker, un conteneur en réseau « bridge » ne peut pas diffuser sur le réseau local : Lutin le dit et propose `network_mode: host` (docs/DOCKER.md).
- **Une machine distante n'est plus orange** parce qu'elle n'a pas le modèle choisi ici : ce modèle n'est cherché que sur la machine choisie pour répondre.
- **À savoir** : le réveil est essayé en vrai chez l'utilisateur (conteneur en mode host) ; l'onglet est testé par un vrai navigateur, mais sans machine distante réelle.

## Conversations, skills et mémoire partagés entre machines ; modèles llama.cpp sous Docker

- **Les conversations des machines appairées apparaissent dans ta liste, en jaune** (comme leurs modèles) : un clic en fait une **copie** ici, que tu continues avec les skills, la mémoire et les modèles de CETTE machine ; la copie garde son origine (🖥) et se met à jour si l'original a avancé et que tu ne l'as pas continuée ici (sinon elle est gardée telle quelle, jamais écrasée). Les images et fichiers joints restent sur l'autre machine.
- **Les skills et la mémoire se cumulent** : « Importer ses skills » ajoute ceux qui te manquent (jamais d'écrasement d'un skill qui existe ici) ; « Importer sa mémoire » ajoute les notes que tu n'as pas sous un titre « Depuis <machine> » (le profil n'est copié que s'il est vide ici).
- **Rien n'est partagé sans l'accord du propriétaire de la machine prêtée** : sur elle, Réglages > Machines > « Partager avec les machines appairées » (mes conversations, mes skills, ma mémoire), décoché par défaut, lecture seule, journalisé. Le jeton d'appairage ne permet toujours pas d'écrire chez elle.
- **Sous Docker, un modèle téléchargé pour llama.cpp n'apparaissait jamais** dans la liste (la lecture de la bibliothèque de Lutin était coupée avec celle d'Ollama) : il est maintenant listé, et peut être supprimé.
- **Interface** : Santé rassemble en une carte les disques qui sont le même disque et laisse de l'air entre ses sections ; Réglages s'ouvre plus court (« Dossiers et données » et « Conversation » repliés, l'état choisi ensuite est mémorisé).
- **À savoir** : le partage a été testé avec de faux nœuds ; essayé en vrai entre deux machines, il ne l'a pas encore été.

**English.** Conversations of paired machines appear in your list in yellow (one click makes a local copy to continue, never overwriting a copy you continued); skills and memory can be imported and accumulate without overwriting; nothing is shared unless the lent machine's owner ticks it (read-only, off by default); under Docker a model downloaded for llama.cpp now shows up in the list.

## Routeur de modèles, observatoire, laboratoire

- **Choix automatique du modèle** (Réglages > Conversation, désactivé par défaut) : Lutin range la demande d'après des signaux objectifs, sans appeler de modèle donc sans délai : code → un modèle « code » installé ; question qui demande de réfléchir → le plus gros modèle qui sait réfléchir et qui tient sur la machine (ou sur une machine appairée qui répond) ; question courte → un petit modèle plus vif. Il ne change de modèle que pour CETTE demande, le dit dans la conversation, ne propose jamais un modèle « trop gros » ni un changement sans gain net, et n'agit jamais pendant une mission. **Reprise** : si le modèle n'écrit rien ou tourne en rond, un essai avec un modèle plus gros.
- **Observatoire** (Santé > « Activité des modèles et des outils ») : par modèle, le nombre de réponses et la vitesse moyenne ; par outil, les appels, les échecs et la durée moyenne ; les reprises et les choix automatiques ; les derniers évènements. Seulement des noms, des durées et des compteurs, jamais le texte de tes messages ; 2000 évènements au plus.
- **Laboratoire** (Santé > « Mesures dans le temps ») : chaque test de vitesse est gardé (avec le moteur et sa version). Une baisse nette de la dernière mesure (vitesse ou épreuve en baisse de plus de 25 %) est signalée, avec « le moteur ou sa version a changé depuis » quand c'est la cause probable.
- **À savoir** : le routage juge la demande avec des règles (mots, longueur, code), pas avec une IA : il peut se tromper, d'où le réglage désactivé par défaut et l'annonce de chaque choix.

**English.** Optional automatic model choice per request (code, thinking, short question; announced, never for missions, retry with a bigger model on failure), an activity view (per-model speed, tool calls and failures; names and counters only) and a measurements history with regression flags, all in Health.

## Commandes en anglais

- **Toutes les commandes, options et valeurs de `lutin` ont un nom anglais officiel** : `lutin workspaces add`, `lutin models install`, `lutin offline on`, `lutin backup`, `lutin restore`, `lutin autostart install`, `lutin migrate`, `lutin import-project`, `lutin language`, `lutin log`, `lutin security`, `lutin devices`, `lutin bench-engines`, `lutin engine-trial` ; options `--yes`, `--level network`, `--workspace`, `--no-models`, `--no-ollama`, `--listen`, `--language`, `--reconfigure`, `--no-browser`, `--no-supervisor`, `--rollback-to`, `--models`, `--engine`, `--fast`, `--output`, `--force`, etc.
- **Les anciens noms français marchent toujours** (alias) : un script ou une habitude d'avant ne casse pas. L'aide (`lutin --help`) montre le nom anglais puis l'ancien nom entre parenthèses.
- **Partout où Lutin cite une commande** (messages, page, documentation, image Docker, scripts d'installation, intégration continue), c'est le nom anglais.
- **À savoir** : le texte d'aide reste dans la langue de l'application (réglage `lutin language`) ; seuls les NOMS des commandes sont en anglais par défaut.

**English.** Every `lutin` command, option and value now has an official English name (`lutin workspaces add`, `lutin offline on`, `--no-models`, `--level network`…); the old French names still work as aliases, and everything that quotes a command (messages, page, docs, Docker image, install scripts, CI) uses the English one.

## Machine prêtée plus robuste, un seul Lutin par port

- **Deux Lutin sur le même port sous Windows** : Python ouvre le port avec l'option « réutiliser l'adresse », qui autorise sous Windows plusieurs serveurs sur le même port. Un second Lutin (la tâche de démarrage ET un lancement à la main) démarrait donc sans erreur, avec son propre serveur de modèle : d'où deux `llama-server` en mémoire. Le port est maintenant exclusif, pris **avant** de lancer les travaux de fond, et un second Lutin s'arrête avec un message clair. Installer le démarrage automatique retire aussi l'ancienne tâche planifiée.
- **Le moteur d'une machine prêtée est partagé** : la personne qui l'utilise sur place passe en premier (une demande venue d'ailleurs attend la fin de son tour, 2 minutes au plus), puis les demandes se suivent. L'autre machine attend le moteur au lieu d'abandonner après 30 s, et « occupée » (trop de demandes à la fois) n'est plus pris pour une panne.
- **La machine distante montre sa charge** (RAM, VRAM, qui utilise son moteur) sur sa carte.
- **Un `llama-server` pas piloté par ce Lutin** est décrit (port, modèle) pour savoir d'où il vient ; Lutin le reconnaît aussi d'après sa ligne de commande quand Windows ne donne pas son chemin.
- **Pas encore possible** : régler Lutin à distance depuis l'autre machine (seule l'extinction, autorisée par le propriétaire, l'est) ; c'est volontaire, un jeton de nœud n'ouvre que le moteur.

**English.** On Windows two Lutin could listen on the same port (address reuse), each starting its own model server; the port is now exclusive and taken before any background work, and installing auto-start removes the old scheduled task. A lent machine's engine is shared fairly (its own user first, 2 minutes at most), the other machine waits instead of giving up after 30 s, "busy" is no longer taken for "down", and the remote machine shows its load.

## Fiabilité des informations : recherches nettoyées, journal de sortie, /web, Vérifier

- **Les recherches web sont nettoyées avant de partir chez un service extérieur** : adresses e-mail, téléphones, cartes bancaires (clé de Luhn), IBAN, clés et jetons, adresses du réseau local, chemins avec un nom d'utilisateur sont retirés, sans appeler de modèle (aucun délai) ; Lutin dit quelles catégories ont été retirées. Une requête faite uniquement de données personnelles n'est envoyée nulle part. Un SearXNG chez toi reçoit la requête telle quelle.
- **Santé > « Ce qui est sorti de cette machine »** : les dernières recherches envoyées à un service extérieur (heure, service, requête telle qu'elle est partie), avec un bouton pour vider.
- **`/web question`** : les résultats bruts d'une recherche (titre, site, date, extrait), à cocher ; « Demander au modèle de les lire » prépare le message. Rien n'entre dans la conversation tant que tu n'envoies pas.
- **Bouton « 🔎 Vérifier »** sous chaque réponse : cherche la question posée et montre les sources et leurs dates, pour juger la réponse.
- **Audit** : documentation Docker mise à jour (l'image ne contient plus Ollama ; `:slim` et `:rocm` sont la même image).

**English.** Web searches are cleaned of personal data before reaching an outside service (no model call, no delay) and listed in Health > "What left this machine"; `/web question` shows raw results to tick before the model reads them; a "Check" button under each answer shows the sources for the question asked; Docker docs updated.

## Cohérence entre les moteurs

- **Un seul remplacement de dossier robuste pour tous** : le correctif « Accès refusé » (réessais, arrêt des programmes restés ouverts, copie en dernier recours) n'était que dans llama.cpp ; il vit maintenant dans un module commun et **Colibri** s'en sert aussi.
- **Texte de la VRAM identique pour Ollama et llama.cpp** : « il manque environ X Go, le reste ira sur le processeur (plus lent) », au lieu d'un message différent selon le moteur. Pour Ollama, l'état reste « critique » en coulisses : c'est lui qui déclenche le déchargement automatique des modèles restés en mémoire avant d'en charger un autre.
- **Ollama sous Windows suit le dossier des moteurs** que tu as choisi (sous-dossier `ollama`), comme llama.cpp et Colibri.
- **Limites dites** : seuls llama.cpp, Colibri et Ollama s'installent depuis la page ; la vue des processus de la page Santé ne connaît pas encore Colibri.

## Recherche web : Tavily, Exa et Perplexity

- **Trois moteurs de recherche de plus**, chacun avec sa clé personnelle (Réglages > Recherche web) : **Tavily**, **Exa** et **Perplexity** (son API de *recherche*). Ils s'ajoutent à SearXNG et Brave, essayés avant DuckDuckGo et Bing.
- **Seuls les résultats servent, jamais une réponse déjà rédigée** : tout repasse par le modèle de Lutin, qui lit les extraits, compare et cite ses sources.
- **Confidentialité dite clairement** : chaque recherche part chez ce service ; le mode hors ligne les coupe ; les clés ne sont jamais renvoyées à la page.
- **À savoir** : les formats de requête viennent de la documentation de chaque service et sont testés avec de faux serveurs, pas avec une vraie clé.

**English.** Tavily, Exa and Perplexity (search API) join SearXNG and Brave, each with a personal key. Only results are used, never a ready-made answer, so Lutin's own model still reads and cites. Searches go to that service; offline mode cuts them. Tested against fake servers only.

## Machines distantes utilisables, démarrage automatique réparé, modèle qui annonce sans agir

- **Les modèles de l'autre machine sont dans la liste de choix.** Plus besoin d'avoir le même modèle sur les deux machines : la liste du haut ajoute les modèles des machines appairées (« qwen3:32b · 🖥 Gros PC », en couleur, groupés par machine ; une machine éteinte reste listée mais grisée). Choisir l'un d'eux envoie la conversation là-bas ; ses capacités (outils, images, réflexion) sont celles que la machine déclare ; la vérification de mémoire d'ici ne bloque plus un modèle qui tourne ailleurs. Si la machine ne répond pas, un message clair remplace le « modèle introuvable » du moteur local.
- **Adresse MAC reçue automatiquement** : la machine prêtée la transmet à l'appairage (la carte réseau par laquelle elle a été jointe, filaire de préférence) et la complète plus tard si elle manquait ; ce que tu as saisi à la main n'est jamais écrasé.
- **Réveil vérifié** : la machine dit si le Wake-on-LAN est activé sur sa carte, si elle est en Wi-Fi, si le « démarrage rapide » de Windows est actif ; la carte de la machine affiche ces avertissements (même éteinte, d'après son dernier message) et le bouton Réveiller les rappelle. Dans Docker, Lutin ne voit pas la carte de l'hôte : il le dit.
- **Lutin doit être lancé après un réveil** : si la machine ne démarre pas Lutin toute seule, la carte l'indique ; en activant « Prêter le moteur », Lutin propose (avec ton accord) d'activer le démarrage automatique ; pour Docker, il rappelle `restart: unless-stopped`.
- **« Démarrer Lutin à l'ouverture de ma session » ne marchait pas sous Windows** (« Accès refusé » : une tâche planifiée à l'ouverture de session demande les droits d'administrateur). Lutin utilise maintenant la clé « Run » de ta session, sans administrateur, et affiche l'état avec un bouton **Retirer le démarrage automatique** (qui retire aussi une ancienne tâche planifiée).
- **Case « Réflexion »** : décochée et grisée (avec la raison) quand le modèle choisi n'a pas de mode réflexion, au lieu de rester cochée sans effet.
- **Le modèle qui répond « Je vais vérifier… » puis rend la main** sans rien faire ni répondre est relancé une fois : Lutin lui rappelle d'appeler l'outil et de répondre directement à la question.
- **À savoir** : testé avec de faux nœuds et de faux registres ; le réveil réel, la lecture des cartes sous Windows (PowerShell) et la clé Run n'ont pas été essayés sur une vraie paire de machines. Sous Docker, la prise en charge des machines distantes reste celle du réseau du conteneur (la machine appairée doit être joignable depuis le conteneur).

**English.** The other machine's models appear in the model list (coloured, grouped per machine, greyed when off) so a big model can live on one machine only; the MAC address is received from the node at pairing; the node reports Wake-on-LAN, Wi-Fi and fast-startup problems, which the machine card shows (also when it is off) and the Wake button repeats; Lutin proposes enabling auto-start when you lend your engine; Windows auto-start now uses the per-user Run key (no administrator rights) with a Remove button; the Thinking checkbox is unticked and greyed for models without it; a model that only says "I'll check" is nudged once to call the tool and answer.

## Dossier des moteurs choisissable, noms de dossiers en anglais

- **Réglages > Moteurs > « Dossier des moteurs »** : un seul dossier pour tous les moteurs (un sous-dossier par moteur), choisi dans la page comme celui des modèles, **y compris sous Docker** (un chemin du conteneur). Ordre : variable `LUTIN_ENGINES`, puis ce choix, puis `/engines` s'il est monté **et modifiable**, puis `/data/engines`. Rien n'est déplacé en douce : le changement est refusé tant qu'un moteur installé par Lutin est dans l'ancien dossier. Le dossier d'installation propre à llama.cpp redevient modifiable sous Docker.
- **« /engines monté mais ignoré »** : si le dossier de l'hôte appartient à root, l'utilisateur 1000 du conteneur ne peut pas y écrire et Lutin se rabattait en silence sur les données. La carte de premier lancement et la carte du dossier disent maintenant pourquoi, et la commande à lancer (`sudo chown -R 1000:1000` sur le dossier de l'hôte).
- **Noms en anglais** pour tout ce qui est chemin de conteneur : `/workspace` (au lieu de `/travail`), `/engines`, `/data/engines` (au lieu de `/data/moteurs`), variables `LUTIN_WORKSPACE`, `LUTIN_WORKSPACES`, `LUTIN_ENGINES`. **Rien ne casse** : un volume `/travail` encore monté est reconnu, les anciennes variables sont lues, et l'ancien dossier `moteurs/` des données est renommé en `engines/` (ou gardé tel quel si un programme l'utilise). Les dossiers internes des données (`donnees`, `memoire`…) ne sont pas renommés dans cette version : cela demande une migration à part.

**English.** One "Engines folder" setting for all engines (also under Docker); the page now says why a mounted `/engines` is ignored (not writable by user 1000) and what command fixes it. Container paths are English (`/workspace`, `/engines`, `/data/engines`, `LUTIN_WORKSPACE(S)`, `LUTIN_ENGINES`); the old French names still work and `moteurs/` is renamed to `engines/`.

## Retours d'essai : mise à jour de llama.cpp, Colibri, premier lancement, mémoire vidéo

- **Mise à jour de llama.cpp sous Windows : « [WinError 5] Accès refusé »** (`bin.neuf` -> `bin`). Un antivirus qui analyse les fichiers tout juste écrits, ou un `llama-server` resté en vie, bloque le renommage quelques secondes. Lutin réessaie maintenant avec des pauses, arrête les `llama-server` restés dans son dossier, puis copie au lieu de renommer en dernier recours ; si rien n'y fait, il dit pourquoi.
- **Serveur « compatible OpenAI » : Colibri s'installe depuis la page.** En choisissant Colibri dans la liste, la carte propose Installer, Mettre à jour, Réinstaller, Désinstaller, Démarrer et Arrêter (somme SHA-256 vérifiée), avec ses réglages (dossier du modèle préparé par Colibri, port local) et l'avis de mise à jour. Les autres serveurs (LM Studio, vLLM…) restent des applications séparées : la carte le dit et l'explique.
- **Premier lancement : le message ne ment plus.** Si le moteur choisi ne répond pas mais qu'un autre est déjà installé, la carte propose « Utiliser Ollama » au lieu de dire qu'aucun moteur n'est prêt ; si rien n'est choisi ni installé, elle le dit.
- **Santé, mémoire vidéo en rouge avec 7 Go pris sur 24** : le niveau comparait la place libre au modèle *choisi* (pas encore chargé), sans le dire. Le texte donne maintenant la place libre, la place déjà prise, la taille demandée et ce qui manque ; avec llama.cpp (qui répartit tout seul entre la carte et le processeur) ce n'est plus un blocage mais un avertissement.
- **Santé, ce qui est vraiment en mémoire vidéo / en RAM** : le routeur de llama.cpp lance un processus par modèle, c'est lui qui tient la carte (le père affichait 0). Lutin additionne maintenant toute l'arborescence. Windows compte le fichier du modèle lu en mémoire dans la RAM du programme alors que le modèle est sur la carte : Lutin affiche la part réellement sur le processeur (d'après le journal du serveur) et le dit. Un `llama-server` resté en vie (ancien lancement, LM Studio, vLLM…) apparaît dans la liste avec sa mémoire vidéo ; Lutin peut arrêter ceux qui sortent de son propre dossier d'installation, jamais ceux des autres.
- **À savoir** : le démarrage de Colibri avec un vrai modèle, la lecture des compteurs de Windows par programme et le remplacement du dossier sous un vrai antivirus sont testés avec de faux programmes, pas sur ton matériel.

**English.** llama.cpp update on Windows no longer fails with "Access denied" (retries, stray llama-server stopped, copy fallback). Colibri can be installed, updated, started and stopped from the OpenAI-compatible card. The first-launch card proposes an engine that is already installed instead of claiming none is ready. Health: the VRAM level now explains itself (free, taken, needed, missing) and is a warning, not a block, with llama.cpp; llama.cpp's router children are counted, the mapped model file is no longer shown as RAM, and stray engine processes are listed (stoppable only if they come from Lutin's own folder).

## Mise à jour : patience face à une panne passagère de GitHub

- **« SHA256SUMS.txt illisible (HTTP 504) : mise à jour refusée »** : GitHub répond parfois 504 pendant quelques minutes. Lutin refusait aussitôt (c'est voulu : jamais d'installation sans somme vérifiée), mais sans insister. Il réessaie maintenant quatre fois (2, 5 puis 12 secondes) avant de renoncer, avec un message clair (« GitHub est momentanément indisponible… rien n'a été installé »), et recommence un téléchargement coupé en route. La vérification de la somme reste obligatoire. Même patience pour l'installation d'Ollama et de llama.cpp. **Si tu es bloqué sur cette erreur** : relance la mise à jour dans quelques minutes, ou `lutin update` dans un terminal.

## Docker : image légère, moteurs installés depuis la page

- **L'image Docker ne contient plus Ollama** (1,5 Go de moins à retélécharger à chaque mise à jour). Au premier lancement, la page propose d'installer le moteur conseillé : **le bouton « Installer Ollama » installe vraiment** (avant, il ouvrait seulement les réglages). Réglages > Moteurs installe, met à jour, démarre, arrête et désinstalle **Ollama et llama.cpp** dans Docker, comme sur ta machine.
- **Un volume pour les moteurs** : `/engines` (volume ou dossier de l'hôte ; sinon `/data/moteurs`). Une mise à jour de l'image ne l'efface pas. Les modèles restent dans `/models` (Ollama) et `/models/gguf` (llama.cpp). **À ajouter à ton compose** : `- /ton/dossier/engines:/engines` (accessible en écriture pour l'utilisateur 1000) ; sans cela, tout va dans `/data/moteurs`, qui survit aussi. **Ollama de l'ancienne image : à réinstaller une fois depuis la page** ; tes modèles ne bougent pas.
- **« Comparer les moteurs »** est grisé tant qu'il n'y a pas au moins deux moteurs installés qui ont le modèle, avec la raison.
- **Santé : llama.cpp sur la carte** : « 0 Go, tout est sur le processeur » s'affichait quand Windows ne donnait pas la mémoire vidéo par programme. Lutin la lit maintenant dans les compteurs de Windows, et dit « non mesurable » plutôt qu'un faux zéro.
- **Premier lancement sous Docker** : la carte dit où le moteur sera installé (`/engines` si tu l'as monté, sinon `/data/moteurs`) et comment le ranger ailleurs.
- **Un dossier par conversation** : `conversations/<titre>-<fin de l'identifiant>/` dans le dossier de travail, créé à la première écriture. Lutin dit au modèle d'y ranger ce qu'il produit pour la conversation (documents, exports, images, audio) ; le code du projet reste où le projet l'attend. L'audio de VoiceStudio y va aussi. Le menu ⋯ de la conversation le montre en premier (« Dossier de la conversation »), avec ouverture.
- **Flèche du haut** dans la zone de message : rappelle le dernier message envoyé (puis les précédents) pour le reformuler.
- **À savoir** : installation d'Ollama et de llama.cpp en Docker testée avec de faux serveurs ; pas encore sur du vrai matériel (carte NVIDIA, iGPU Intel).

**English.** Docker image no longer contains Ollama (1.5 GB lighter); the page installs and manages Ollama and llama.cpp into a `/engines` volume (or `/data/moteurs`) that image updates never erase; the first-launch "Install" button now really installs; engine comparison is disabled with fewer than two engines; Health no longer shows a false "0 GB, all on CPU" for llama.cpp on Windows; Up arrow recalls your last message. Not yet run on real hardware.

## Addon VoiceStudio et deux outils de plus

- **Addon VoiceStudio** (désactivé par défaut) : le modèle peut lister les voix, **lire un texte à voix haute** (accord à chaque fois, fichier audio joint sous le message), **transcrire** un enregistrement et **cloner une voix**, ce dernier avec un accord explicite *toujours demandé* (« c'est ma voix » ou « la personne a donné sa permission »), jamais automatique, et la déclaration est transmise à VoiceStudio. Seule la machine locale est jointe ; la clé d'API éventuelle ne s'affiche jamais. `docs/VOICESTUDIO.fr.md`.
- **Outils `trouver` (fichiers par nom) et `calculer` (calcul exact, sans exécuter de code)**, en lecture seule.
- **À savoir** : testé avec un faux VoiceStudio ; l'application réelle n'a pas été lancée.

**English.** VoiceStudio addon (off by default): list voices, read aloud, transcribe, clone a voice (explicit agreement always asked, never automatic); local machine only. New read-only tools `trouver` and `calculer`. Tested against a fake VoiceStudio; the real application was not run.

## Lutin cherche à la place du petit modèle

- Un modèle qui répondait « mes outils sont limités » au lieu de chercher n'est plus un problème : quand le message demande de chercher, ou colle une adresse, Lutin fait la recherche (ou lit la page) lui-même, affiche les **sources trouvées** et ne laisse au modèle que la réponse, avec renvois [1], [2]. Questions implicites (« qui est… », « le dernier… ») : pour les petits modèles. Requête nettoyée sans appeler le modèle quand la demande est courte. Voir `docs/WEB_SEARCH.fr.md`.

**English.** Lutin now searches (or reads a pasted address) itself when the message asks for it, shows the sources found and leaves the model only the answer.

## Recherche web complète

- **Plusieurs moteurs, dans l'ordre** : **SearXNG** (chez soi), **Brave Search** (clé personnelle), puis DuckDuckGo et Bing sans rien configurer ; le premier qui répond l'emporte, un moteur muet est laissé tranquille 10 minutes. Réglages > Recherche web : moteurs dans l'ordre, adresse de SearXNG, clé Brave (jamais renvoyée à la page), bouton **Tester la recherche** qui interroge chaque moteur séparément. `docker-compose.searxng.yml` + `docs/WEB_SEARCH.fr.md`.
- **Options pour le modèle** : `periode` (jour, semaine, mois, an), `site`, `actualites` ; résultats **nettoyés** (suivi et ancres retirés, doublons supprimés, deux résultats au plus par site) avec leur **date** et le moteur utilisé ; consigne de requête courte, de reformulation et de recoupement.
- **Lecture de pages** : **PDF** (jusqu'à 15 Mo), liste des **liens** d'une page (`liens`), menus et pieds de page ignorés quand il y a un vrai contenu, **cache de 10 minutes** (la suite d'une page longue ne la retélécharge pas), une reprise après une erreur passagère (502/503/504, délai), jeu de caractères annoncé par la page.
- **Sécurité** : l'adresse de SearXNG est la **seule adresse locale** que la recherche peut joindre (jamais pour lire une page), et ne se règle que depuis cette machine ; la clé Brave est dans un fichier privé. Deux défauts trouvés par les tests et corrigés (adresse `ftp://` et adresses avec espaces acceptées).
- **À savoir** : testé avec de faux SearXNG et Brave ; **l'image réelle de SearXNG et l'API réelle de Brave n'ont pas été lancées**.

**English.** Several engines in order: SearXNG (at home), Brave Search (personal key), then DuckDuckGo and Bing; Settings > Web search with a per-engine test button; `docker-compose.searxng.yml`; model options period/site/news; cleaned results with dates and engine; PDF reading, page links, 10-minute page cache, retry, charset; SearXNG's address is the only local address search may reach, settable from this machine only. Tested with fake SearXNG/Brave; the real image and API were not run.

## Compléments (après la 0.24.0)

- **Mises à jour vérifiées** : `lutin update` télécharge la roue, calcule son SHA-256 et la compare au `SHA256SUMS.txt` de la publication avant d'installer ; somme fausse, fichier absent de la liste ou roue énorme = refus, et pip installe le fichier vérifié lui-même. **Essayé pour de vrai** sur les publications v0.24.0 et v0.21.0. Limite : les sommes sont sur le même hébergeur que la roue (corruption, fichier échangé : oui ; publication compromise : non).
- **`lutin colibri installer / demarrer / arreter`** (expérimental) : téléchargement de l'archive officielle avec SHA-256 obligatoire, décompression qui ne peut pas sortir de son dossier, serveur sur 127.0.0.1. **Installation essayée pour de vrai** (v2.1.0) ; **démarrage jamais essayé** (modèle de dizaines de Go, code d'un tiers).
- **Pages construites par JavaScript** (Reddit…) : Lutin lit ce que le serveur annonce sans JavaScript (titre, description, données structurées), dit au modèle ce qui manque et lui fait proposer de copier-coller ou de joindre la page enregistrée. Un site qui refuse les lectures automatiques n'est pas contourné.
- **Recherche dans les Réglages** (filtre les groupes et ouvre ceux qui correspondent) ; **captures du README** : ajout de la page Santé (machine fictive).

**English.** Verified updates (SHA-256 against the release's `SHA256SUMS.txt`, tried on real releases). `lutin colibri installer / demarrer / arreter` (experimental; install tried for real, start-up never). Settings search. Health-page screenshot with a fictitious machine.

## Ergonomie (jalon 0.27)

- **Ctrl+K : tout trouver.** Une recherche sur les onglets, les conversations, les modèles installés, les groupes de réglages et les actions ; sans accents ni majuscules, au clavier (↑ ↓ Entrée Échap), accessible (rôles ARIA, focus rendu). Lien `/#palette`.
- **Accueil d'une conversation vide** : cinq départs concrets qui remplissent la zone de saisie sans rien envoyer ; il s'efface seul dès qu'un message arrive.
- **Appels d'outils lisibles** : « Lit README.md » au lieu de JSON brut, l'appel exact en infobulle.
- **Onglet Modèles plus court** (l'essentiel visible, le reste dans « En savoir plus ») ; **les boutons du banc d'essai de la page mesurent le moteur choisi** (llama.cpp, serveur compatible OpenAI), plus seulement Ollama.
- **Page compressée (gzip)** quand le navigateur le demande : 371 Ko deviennent environ 100 Ko.
- **Fiabilité** : une seule comparaison de moteurs à la fois même avec deux demandes simultanées (verrou), test devenu indépendant de la vitesse de la machine.
- **Visuels** : captures du README refaites avec une machine et un disque fictifs (`LUTIN_DEMO`), plus une capture de la palette. **Colibri** : faits vérifiés sur sa page publique consignés (conversion GGUF préalable) ; l'intégration gérée reste non faite, faute d'essai réel.

**English.** Ctrl+K search over tabs, conversations, installed models, settings groups and actions (keyboard-driven, accessible). Empty conversations show five starting points that fill the box without sending anything. Tool calls read as sentences with the exact call on hover. Shorter Models tab; the page's benchmark buttons now measure the chosen engine, not only Ollama. gzip for the page (371 KB to about 100 KB). One engine comparison at a time even with simultaneous requests. README screenshots redone with a fictitious machine and disk, plus a palette screenshot. Colibri facts checked against its public page; managed integration still not done (no real trial).

## 0.26.0

- **Stabilisation.** Aucun écran nouveau : on ferme des trous.
- **Un fichier de données abîmé ne fait plus planter Lutin.** Un `reglages.json` coupé ou qui n'était pas un objet faisait échouer chaque requête sans réponse ; la lecture de tous les fichiers de données rend maintenant la valeur par défaut quand le type lu n'est pas celui attendu.
- **Mise à jour sûre** : sauvegarde des données avant toute mise à jour (les trois dernières gardées, jamais bloquante), message clair si pip échoue. **Retour arrière** : `lutin update --revenir-a X.Y.Z` réinstalle une version publiée (numéro strictement contrôlé). Une mise à jour normale ne recule jamais.
- **Page plus rapide quand le moteur est arrêté** : l'état de la recherche par le sens ne sonde plus le moteur une seconde fois à chaque rafraîchissement.
- **Tests** : parcours d'une installation vierge (toutes les routes de lecture, chemins hors dossier refusés) et de fichiers de données abîmés ; mise à jour et retour arrière.
- **Docs** : `docs/ROLLBACK.fr.md` (retour arrière), `docs/SECURITY_AUDIT.fr.md` (revue de sécurité : ce qui est vérifié, ce qui reste ouvert, dont la vérification des mises à jour). Revue par les mainteneurs, **pas un audit indépendant**. **Rien de ceci n'est la 1.0** : les essais sur du vrai matériel restent à faire.

**English.** Stabilisation, no new screen. A damaged or wrong-type data file no longer crashes Lutin (it used to fail every request with no answer). Safe update: data backup before any update (last three kept, never blocking) and `lutin update --revenir-a X.Y.Z` to reinstall a published version; a normal update never goes back. The page no longer probes a stopped engine twice per refresh. New tests: fresh-install walk-through, damaged data files, update and rollback. New docs: rollback procedure and security review (maintainers' own review, not an independent audit; update integrity beyond TLS listed as an open limit). This is not 1.0: real-hardware trials are still to do.

## 0.25.0

- **Moteurs expérimentaux : Colibri et Strata**, en préréglages externes du catalogue signé (version 3), étiquetés « expérimental », rangés en dernier, jamais préselectionnés ni recommandés. Nouveau champ `experimental` dans le schéma du catalogue ; la veille hebdomadaire les suit. Pas d'intégration gérée de Colibri : l'essai S3 qui devait la justifier n'a pas été fait. `docs/EXPERIMENTAL_ENGINES.fr.md` dit leurs limites. **Aucun des deux n'a été essayé pour de vrai** (testés avec un faux serveur).

**English.** Colibri and Strata as external presets in the signed catalogue (version 3), labelled "experimental", listed last, never preselected nor recommended; new `experimental` schema field; weekly watch follows them. No managed Colibri integration (trial S3 not done). Tested with a fake server only.

## 0.24.0

- **Réveiller une machine (Wake-on-LAN).** Bouton « Réveiller » (adresse MAC à renseigner) : état « réveil envoyé » puis « nœud joignable » puis « moteur opérationnel » ; après trois minutes sans réponse, la page liste ce qui bloque d'habitude (BIOS, carte réseau, câble, démarrage rapide, auto-connexion).
- **Éteindre une machine, avec accord.** Décoché par défaut côté machine à éteindre ; 30 secondes de délai, annulable, journalisé des deux côtés.
- **Démarrer Lutin tout seul** : tâche planifiée à l'ouverture de session (Windows), unité systemd utilisateur (Linux) ; `lutin demarrage-auto`. Les limites (auto-connexion Windows, BIOS) sont dites dans la page. **Non vérifié sur du vrai matériel.**

**English.** Wake-on-LAN button with the wake-up → reachable → operational states and a checklist when nothing answers, remote shutdown only if the machine allowed it (30 s, cancellable, logged on both sides), start Lutin at session logon (Windows scheduled task / Linux systemd user unit, `lutin demarrage-auto`). Not verified on real hardware.

## 0.23.0

- **Machines : un Lutin répond avec le moteur d'un autre (D7).** Réglages > Machines : « Prêter le moteur de cette machine » (éteint par défaut), code d'appairage à 8 chiffres (5 minutes, une fois), jeton de nœud par machine (gardé haché, révocable), ajout par validation explicite. Le jeton n'ouvre que `/api/noeud/*` : ni conversations, ni fichiers, ni réglages.
- **Quatre états visibles** (injoignable · réveil envoyé · nœud joignable · moteur opérationnel), routage vers le nœud quand il peut faire tourner le modèle, **repli silencieux sur le moteur local** sinon : aucune erreur ni avertissement dans la conversation. L'identité du nœud est vérifiée avant d'envoyer quoi que ce soit ; journal des machines (un trait par changement d'état).
- `docs/CLUSTER_ARCHITECTURE.fr.md`. **Testé avec deux vrais serveurs Lutin dans un même test, pas sur deux ordinateurs.**

**English.** Machines (D7): lend this machine's engine (off by default), 8-digit pairing code, per-machine hashed revocable node token that only opens `/api/noeud/*`, four visible states, routing to the node with silent local fallback, node identity checked before sending anything, machines log. Tested with two real servers in one test, not on two computers.

## 0.22.0

- **Estimer avant de charger.** La mémoire qu'un modèle prendra (fichier + conversation + marge), où (carte, mémoire vive) et un niveau (tient / partiel / tient à peine / ne tient pas) sont annoncés AVANT le chargement : dans la bannière, dans la conversation (une fois par demi-heure) et à la demande (`/api/estimation`), avec ce qui ferait tenir le modèle (conversation plus courte, cache plus léger).
- **Modèles à experts** : préréglage « experts sur le processeur » (`--n-cpu-moe`) calculé pour que le reste tienne sur la carte (24 Go + 32 Go de RAM). Nombre de couches estimé.
- **Mode prudent** proposé aux machines modestes (jamais appliqué sans accord).
- **Estimation contre mesure** : le banc des moteurs enregistre l'écart entre l'estimation et la mémoire réellement prise. Aucun écart réel mesuré pour l'instant.

**English.** Estimate before loading (memory, where, level, advice), mixture-of-experts processor preset, cautious mode for modest machines, estimate-versus-measurement gap recorded by the engine bench (no real gap measured yet).

## 0.21.0

- **Jamais un modèle incompatible avec le moteur choisi.** L'onglet Modèles masque ce que le moteur ne sait pas faire tourner (repli « N modèles masqués » avec la raison), l'installation d'un modèle incompatible est refusée, et chaque ligne dit le format (GGUF), la quantification et la mémoire estimée. La compatibilité vient de la grille de capacités du moteur (outils, raisonnement, images) ; un serveur externe ne montre que ses propres modèles.
- **Rôles par moteur** : `lutin modeles recommander --moteur llamacpp` choisit polyvalent / rapide / code… parmi les seuls modèles compatibles.
- **Le banc d'essai ne dépend plus d'Ollama** : `lutin bench --moteur llamacpp` (ou `openai`) mesure vitesse, outils, code, français avec le moteur choisi.

**English.** Models incompatible with the chosen engine are never offered (hidden with the reason, install refused, format/quantization/estimated memory shown); roles are computed per engine (`lutin modeles recommander --moteur`); the bench runs on any engine (`lutin bench --moteur`).

## 0.20.0

- **Docker : un conteneur par moteur, au choix, avec des profils Compose.** `docker-compose.moteurs.yml` : `--profile ollama`, `llamacpp-cpu`, `llamacpp-cuda`, `llamacpp-vulkan`, `llamacpp-intel`. Lutin y est déjà pointé sur le bon moteur (`OLLAMA_URL`, nouvelle variable `LUTIN_LLAMACPP_URL`) : rien à saisir. Nouvelle page `docs/DOCKER_INSTALLATION.fr.md` (Docker Linux, Docker Desktop et WSL2, cartes graphiques). **Profils llama.cpp non vérifiés sur du vrai matériel.**
- **`lutin doctor` connaît Docker.** Dans le conteneur : `/data` et `/models` sont-ils de vrais volumes (sinon tout disparaît à la recréation), accessibles en écriture, mémoire vue, moteurs à côté joignables. Sur l'hôte : version de Docker, Compose v2, mémoire donnée à Docker (WSL2).
- **Premier lancement.** Tant qu'aucun moteur n'est prêt, l'onglet Modèles est grisé avec la raison et une carte propose : installer le moteur conseillé, en choisir un autre, ou plus tard.
- **Annuler une installation ou un téléchargement de moteur** (bouton « Annuler ») ; ce qui est téléchargé est gardé, relancer reprend où ça s'était arrêté.
- **Test de CI des volumes** : un conteneur est recréé avec les mêmes volumes et retrouve ses données et ses modèles.

**English.** Docker: one container per engine through Compose profiles (`docker-compose.moteurs.yml`, `LUTIN_LLAMACPP_URL`), `lutin doctor` understands Docker (volumes, memory, reachable engines), first-launch card with the Models tab greyed out until an engine is ready, cancellable engine installs (downloads resume), CI test that recreating a container keeps data and models. llama.cpp profiles are unverified on real hardware.

## 0.19.1

- **llama.cpp ne coupe plus une réponse en cours.** Avec llama.cpp (un seul modèle à la fois), la mise à jour de la fiche de suivi ou une autre demande avec une fenêtre de contexte différente redémarrait le serveur en pleine réponse : la conversation restait « en attente » et le banc affichait « 'NoneType' object has no attribute 'poll' ». Le serveur n'est plus jamais redémarré sous une réponse en cours (la demande suivante attend la fin), un contexte plus petit ne provoque plus de redémarrage, et le démarrage dit clairement si le serveur a été remplacé.
- **Page Santé plus claire et immédiate.** Elle s'affiche tout de suite avec les cartes « Mémoire vive » et « Mémoire vidéo » (jauge, ce qui les occupe, bouton Décharger) ; les disques arrivent ensuite sans bloquer. Chaque modèle dit s'il est sur la carte graphique ou sur le processeur (pour llama.cpp : les couches sur la carte lues dans son journal, et la mesure de nvidia-smi quand elle existe). Si le llama.cpp installé est la version processeur alors que la machine a une carte, la page le dit et indique quoi faire. ComfyUI peut être déchargé, ou fermé quand c'est Lutin qui l'a lancé.

**English.** llama.cpp no longer cuts a running answer (the server is never restarted under one; a smaller context does not restart it). Health page shows at once, with RAM and video-memory cards listing what uses them, where each model sits (graphics card or processor), and unload buttons (ComfyUI can also be closed when Lutin started it).

## 0.19.0

- **Santé : ce qui est chargé en mémoire, avec un bouton pour le décharger.** La page Santé montre la mémoire vive et la mémoire vidéo utilisées (mises à jour toutes les 4 secondes tant que la page est ouverte), puis chaque chose chargée : les modèles d'Ollama (taille, part sur la carte graphique, heure d'expiration), le serveur llama.cpp de Lutin (ou le routeur), le cache de ComfyUI. **Décharger** libère le modèle d'Ollama, arrête le serveur llama.cpp (il redémarre tout seul au prochain message) ou demande à ComfyUI de libérer ses modèles (désactivé pendant qu'il génère). En dessous, les programmes qui prennent le plus de mémoire vive, à titre d'information : Lutin ne ferme pas les programmes des autres.
- **Banc comparatif de moteurs et recommandation explicable.** `lutin bench-moteurs` (et la carte « Quel moteur pour ma machine ? » dans Réglages > Moteurs) fait tourner le même modèle sur Ollama et sur llama.cpp : chargement à froid, premier jeton, jetons/s, mémoire vive et vidéo, stabilité ; le résultat est conservé, partageable (sans chemin ni nom d'utilisateur) et « à refaire » quand le matériel ou la version d'un moteur change. La recommandation cite sa raison : d'après le banc (le plus rapide seulement s'il gagne d'au moins 10 % sur le plus simple), sinon d'après des règles générales marquées « pas encore mesuré ici ». Jamais lancé tout seul, rien n'est téléchargé. Les décisions Docker (image par défaut) et petit PC à carte intégrée restent à prendre sur des chiffres réels de plusieurs machines (`docs/BENCH_MOTEURS.fr.md`).
- **Cliquer une conversation existante ramène sur l'onglet Conversation**, comme « Nouvelle conversation ».

**English.** Engine comparison bench and explainable recommendation (`lutin bench-moteurs`, "Which engine for my machine?" card): same model on Ollama and llama.cpp, cached, shareable, redone when hardware or an engine version changes; the recommendation quotes its reason (the fastest only if it wins by at least 10 %, otherwise general rules flagged as not measured). Health page: what is loaded in memory, with an Unload button (Ollama models with size, GPU share and expiry; the llama.cpp server or router; ComfyUI's cache), live RAM/video-memory gauges refreshed every 4 s, and the programs using the most RAM (information only). Clicking an existing conversation now switches back to the Conversation tab.

## 0.18.0

- **Les cartes d'Ollama et de llama.cpp viennent du catalogue signé** (description, forces, faiblesses, site, version essayée avec Lutin), comme celles des serveurs externes ; le code qui les installe reste dans Lutin, et la page garde ses textes de secours si le catalogue est illisible.
- **Veille hebdomadaire des nouvelles versions de moteurs** (llama.cpp, Ollama, vLLM, SGLang, LocalAI, llama-swap) : un workflow ouvre une demande de fusion à relire quand une version sort. Il ne teste, ne signe, ne fusionne et ne publie rien tout seul (la clé de signature n'est pas sur GitHub). Une panne réseau n'est jamais prise pour une nouveauté.

**English.** Ollama and llama.cpp cards now come from the signed catalogue (description, strengths, limits, website, version tried with Lutin); the installation code stays in Lutin and the page keeps fallback texts if the catalogue is unreadable. Weekly watch for new engine versions: a workflow opens a pull request to review; it tests, signs, merges and publishes nothing by itself.

## 0.17.0

- **Catalogue des moteurs signé.** Les serveurs compatibles OpenAI que Lutin connaît (LM Studio, vLLM, SGLang, LocalAI, llama-swap) viennent d'un fichier de données **signé en Ed25519** (vérification en Python pur, sans dépendance, testée avec les vecteurs du RFC 8032), et non du code. Dans Réglages > Moteurs, la carte du serveur externe propose « Choisir un serveur connu… » : l'adresse habituelle se remplit, avec description, forces, limites et lien vers le site. Un catalogue modifié d'une virgule, mal signé ou qui ne respecte pas le schéma strict est refusé ; hors ligne, la copie livrée suffit ; une copie en ligne plus récente et bien signée est lue au plus une fois par semaine. Ajouter un serveur qui parle déjà OpenAI = une ligne de catalogue, sans nouvelle version de Lutin. Outil de signature `tools/signer_catalogue_moteurs.py` (clés privées hors dépôt, deux clés publiques embarquées pour pouvoir en changer). Documents `ENGINE_CATALOG.md` et `ENGINE_DEVELOPMENT.md`. Les cartes d'Ollama et de llama.cpp viennent encore du code.

**English.** Signed engine catalogue: the OpenAI-compatible servers Lutin knows (LM Studio, vLLM, SGLang, LocalAI, llama-swap) come from an Ed25519-signed data file (pure-Python verification, RFC 8032 test vectors), not from code. The external server card offers "Pick a known server…" (address, description, strengths, limits, website). A tampered, mis-signed or schema-breaking catalogue is refused; offline, the shipped copy is enough; a newer, properly signed online copy is read at most weekly. Adding an OpenAI-speaking server is one catalogue line, no new Lutin release. Signing tool `tools/signer_catalogue_moteurs.py` (private keys outside the repo, two embedded public keys for rotation). Docs `ENGINE_CATALOG.md` and `ENGINE_DEVELOPMENT.md`. The Ollama and llama.cpp cards still come from code.

*Publiées ensemble dans cette version, avec le catalogue :*

- **llama.cpp en mode routeur (expérimental).** Réglages > Moteurs > llama.cpp > « Réglages avancés » : un seul serveur sert plusieurs modèles (le modèle de conversation, celui des autres rôles, un modèle de recherche par le sens), chargés à la demande, sans redémarrer quand on change de modèle. Lutin écrit le fichier de préréglages (un par modèle installé, avec son projecteur d'images) et lance `--models-preset` ; nombre de modèles gardés en mémoire réglable. Proposé seulement si le llama-server installé connaît l'option. **Non vérifié sur du matériel réel** : testé contre un faux serveur ; si le serveur ne démarre plus, il suffit de décocher.
- **Clé d'accès générée** pour le llama-server que Lutin lance (`--api-key`, gardée dans `moteurs.json`, lisible par l'utilisateur seul) : personne d'autre sur la machine ou le réseau local ne peut lui parler sans elle.
- **Version de llama.cpp épinglée** (par exemple `b6500`) : « Installer » prend cette version, et aucune mise à jour n'est plus proposée. **Modèles « à experts »** : nombre de couches d'experts laissées au processeur (`--n-cpu-moe`), passé seulement si le programme le connaît.
- **Recherche par le sens avec n'importe quel moteur** : les embeddings passent par le moteur choisi (Ollama, llama.cpp en mode routeur, serveur externe) ; le modèle de recherche se télécharge depuis le même registre.
- **Grille de capacités** sur chaque carte de moteur (« Ce que ce moteur sait faire ») : natif / adapté / non supporté / non testé pour discuter, flux, bouton Arrêter, appels d'outils, raisonnement, images, embeddings, plusieurs modèles, téléchargement, installation.
- **Suite de conformité commune** (`tests/test_conformite_moteurs.py`) : les mêmes vérifications jouées sur les trois adaptateurs (Ollama, llama.cpp, serveur externe) contre un faux serveur ; chaque case « natif » ou « adapté » de la grille y est vérifiée, donc la grille ne ment pas.

**English.** llama.cpp router mode (experimental, not verified on real hardware: tested against a fake server): one server serves several models loaded on demand, no restart when switching (Settings > Engines > llama.cpp > Advanced). Generated access key for the llama-server Lutin starts (`--api-key`). Pinned llama.cpp version (no update offered) and expert layers kept on the processor for MoE models (`--n-cpu-moe`). Search by meaning works with any engine (embeddings go through the chosen engine). Capabilities grid on every engine card (native / adapted / not supported / not tested) and a common conformance suite run on the three adapters (Ollama, llama.cpp, external server): every native or adapted cell is verified.

## 0.16.9

- **La même page « Modèles » pour Ollama et pour llama.cpp.** Catalogue de Lutin, modèles « sans filtre », bibliothèque d'ollama.com (récents, populaires, filtres par usage, « seulement les légers », « cacher ce qui est trop gros »), précisions, installation d'un modèle par son nom : tout est identique d'un moteur à l'autre. Avec llama.cpp, un clic télécharge le même modèle **directement depuis la bibliothèque d'Ollama, sans Ollama** (adresse publique du registre, empreinte SHA-256 vérifiée, reprise si interrompu) et le range comme Ollama le fait, sous le même nom. La recherche Hugging Face reste dessous comme source supplémentaire. Ne restent propres à Ollama que le banc d'essai, la comparaison et la recherche de mises à jour des modèles.
- **Retrouver ses modèles et changer leur dossier.** Le bouton de la carte d'Ollama ouvre maintenant directement la fenêtre « Dossier des modèles d'Ollama » (il renvoyait vers l'onglet Modèles, où rien ne permettait de le faire). Un nouveau bouton « Retrouver mes modèles déjà téléchargés » cherche dans les emplacements usuels de tous les disques (`E:\IA\Ollama`, `D:\Models`…) les dossiers qui contiennent déjà des modèles et propose de les utiliser ; le diagnostic fait la même recherche, en arrière-plan, quand Ollama ne voit aucun modèle.

**English.** Same Models page for Ollama and llama.cpp (catalogue, uncensored models, ollama.com library, precisions, install by name); with llama.cpp a click downloads the same model straight from Ollama's registry without Ollama (SHA-256 verified, resumable) under the same name. The Ollama models-folder button now opens the folder window directly, with a “Find my already downloaded models” search across the usual places of every drive.

## 0.16.8

- **Les mêmes modèles sous Ollama et sous llama.cpp, sans rien retélécharger.** Les modèles déjà téléchargés par Ollama (y compris les modèles « sans filtre ») apparaissent dans la liste de llama.cpp **sous les mêmes noms** (`qwen3:8b`, `huihui_ai/qwen3-abliterated:4b`) : le fichier d'un modèle d'Ollama est un GGUF, llama.cpp le lit sur place. Aucune copie, aucune suppression possible depuis llama.cpp (lecture seule), le projecteur d'images est transmis pour les modèles qui voient. Sous Docker, ou si tu coupes le partage (`partager_ollama` dans `moteurs.json`), rien n'est partagé. Changer de moteur garde donc le même modèle choisi.
- **Les mêmes lignes de dossiers sur la carte de chaque moteur** (Réglages > Moteurs) : « Dossier d'installation » et « Dossier des modèles », avec la place libre. Pour llama.cpp les deux se règlent ici ; pour Ollama le dossier d'installation se choisit avant l'installation (Windows, option `/DIR` de son installateur — non vérifiée sur un vrai poste) et le dossier des modèles se change dans l'onglet Modèles, qui sait copier les modèles déjà téléchargés.

- **Correction importante : la mise à jour d'Ollama ne fait plus croire que les modèles sont perdus.** Le bouton « Mettre à jour » (0.16.7) désinstallait puis réinstallait Ollama ; celui-ci repartait sur son dossier de modèles par défaut, vide, alors que les modèles étaient intacts dans l'ancien dossier. Maintenant : (1) « Mettre à jour » installe la nouvelle version **par-dessus**, sans désinstaller ; (2) le dossier des modèles est retenu avant, puis rétabli (réglage de Lutin + variable de l'utilisateur) avant le redémarrage ; (3) Lutin retient le dernier dossier de modèles vu par Ollama et s'en sert quand il relance lui-même Ollama ; (4) si Ollama tourne mais ne voit aucun modèle alors que ce dossier en contient, le diagnostic le dit (« tes modèles ne sont pas perdus ») avec un bouton « Redémarrer Ollama ».
- **llama.cpp est réglé d'après la machine.** À chaque démarrage du serveur, Lutin lit l'aide du programme (les options changent d'une version à l'autre) et ne passe que celles qu'il connaît : le nombre de fils de calcul = les cœurs de la machine, et, sur carte graphique, `--fit` quand le modèle ne tient pas entièrement (jugement de Lutin, comme pour Ollama) pour que llama.cpp répartisse les couches entre la carte et le processeur au lieu de tout forcer sur la carte. Non vérifié sur un vrai poste : à tester avec un modèle plus gros que la carte.

**English.** Models already downloaded by Ollama (uncensored ones included) show up in llama.cpp's list under the same names, read in place (an Ollama model file is a GGUF): no copy, read-only, vision projector passed along. Engine cards now show the same two folder lines (installation, models) with free space; llama.cpp sets both there, Ollama's install folder is chosen before installing (Windows `/DIR`, unverified on real hardware) and its models folder in the Models tab.

## 0.16.7

- **Un modèle qui dit « je ne peux pas créer de fichier » est repris.** Avec llama.cpp, un modèle pouvait répondre qu'il ne peut pas créer de fichier directement, alors que l'outil d'écriture existe. Le détecteur « fichier demandé mais pas créé » ne reconnaissait pas non plus « fais-moi un démineur en html » (il attendait « fichier », « script »…). Maintenant les demandes de réalisation (jeu, page, site, programme, html, python…) sont reconnues, et un refus à tort (« je ne peux pas créer de fichier ») déclenche, une fois, un rappel : l'outil existe, appelle-le.
- **Chemins réseau (`\NAS\partage\dossier`) : l'antislash perdu est rendu.** Un petit modèle perd un des deux antislashs de tête en écrivant la commande ; elle échouait avec « chemin introuvable ». Si le chemin figure dans ta demande, la commande reprend la forme exacte.
- **Actualités : une vraie requête de recherche.** La phrase brute (fautes, politesse, date jj/mm/aaaa) partait telle quelle au moteur de recherche. Le modèle la transforme maintenant en 3 à 8 mots-clés (sinon elle est nettoyée), avec le mois et l'année plutôt qu'une date.
- **llama.cpp : des suggestions dans l'onglet Modèles.** Sept modèles vérifiés (Qwen3 1,7B à 14B, Gemma 3 4B, Llama 3.1 8B, Qwen2.5 Coder 7B), jugés pour ta machine comme la liste d'Ollama, téléchargeables d'un clic ; la recherche Hugging Face reste dessous.
- **Mises à jour des moteurs.** Lutin vérifie au plus une fois par 24 h (en arrière-plan, rien n'est installé tout seul) si llama.cpp (installé par Lutin) et Ollama (local) ont une version plus récente. L'avis apparaît sur la carte du moteur dans Réglages > Moteurs, avec un bouton « Mettre à jour » ; pas de notification en haut de la page.
- **« Nouvelle conversation » revient sur l'onglet Conversation.**

**English.** A model that wrongly says it cannot create files is told once that the write tool exists (and “make me a minesweeper in html” is recognised as a creation request); network (UNC) paths that lose a leading backslash are repaired from your request; news searches use real keywords instead of the raw sentence; llama.cpp gets machine-rated model suggestions; engines (llama.cpp, Ollama) check for updates at most every 24 h and show it on their card in Settings > Engines with an Update button; “New conversation” returns to the Conversation tab.

## 0.16.6

- **Choix du programme de llama.cpp : la détection du matériel est attendue.** L'essai réel sur un poste à carte NVIDIA a réussi (CUDA installé, ~247 jetons/s avec un modèle de 4 milliards, appel d'outil compris) mais a montré un défaut : la détection du matériel démarre en arrière-plan et un premier appel immédiat (l'essai en ligne de commande, ou un clic sur « Installer » juste après le lancement) pouvait la croire absente et choisir la version « processeur ». Le choix attend maintenant la fin de la détection (25 secondes au plus).

**English.** Choosing llama.cpp's build (CUDA, Vulkan, CPU) now waits for the background hardware detection (up to 25 s) instead of falling back to CPU. The first real trial on an NVIDIA PC passed.

## 0.16.5

- **`/compact` en mode fiche de suivi : plus rien ne disparaît sans être passé dans la fiche.** Avant, la fiche ne lisait pas les derniers messages s'ils étaient moins de six, puis tout sauf le dernier échange était retiré : la fiche était en retard et tu perdais le fil. Maintenant la fiche lit **tout** ce qui va sortir (par lots, sans en sauter quand il y en a beaucoup) ; si elle n'y arrive pas (modèle absent), **rien n'est retiré** et un message le dit. Et la commande n'est plus un simple « résumé déguisé » : au moins la moitié des messages sort, mais les **vrais messages récents restent tels quels** (jusqu'au quart de la fenêtre), la fiche gardant le fil du reste. Le passage normal de la fiche lit aussi par lots au lieu de couper les échanges trop longs.
- **Accord automatique suspendu après une lecture web : un bouton pour le rétablir.** La carte d'accord propose « Accepter et réactiver l'accord automatique » (avec l'avertissement du risque) : la suite de la demande repart en accord automatique. Les cases suspendues sont maintenant barrées et marquées « ⏸ suspendu » (elles redeviennent normales à la demande suivante, ou tout de suite si tu réactives).
- **Modèles pour Mac (MLX) : plus proposés ailleurs que sur un Mac**, ni dans la recherche de la bibliothèque, ni dans les variantes de précision (Ollama refuse de les lancer ; jusque-là seul l'échec de téléchargement les retirait de la liste).
- **Menu « ⋯ » d'une conversation : ses dossiers.** Le dossier de travail et les dossiers où elle a créé des fichiers s'ouvrent en un clic dans l'explorateur (Windows, macOS, Linux avec écran). Sous Docker ou sur un serveur sans écran, la page ne peut pas ouvrir de dossier : le même bouton copie le chemin.

**English.** `/compact` in tracking-sheet mode now reads everything that leaves the context (in batches) and removes nothing if the sheet could not be updated; it keeps the real recent messages (up to a quarter of the window) instead of only the last exchange. A suspended auto-approval (after reading the web) can be re-enabled from the approval card, and suspended checkboxes are clearly marked. Mac-only (MLX) models are hidden elsewhere than on a Mac. The conversation “⋯” menu opens its work folders (path copy under Docker).

## 0.16.4

- **Où s'installe llama.cpp : le dossier équivalent à celui d'Ollama est proposé, et tu peux choisir ailleurs.** Si tu as déplacé le dossier des modèles d'Ollama (par exemple `D:/IA/ollama/models`), la page propose `D:/IA/llama.cpp` (même disque, place libre affichée) ; sinon le dossier de Lutin sert, comme avant. Dans Réglages > Moteur, la fiche de llama.cpp montre le dossier utilisé (programme + modèles + journal), un bouton « Utiliser le dossier proposé », et un champ pour n'importe quel autre chemin ; une confirmation prévient avant d'installer dans le dossier de Lutin si un dossier à côté d'Ollama était proposé. `lutin essai-moteur` pose la même question et accepte `--dossier`. Changer de dossier est refusé tant que llama.cpp est installé (rien n'est déplacé en douce : désinstalle d'abord, tes modèles restent).
- **Essai Linux en CI corrigé** : il installe `libgomp1` comme le fait déjà l'image de Lutin.

**English.** llama.cpp's install folder: the one equivalent to Ollama's is proposed (same disk, free space shown) and you can pick another; `lutin essai-moteur --dossier`; the Linux CI trial now installs `libgomp1`.

## 0.16.3

- **`lutin essai-moteur llamacpp` : un essai réel de llama.cpp, avec un rapport.** Les tests de Lutin utilisent de faux serveurs ; cette commande fait pour de vrai, sur la machine où elle tourne, ce que Lutin fait avec un moteur : installer le programme adapté à la carte graphique, télécharger un modèle (avec ton accord et sa taille annoncée), démarrer le serveur, vérifier qu'il répond, tenir une conversation en flux (premier jeton, jetons par seconde), faire un appel d'outil, puis arrêter proprement. Chaque étape dit ce qui marche ou non ; sous Linux, un serveur qui ne démarre pas est expliqué (bibliothèques manquantes, glibc). Le rapport est écrit dans le dossier de données de Lutin (`essais/`). Options : `--modele auteur/dépôt/fichier.gguf`, `--modele-test` (1 Mo : prouve seulement que le serveur démarre et répond), `--variante cuda|vulkan|cpu`, `--sans-outils`, `--oui`. Guide : `docs/TRIALS.fr.md`.
- **llama.cpp : le serveur est « prêt » quand `/health` répond « ok »** (il répond 503 pendant le chargement du modèle) au lieu de la simple présence de `/v1/models`.
- **Installation CUDA sous Windows : les bibliothèques de l'archive séparée rejoignent le programme** si celui-ci se trouve dans un sous-dossier de son archive.
- **Image Docker : `libgomp1` ajouté** (images légère et complète). Constat de l'essai automatique : le programme de llama.cpp publié pour Ubuntu installé et lancé dans `python:3.12-slim` ne démarrait pas faute de `libgomp.so.1` (OpenMP). Un serveur qui ne démarre pas faute d'une bibliothèque nomme maintenant le paquet à installer.
- **Essai automatique sur Linux** (`.github/workflows/moteurs.yml`, à part de la CI principale, jamais bloquant) : llama.cpp installé et lancé avec un modèle minuscule dans `python:3.12-slim`, l'image de Lutin « légère ». Il dit si le programme publié pour Ubuntu démarre avec la glibc de Debian.

**English.** `lutin essai-moteur llamacpp`: a real trial of llama.cpp with a report (install, model download with your consent, startup, streaming chat, tool call, shutdown); readiness through `/health`; CUDA libraries placed next to the program; a non-blocking Linux CI trial in `python:3.12-slim`.

## 0.16.1

- **« Arrêter » rend toujours la main.** Un modèle qui ne renvoyait plus rien (chargement bloqué, carte graphique prise par une génération d'image qui s'éternise) ne voyait jamais le bouton : « Réflexion en cours » restait en rouge et il fallait redémarrer Lutin. La réponse du modèle est maintenant lue de façon interruptible, ouverture de la connexion comprise : Arrêter la coupe tout de suite et le serveur de modèle cesse de générer. Filet : si un tour (un outil figé, par exemple) ne s'arrête pas 20 s après Arrêter, il est abandonné, la conversation est libérée et le tour abandonné n'écrira plus rien dedans. Le démarrage de ComfyUI écoute aussi Arrêter.
- **La recherche web ne dépend plus d'un seul moteur.** DuckDuckGo limitait les requêtes au bout de quelques essais (puis restait muet plusieurs minutes) et le modèle répondait en boucle qu'il était bloqué. Maintenant : DuckDuckGo, puis Bing en relais ; un moteur muet est laissé de côté 10 minutes ; une même recherche répétée vient du cache ; et si plus rien ne répond, le modèle reçoit la consigne de ne pas insister, de le dire à l'utilisateur et de répondre avec ce qu'il sait (ou de lire une page par son adresse).
- **Configurer depuis un autre appareil, hors Docker.** Accès > Administration à distance : un réglage (activable depuis la machine seulement, ou avec `lutin securite --admin-distance on`) qui ouvre la configuration (supprimer des fichiers créés, dossiers de travail, extensions, connecteurs MCP, moteurs) à tout appareil déjà admis. Les refus disent où l'ouvrir. Le niveau d'accès lui-même reste modifiable depuis la machine seulement.
- **Mise en page des grands écrans.** Les réglages, les modèles et les bulles de conversation ne s'arrêtent plus à 900 px : ils suivent la largeur de l'écran (jusqu'à environ 1 800 px pour les pages, 1 500 px pour les bulles) et, à partir de 1 500 px, les moteurs, extensions et connecteurs s'affichent en colonnes côte à côte. Téléphone et petites fenêtres : rien ne change.

**English.** Stop always gives control back (interruptible model stream, abandoned stuck turns); web search falls back from DuckDuckGo to Bing with pauses, cache and a clear instruction when nothing answers; remote administration for non-Docker installs (Access > Remote administration); wide-screen layout.

## 0.16.0

- **Deux nouveaux moteurs : llama.cpp et tout serveur compatible OpenAI.** Réglages > Moteur montre chaque moteur avec sa description, ses forces et ses faiblesses, son état et **seulement ce qui est possible avec lui** (avec la raison du reste : Docker, système, mode hors ligne). Lutin traduit à la frontière : messages, appels d'outils (reconstitués morceau par morceau), images, réflexion, comptes de jetons et vitesse ; conversation, outils, mémoire, missions, connecteurs MCP et actualités fonctionnent avec le moteur choisi.
- **llama.cpp géré par Lutin.** Installation du programme officiel adapté à la machine (CUDA / Vulkan / processeur / Metal, empreinte vérifiée, sans droits administrateur), démarrage à la demande avec le modèle et le contexte choisis, arrêt, désinstallation (les modèles sont gardés), ou connexion à un `llama-server` déjà lancé (adresse). Modèles GGUF : recherche sur Hugging Face, choix de la quantification, téléchargement, suppression.
- **Ollama : installer, désinstaller, réinstaller, démarrer, arrêter** depuis Réglages > Moteur sous Windows (installateur officiel, signature vérifiée, modèles gardés) ; sous Linux et Mac la page donne la commande ; sous Docker elle explique que c'est un autre conteneur.
- **L'interface suit le moteur.** Avec un autre moteur, ce qui n'existe qu'avec Ollama (bibliothèque, précisions, comparaison, calibrage des cœurs, charge de la machine) disparaît et l'onglet Modèles montre les modèles de ce moteur avec ce qu'il permet (télécharger, utiliser, supprimer). Le modèle utilisé avec chaque moteur est retenu quand on change. Un diagnostic propre à chaque moteur remplace celui d'Ollama. Les opérations en cours (installation, téléchargement) apparaissent dans la barre bleue.
- **Serveur compatible OpenAI** (LM Studio, vLLM, Strata…) : adresse et clé facultative dans Réglages > Moteur ; la clé n'est jamais renvoyée à la page.

**English.** Two new engines: llama.cpp (installed, started and fed with GGUF models by Lutin, or connected by address) and any OpenAI-compatible server; Settings > Engine shows each engine's strengths, weaknesses and only what is possible with it; Ollama can be installed, uninstalled and reinstalled from the page on Windows; the interface follows the engine.

## 0.15.1

- **Docker : configurer depuis la page.** Supprimer un fichier créé, ajouter un dossier de travail, une extension ou un connecteur est refusé depuis un navigateur qui n'est pas « sur la machine » ; or, sous Docker, il ne l'est jamais. Nouvelle variable `LUTIN_ADMIN_TOUS=1` (dans le docker-compose) : toute personne déjà admise (appareil appairé par PIN, ou utilisateur du proxy) peut alors configurer depuis la page. Elle n'a d'effet que dans Docker, et ne change pas le niveau d'accès lui-même. Les refus disent maintenant comment faire, et la documentation Docker détaille le risque (lecture et écriture des dossiers montés, programmes lancés dans le conteneur).

**English.** `LUTIN_ADMIN_TOUS=1` (Docker only) lets everybody already admitted configure from the page (delete created files, folders, extensions, connectors); refusals now say how to enable it.

## 0.15.0

- **Couche « moteur » : Lutin n'est plus lié à Ollama.** Tout ce que Lutin demande à un moteur de modèles (discuter en flux ou d'un coup, dire s'il répond, ses capacités, la mémoire prise) passe par une interface commune (`moteurs.py`). Ollama reste le moteur par défaut et fonctionne exactement comme avant ; un autre moteur (llama.cpp server, LM Studio, vLLM, Strata… par leur interface compatible OpenAI) pourra prendre sa place sans toucher au reste : conversation, outils, mémoire, missions, connecteurs MCP. La prochaine étape ajoutera ce moteur compatible OpenAI. Un test fait déjà tenir toute une conversation par un faux second moteur.
- **Réglages > Moteur.** Un choix du moteur (Ollama pour l'instant) avec son explication ; il se dégrisera quand un second moteur sera disponible. Nouveau réglage `moteur` (Ollama par défaut ; un réglage inconnu retombe sur Ollama).
- **La mémoire des longues conversations passe dans l'onglet Mémoire** (méthode résumé/fiche, part du contexte, recherche par le sens, mise à jour de la fiche) : c'est ce que Lutin retient, donc sa place logique. Les dossiers et les données restent dans Réglages.

**English.** Engine layer: everything Lutin asks a model engine goes through a common interface; Ollama stays the default and works as before; an OpenAI-compatible engine (llama.cpp, LM Studio, vLLM, Strata…) comes next. New Settings > Engine; long-conversation memory moved to the Memory tab.

## 0.14.2

- **Réglages verrouillés sous Docker : la page dit quoi faire.** Dans Docker, le navigateur n'est jamais « sur la machine » de Lutin : sans administrateur déclaré, les extensions, les dossiers de travail et les connecteurs MCP sont verrouillés. Le message explique maintenant les deux solutions (niveau proxy + `LUTIN_ADMINS`, ou `docker exec lutin lutin …`), et la documentation Docker les détaille.
- **Connecteurs MCP : comment en ajouter.** La section affiche des exemples (programme ou adresse), explique ce qui se passe ensuite (liste des outils à cocher) et, quand la page est verrouillée, pourquoi et comment faire autrement. Nouvelle commande `lutin mcp` (lister, ajouter, retirer, actualiser, autoriser, interdire, ecriture) pour tout faire en ligne de commande, notamment dans Docker.
- **Modèle réservé aux Mac (MLX).** « this model requires MLX support » devient une explication claire (ce modèle est fait pour la puce Apple, choisis-en un autre) et le modèle est retiré de ta liste.

**English.** Locked settings under Docker now explain what to do; MCP connectors: examples, explanations and a new `lutin mcp` command; a clear message for Mac-only (MLX) models.

## 0.14.1

- **Bibliothèque d'Ollama : plus de doublons.** Un modèle n'apparaît qu'une fois, y compris avec « Voir la suite ». Les étiquettes qui ne sont pas des tailles (« 1m », une longueur de contexte) ne sont plus proposées à l'installation.
- **Téléchargement d'un modèle introuvable.** « pull model manifest: file does not exist » devient une explication claire (ce modèle ou cette taille n'existe pas, vérifie le nom sur ollama.com), et le modèle n'encombre plus ta liste.
- **Réponses de l'assistant à nouveau en vert pâle** (les tiennes restent bleues).
- **Demander un fichier après une recherche web.** Quand tu demandes de créer un fichier (docker-compose, script, configuration…) et que le modèle termine sans avoir appelé un outil d'écriture (il a cherché sur le web puis s'est arrêté, ou il montre le contenu en te disant de le copier), Lutin le relance une fois pour qu'il écrive vraiment le fichier. Le prompt système rappelle aussi d'utiliser l'outil d'écriture, même après une recherche.

**English.** Library list without duplicates or fake sizes; a clear message when a model does not exist; assistant replies back to pale green; when a file is requested and the model stops without writing it (for example after a web search), Lutin nudges it once to really write the file.

## 0.14.0

- **Connecteurs MCP.** Brancher un serveur d'outils (Home Assistant, GitHub, fichiers…) depuis Automatisation > Connecteurs MCP : programme lancé par Lutin (stdio) ou adresse (HTTP). Aucun outil n'est donné au modèle sans être coché un par un ; lecture seule par défaut ; un outil qui modifie quelque chose demande ton accord à chaque appel (jamais d'accord automatique) et est inscrit au journal ; le retour des outils est traité comme du contenu web (jamais affiché brut, jamais obéi, accord automatique suspendu ensuite). Seul le configurateur peut en ajouter. Un serveur de démonstration est fourni (`python -m lutin.mcp_demo`). Les extensions existantes (Telegram, courriel, X, ComfyUI) ne changent pas.
- **Bibliothèque d'Ollama plus facile.** Filtres par usage (agent, code, images, réflexion, recherche dans les documents), par famille, « seulement les légers » ; chaque taille indique si elle tient sur ta machine (estimation) et peut être masquée si trop grosse ; lien vers la page de chaque modèle ; les tailles déjà installées sont marquées.
- **Anciens modèles.** Quand le catalogue dit qu'un modèle est remplacé par un autre déjà installé, Lutin propose de supprimer l'ancien (jamais sans clic). Catalogue en version 6.
- **Actualités avec un petit modèle.** « Les news du jour » : Lutin cherche et lit lui-même quelques sources, puis le modèle (10 milliards de paramètres ou moins) ne fait que résumer, sans outil. Un grand modèle garde la main.
- **Barre d'état unique.** Les tâches de fond (fiche de suivi, calibrage, mesures de modèles) et la mémoire prise par le modèle chargé apparaissent dans le bandeau bleu, comme les téléchargements.
- **Extensions grisées et QR code.** Quand les réglages sont verrouillés (page ouverte depuis un autre appareil, ou derrière un proxy sans administrateur déclaré), la page dit pourquoi et comment faire (LUTIN_ADMINS) au lieu de griser sans explication. Correction d'une course : ouvrir l'onglet Accès avant la fin du premier chargement ne montrait ni PIN ni QR code. Derrière un proxy, la page explique qu'il n'y a ni PIN ni QR code à ce niveau.
- **Finition de l'interface.** Typographie, onglets en pastilles, cartes en relief, bulles de conversation, zone de saisie, boutons homogènes.

**English.** MCP connectors (tool by tool permissions, read-only by default, approval at every modifying call, results treated as untrusted); easier Ollama library (filters by use and family, fit estimate per size, page links); old-model cleanup proposals; guided news for small models; a single status bar for background tasks and memory; the locked-settings explanation and a QR code race fix; interface polish.

## 0.13.12

- **Un modèle qui raconte avoir agi sans le faire est repris (fichier, commande, recherche web, image, mémoire).** Dans une conversation réelle, un petit modèle répondait « J'ai créé le fichier docker-compose.yml » sans appeler l'outil d'écriture, jusqu'à confirmer que le dossier était vide… puis à recommencer. Quand la réponse affirme une écriture alors qu'aucun outil d'écriture n'a été appelé depuis ta demande, Lutin le lui fait remarquer (une seule fois), sans garder l'affirmation fausse dans la conversation. Le contrôle est prudent : verbe au passé à la première personne, outil réellement disponible, code cité ignoré, objet de type fichier exigé pour les écritures.

**English.** When a model claims to have created a file without calling any write tool, Lutin points it out once and asks it to really do it.

## 0.13.11

- **Tout fichier créé par Lutin est tracé.** Un fichier écrit avec l'outil d'écriture (par exemple un `docker-compose.yml`) n'apparaissait nulle part : ni sous le message, ni dans Réglages > Fichiers créés par Lutin. Il y figure désormais dès sa création, et le modèle reçoit le chemin complet du fichier (il peut dire précisément où il est). Un fichier simplement modifié n'est pas compté comme créé.

**English.** Every file created by Lutin is now tracked (card under the message, Settings > Files created by Lutin) and the model is given the full path.

## 0.13.10

- **Modèle qui ne produit rien : dernier essai sans outils, et message honnête.** Sur le mini-PC, `granite4:tiny-h` ne répondait rien trois fois de suite alors que la conversation n'était pas pleine (4,7k sur 8,2k jetons), et Lutin accusait la fenêtre de contexte. Le troisième essai se fait maintenant **sans déclarer les outils** (certains petits modèles se taisent quand ils sont déclarés). Les messages disent la vérité : « n'a rien écrit » (et non « a réfléchi ») s'il n'y a pas eu de réflexion, et la fenêtre de contexte n'est citée comme cause que si elle est vraiment pleine (85 % ou plus) ; sinon c'est dit que ce modèle ne répond pas correctement ici. La raison de fin donnée par Ollama est notée dans le journal.

**English.** A model producing nothing now gets a last attempt without tools, and the messages no longer blame the context window unless it is really full.

## 0.13.9

- **Point jaune quand l'assistant attend une action de ta part** (accord à donner, question « fiche de suivi ou résumé ? », mission bloquée sur une question) : à côté de la conversation dans la liste et sur l'onglet Conversation, quel que soit l'onglet ouvert. Il passe avant le point bleu (il travaille) et le vert (terminé).
- **Nom de modèle trop long : les pastilles restent visibles.** Dans l'onglet Modèles, le « … » coupait la fin de la ligne et cachait la pastille « Adapté / Trop gros / ★ actif ». Maintenant c'est le nom qui est raccourci (lisible en entier au survol), les pastilles restent à la fin de la ligne.
- **Plus de mémoire disponible : la demande est gardée et reprise toute seule.** Au lieu de « Demande suspendue… écris continue », Lutin garde ton message, indique ce qui manque, vérifie la mémoire toutes les 5 secondes (jusqu'à 15 minutes) et répond dès que la place revient. « Arrêter » annule l'attente ; au bout du délai, l'ancien message s'affiche et la demande reste gardée. Les missions gardent l'ancien comportement.
- **Recherche web plus utile pour les petits modèles** : `web_chercher` joint maintenant le début des 3 premières pages (lues en parallèle, 12 secondes au plus) et demande une synthèse sourcée plutôt qu'une liste de liens. Option `lire` de l'outil (0 à 5) pour changer le nombre de pages lues. **Ces résultats ne sont jamais recopiés dans la conversation** : la recherche et la lecture web servent à l'assistant, qui en tire sa réponse ; la conversation n'affiche que « résultat transmis à l'assistant, non affiché » (les erreurs restent visibles).

**English.** Yellow dot when the assistant waits for you; model pills no longer hidden by long names; a request blocked for lack of memory is kept and resumed automatically when memory is back; web search joins the start of the first pages so small models can summarise instead of listing links.

## 0.13.8

- **Plus d'avertissement « seulement 0 % du modèle tient sur la carte graphique » à chaque réponse** sur une machine sans carte graphique (tout tourne sur le processeur, c'est connu). Sur une machine avec carte, il n'apparaît plus qu'une fois par modèle et par demi-heure.
- **Banc d'essai : une bonne réponse n'est plus comptée fausse à cause d'un point final.** « Le résultat est 14. » était refusé (le point collé au 14) ; la valeur est aussi acceptée en première ligne suivie d'une explication. Les scores de code des petits modèles étaient sous-estimés (jusqu'à 1/8 pour des réponses justes) : relance tes mesures.
- **Mission longue : on voit ce qu'elle fait.** Pendant un tour (des minutes sur une petite machine), la bannière disait seulement « tour 1 en cours… » : on ne savait pas si quelque chose se passait. Elle indique maintenant ce que fait le modèle (« il réfléchit… 1 200 caractères », « il écrit sa réponse… », l'outil lancé) et garde un « Activité récente » avec les dernières actions et leurs résultats. Le modèle reçoit aussi la consigne de terminer chaque tour par un court point d'avancement écrit dans la conversation.
- **Huit modèles de plus au catalogue**, avec leur version sans filtre quand elle existe : Granite 4.1 (3 et 8 milliards, + versions sans filtre), Granite 4 hybride 3 milliards, Qwen 3 4 milliards « sans réflexion » (`qwen3:4b-instruct`), Ministral 3 (3 milliards, avec images), Phi-4 mini sans filtre. `granite4:tiny-h`, mesuré le plus rapide d'un mini-PC Core Ultra (25 jetons/s, outils 6/6), devient le polyvalent conseillé sans carte graphique. Il n'existe pas de version sans filtre vérifiée de `granite4:tiny-h`, du Granite hybride ni de Ministral 3.

**English.** No more “0% of the model fits on the graphics card” warning on every answer on a machine without a graphics card (once per model per half hour otherwise). A correct benchmark answer is no longer marked wrong because of a final period. Eight more models in the catalogue, with the unfiltered version when one exists; `granite4:tiny-h` becomes the recommended all-rounder without a graphics card.

## 0.13.7

- **Le bandeau de téléchargement ne prend plus la moitié de l'écran.** Les lignes « ✔ modèle installé » y héritaient d'une règle du bandeau « nouvelle version » (largeur de base 260 px), qui dans un bandeau en colonne devenait 260 px de **hauteur**. Le bandeau est maintenant une bande fine (30 % de l'écran au plus, défilable), et un test mesure sa hauteur à chaque état (en cours, terminé, échec).

**English.** The download banner no longer takes half the screen: “installed” lines inherited a 260 px base width that became 260 px of height in a column banner.

## 0.13.6

- **« Impossible de télécharger : open …\.ollama\id_ed25519 »** : Ollama garde une clé d'identité (`id_ed25519`) dans son dossier `.ollama`, à côté de son historique et **séparément du dossier des modèles**. Si ce dossier est supprimé ou déplacé pendant qu'Ollama tourne, il ne la retrouve plus et refuse de télécharger. Ce n'est pas un chemin écrit en dur dans Lutin : c'est un fichier qu'Ollama recrée à son démarrage. L'erreur est maintenant expliquée en clair, et le bandeau de téléchargement propose **« Redémarrer Ollama puis réessayer »**.

- L'onglet **Santé** (disques) et la jauge de l'onglet Modèles mesurent le disque du dossier que **Ollama utilise vraiment** et se remettent à jour quand il change ; un test le vérifie.

**English.** When Ollama's `.ollama` folder (holding its identity key, separate from the models folder) is deleted while it runs, downloads fail with a raw `id_ed25519` error. It is now explained, with a “Restart Ollama then retry” button.

## 0.13.5

- **Lutin demande à Ollama où sont ses modèles.** Quand tu changes le dossier des modèles dans l'application Ollama, Lutin ne le voyait pas (le réglage n'est pas visible de l'extérieur). Il lit maintenant le chemin réel dans le Modelfile d'un modèle installé (ligne `FROM …/blobs/sha256-…`), donc la jauge de disque, la page Emplacements et la copie vers un autre dossier suivent ce qu'Ollama utilise vraiment.
- **On peut supprimer le modèle actif**, même s'il est le seul installé : Lutin bascule sur un autre modèle de discussion s'il y en a un, sinon la bannière d'ouverture dit qu'il faut en installer un. Avant, il refusait (« change de modèle actif avant de supprimer »), ce qui bloquait quand on n'en avait qu'un.
- **Copier un lien depuis un bloc de code colle bien quelque chose** : le texte copié commençait et finissait par un retour à la ligne (celui des ``` du bloc), et un lien ainsi collé est refusé par la barre d'adresse du navigateur ou de l'explorateur. Les lignes vides autour du bloc disparaissent, à l'écran comme à la copie. La copie est aussi plus robuste (champ temporaire placé dans la fenêtre ouverte, texte sélectionné), et si le navigateur la refuse, le texte est proposé sélectionné pour un Ctrl+C manuel.
- **Le suivi des téléchargements passe dans le bandeau bleu** (comme « Nouvelle version disponible ») au lieu d'une pastille qui encombrait la barre du haut : modèle, pourcentage, Mo, barre de progression, « Réessayer » et « Fermer » en cas d'échec.

**English.** Lutin asks Ollama where its models are (read from a model's Modelfile), so a models folder changed in the Ollama app is seen. The active model can be deleted (Lutin switches to another one if any). Download tracking now uses the blue banner (like “new version available”) instead of a crowded pill in the top bar.

## 0.13.4

- **Le modèle de recherche par le sens (nomic-embed-text) n'apparaît plus dans les listes de choix de modèles** : ni dans le sélecteur de la conversation, ni dans le choix du petit modèle annexe, ni dans la commande /modele, ni dans la comparaison. Il travaille en fond et ne sait pas discuter : le choisir donnait une conversation muette. Lutin le refuse aussi côté serveur, et le diagnostic d'ouverture ne le compte plus comme un modèle de discussion (s'il est le seul installé, la bannière « aucun modèle installé » apparaît bien).

**English.** The meaning-based search model (nomic-embed-text) no longer appears in model pickers (conversation selector, side-task model, /modele command, comparison), and the server refuses it as a chat model.

## 0.13.3

- **On voit quelle précision est installée** : chaque modèle installé affiche sa précision sur sa ligne (« 4 bits (Q4_K_M) », « 8 bits (Q8_0) »…), lue dans Ollama. Dans le panneau **Précision**, la variante réellement installée est marquée « ✔ installé » ou « ★ actif », y compris la variante par défaut quand tu as installé le modèle sans préciser, et le panneau dit « Installé actuellement : … ».
- **Les téléchargements se suivent depuis la barre du haut** : une pastille affiche l'avancement (« ⬇ qwen3:8b-q8_0 45 % », plusieurs à la fois en « +N »), l'échec avec sa cause (clic = fermer et ouvrir les modèles) et « ✔ installé » à la fin, quel que soit l'onglet ouvert.
- **Banc d'essai plus fiable et plus lisible** : une vingtaine de questions au lieu de onze (outils 6 : lire, chercher, lister, lancer une commande, et deux questions qui ne doivent PAS appeler d'outil ; code 8 ; français 4 ; consignes 4 : JSON strict, un mot, trois mots, liste numérotée de 4). Dans la comparaison, la légende explique que « 3/4 » veut dire trois questions réussies sur quatre, que la vitesse n'est pas une réussite, et la case donne en infobulle la question ratée ; un détail question par question est dépliable, avec un rappel honnête de la portée de ces mesures (indicateur, pas ta vraie tâche).

**English.** The installed precision (4-bit, 8-bit…) is shown on each model line and marked “installed/active” in the Precision panel. A pill in the top bar tracks downloads (progress, failures with their cause, completion). The benchmark has about twenty questions instead of eleven, and the comparison explains what “3/4” means, shows which question failed and offers a question-by-question detail.

## 0.13.2

- **Mode fiche de suivi : la fenêtre de contexte ne reste plus saturée.** Le retrait du début attendait que le scribe ait lu les messages ; si le scribe échouait (par exemple parce que le modèle manquait de mémoire pendant une génération d'image), rien n'était jamais retiré et la conversation grossissait jusqu'à dépasser la fenêtre (47k / 37k) : le modèle ne répondait plus. Maintenant, au-delà de 60 % de la fenêtre (ou 80 % d'après le chiffre réel d'Ollama), le début sort quand même (archivé, retrouvable avec « rappeler »), même si la fiche a du retard.
- **Plus jamais de silence** : une demande qui se termine sans aucune ligne de réponse ni d'erreur le dit maintenant (fenêtre pleine, manque de mémoire…) et rappelle quoi faire. La jauge affiche ⚠ quand le contexte dépasse la fenêtre.
- **Le bouton « Précision » existe aussi pour les modèles sans filtre** (huihui_ai/…) : leurs variantes 8 bits, etc., sont lues sur la page de leur auteur.

**English.** Tracking-sheet mode: the context window no longer stays saturated (removal of old messages no longer waits for the scribe once the window is over 60% full, or 80% by Ollama's real count). A request that ends without any written answer now says so and what to do. The “Precision” button also works for unfiltered (author-namespaced) models.

## 0.13.1

- **Recherche par le sens : l'installation du modèle se suit et se gère comme celle de tous les modèles.** Avant, le bouton « Installer » restait enfoncé sans rien afficher (la page ne se mettait pas à jour pendant le téléchargement) et le modèle n'était pas supprimable depuis les réglages. Maintenant : barre de progression avec le pourcentage et les Mo, « Réessayer » en cas d'erreur, « Supprimer ce modèle » une fois installé (avec confirmation), et le téléchargement continue si tu fermes la page.
- Le modèle de recherche (nomic-embed-text) apparaît dans l'onglet Modèles avec la puce « 🔎 utilisé pour la recherche par le sens » (ou « option décochée »), sans bouton « Utiliser » ni banc d'essai : il ne sert pas à discuter. Son téléchargement s'y suit comme pour les autres modèles.

**English.** Meaning-based search: the model install is now tracked and managed like any model: progress bar with percentage and MB, “Retry” on error, “Delete this model” once installed, and it continues if you close the page. The search model shows in the Models tab with a “🔎 used for meaning-based search” badge, without “Use” or benchmark buttons.

## 0.13.0

- **« ⚡ Optimiser pour cette machine »** (Réglages > Vitesse) : Lutin mesure, avec le modèle choisi, le débit d'écriture pour plusieurs nombres de cœurs du processeur (le tiers, la moitié, les deux tiers, la totalité), deux fois chacun, et propose le plus petit nombre qui écrit à moins de 3 % du meilleur (à vitesse égale, il reste des cœurs pour le reste de la machine). Rien n'est appliqué sans ton clic. 2 à 4 minutes.
- **Petit modèle pour les tâches annexes** (option, désactivée par défaut) : mise à jour de la fiche de suivi, résumés et titres peuvent passer par un modèle plus petit et plus rapide. Il faut de la place en mémoire pour deux modèles, et `OLLAMA_MAX_LOADED_MODELS` ne doit pas valoir 1 (sinon Ollama recharge un modèle à chaque changement).
- **Réflexion pendant les outils** (option, comportement actuel par défaut) : « seulement avant la première réponse » évite de refaire la réflexion à chaque retour d'outil.
- Non fait volontairement : raccourcir les descriptions des outils (≈ 2 600 jetons). Elles guident les modèles, et comme elles sont au début de la requête, Ollama les garde en cache : le gain serait faible pour un risque de dégrader les réponses.

**English.** “⚡ Optimise for this machine” (Settings > Speed): measures write speed with several core counts and suggests the smallest one within 3% of the best; nothing is applied without your click. Optional small model for side tasks (tracking-sheet update, summaries, titles) and optional “thinking only before the first answer” while using tools; both off by default.

## 0.12.0

- **Choisir la précision d'un modèle (4 bits, 8 bits…)** : le bouton **Précision** de chaque modèle de l'onglet Modèles liste ses variantes (`q4_K_M`, `q8_0`, `fp16`…) lues sur ollama.com, avec leur taille, ce que cette machine en pense (« Adapté », « Limite », « Trop gros ») et ce que la précision change. Plus elle est basse, plus le modèle est petit et rapide, mais moins fin : surtout pour les petits modèles et leurs appels d'outils.
- **Mode « petite machine »** : sur une machine sans carte graphique ou à peu de mémoire, une bannière propose d'un clic des réglages adaptés (fenêtre de contexte 24 576 → 12 288 jetons, réflexion coupée par défaut). Jamais imposé, et « Ne plus proposer » le range.
- **Comparer des modèles côte à côte** : coche ⚖ sur des modèles installés, **Tester et comparer la sélection** lance le banc complet sur chacun l'un après l'autre, et un tableau montre vitesse, outils, code, français et consignes (le meilleur de chaque colonne en gras).

**English.** Choose a model's precision (4-bit, 8-bit…) with a **Precision** button listing the variants read on ollama.com, with sizes and how well this machine copes. A “small machine” banner offers one-click settings (smaller context window, thinking off by default) on machines without a graphics card or with little memory. Compare models side by side: tick ⚖, run the full benchmark on each, and read speed, tools, code, French and instructions in one table.

## 0.11.5

- **Outil « executer » : une commande avec un « = » n'arrivait plus vide.** Quand le modèle envoyait la commande comme simple texte (`echo a=b`, `set X=1`, `git config user.name=Moi`…), Lutin la prenait pour une paire « clé=valeur » et l'outil recevait une commande vide. Désormais « clé=valeur » n'est lu comme tel que si **chaque clé est un paramètre de l'outil** ; sinon c'est du texte rattaché à l'argument principal de l'outil (d'après son schéma). Les arguments envoyés sous forme de texte JSON, de chaîne JSON, de nombre ou de liste sont aussi traités sans rien inventer.
- Les noms de paramètres voisins que les modèles écrivent par erreur (`command`, `cmd`, `path`, `file`, `content`…) sont rattachés au vrai paramètre de l'outil, seulement s'il est déclaré et absent.

**English.** `executer` (run a command): a command containing “=” no longer arrived empty when sent as plain text. “key=value” is only read as such when every key is a parameter of the tool; otherwise the text goes to the tool's main argument. Look-alike parameter names (`command`, `path`…) are mapped to the real one when declared and absent.

## 0.11.4

- **Une réflexion qui répète les mêmes phrases est coupée** : c'est le modèle qui se met à boucler (fréquent avec un petit modèle en mode réflexion), pas un défaut de Lutin, mais il ne s'en sort pas seul. Lutin le détecte (la même fin de texte déjà écrite plusieurs fois), arrête la génération, puis relance sans réflexion avec une pénalité de répétition et un rappel de répondre directement. Si ça recommence deux fois, il le dit.
- **L'accord automatique suspendu par du contenu web est visible** : les cases restent cochées (c'est ton choix pour la conversation) mais prennent un ⏸ avec l'explication, et la suspension ne dure que **jusqu'à la fin de la demande en cours** : à la demande suivante, tout repart comme coché.
- **Fenêtres noires qui clignotent au chargement d'un modèle (Windows)** : quand Lutin démarrait Ollama, il le détachait de toute console ; chaque programme à console qu'Ollama lance ensuite (le moteur de chaque modèle chargé) ouvrait alors sa propre fenêtre. Ollama est maintenant démarré avec une console **cachée** que ses programmes partagent. Ne change rien si Ollama était déjà démarré par autre chose (application Ollama, `.bat`).
- **Enquête sur les fenêtres noires qui clignotent** (Windows) : en lançant Lutin avec la variable `LUTIN_TRACE_PROCESSUS=1`, chaque programme qu'il lance est noté (heure, commande, fenêtre masquée ou non) dans `lutin-processus.log` du dossier temporaire (ou dans le fichier donné). Si une fenêtre clignote mais que rien n'est noté à ce moment-là, ce n'est pas Lutin.

**English.** Investigating flashing console windows (Windows): start Lutin with `LUTIN_TRACE_PROCESSUS=1` and every program it launches is logged (time, command, window hidden or not) to `lutin-processus.log` in the temporary folder. If a window flashes and nothing is logged at that moment, it is not Lutin.

## 0.11.3

- **Moins de détours quand un dossier est hors du projet** : les erreurs des outils de lecture (« fichier introuvable », « pas un dossier », « chemin refusé ») disent maintenant que les chemins sont relatifs au projet et qu'un dossier extérieur doit être ajouté comme dossier de travail, au lieu de laisser le modèle contourner par des commandes (chacune demandant ton accord). Lire un long fichier en plusieurs fois reste normal et n'est pas bloqué.
- Une sortie de commande trop longue dit combien de caractères ont été coupés au milieu et renvoie vers l'outil « lire » (avec debut/fin) pour lire un fichier par tranches.

**English.** Tool errors now say paths are relative to the project and that an outside folder must be added as a working folder. A cut command output says how much was cut and points to the “lire” tool for reading files in slices. Reading a long file in several pieces stays allowed.

## 0.11.2

- **« oui » / « ok » valide ce que le modèle vient de proposer**, au lieu de rejouer une vieille étape de la fiche ou de la liste de tâches (déjà faite, d'où des « c'est déjà fait » suivis de relectures inutiles) ou de ne rien ordonner faute de fiche. L'étape de la fiche n'est plus qu'un rappel, avec la consigne de ne pas la répéter si elle est déjà faite.

**English.** “yes” / “ok” now approves what the model just proposed, instead of replaying an old, already-done step of the sheet or task list.

## 0.11.1

- Numéros de version du CHANGELOG remis d'équerre : la fonction « modèles hors catalogue mieux jugés » est la **0.11.0** (un titre `feat:` fait monter le numéro du milieu, c'est la règle de publication du projet, voir docs/PUBLISHING.fr.md). **English.** CHANGELOG version numbers aligned: the “models outside the catalogue” feature is **0.11.0** (a `feat:` title bumps the middle number, per the project's publishing rule).

## 0.11.0

- **Les modèles hors catalogue sont mieux jugés** : pour un modèle découvert dans la bibliothèque ou installé à la main, Lutin lit ce qu'Ollama en dit (nombre de paramètres, experts, longueur de contexte, mémoire du contexte, capacités) au lieu d'une estimation. La description de la ligne le dit, y compris « n'appelle pas les outils » le cas échéant. Lecture en arrière-plan, une seule fois par modèle.

**English.** Models outside the catalogue are better judged: Lutin reads what Ollama says about them (parameters, experts, context length, context memory, capabilities) instead of guessing.

## 0.10.14

- **Quatre modèles de plus au catalogue**, pensés pour les petites machines : `granite4:tiny-h` (7 milliards dont 1 seul travaille à chaque mot : fait pour aller vite sur processeur), `granite4:3b`, `phi4-mini:3.8b` et `llama3.1:8b`. Notes éditoriales, pas des mesures : lance le banc d'essai 📊 chez toi.
- **Une demande d'accord dit pourquoi elle est posée** : « la case d'accord automatique n'est pas cochée pour cette conversation », ou « accord automatique suspendu : du contenu web a été lu pendant cette demande » (garde-fou contre les consignes piégées dans une page web). Plus de mystère quand une commande demande ton accord alors que les cases semblent cochées.
- Les **modèles à experts** sont jugés sur la part qui travaille (« Adapté » sur processeur au lieu de « Limite » quand cette part est petite), car sur processeur la vitesse suit cette part et non la taille du fichier.

**English.** Four more models in the catalogue for small machines (`granite4:tiny-h`, `granite4:3b`, `phi4-mini:3.8b`, `llama3.1:8b`; editorial notes, not measurements). Mixture-of-experts models are rated on the part that works at each word, since on a processor speed follows that part rather than the file size.

## 0.10.13

- Numéros de version du CHANGELOG corrigés (0.10.9 à 0.10.11 étaient des mises à jour de documentation Intel). **English.** CHANGELOG version numbers fixed.

## 0.10.12


- **Mode fiche de suivi : la conversation ne reste plus « pleine »**. Avant, rien n'était jamais retiré : la conversation grossissait sans fin et le début était rogné à CHAQUE réponse, donc Ollama relisait tout à chaque fois (des minutes sur processeur), la jauge restait au maximum et le modèle finissait par se perdre. Maintenant, quand les messages prennent près de la moitié de la fenêtre, la moitié la plus ancienne sort **en bloc**, sans appel au modèle (la fiche garde le fil, le début reste retrouvable avec « rappeler », et rien n'est retiré avant que le scribe l'ait lu). Le début de la requête ne change qu'à ces moments : le cache d'Ollama sert.
- **/compact en mode fiche** retire le début tout de suite au lieu d'ajouter un résumé en plus de la fiche. En mode résumé, il résume comme avant.
- **Une page en arrière-plan ne fige plus la réponse** : si l'onglet est gelé ou ne lit plus (autre onglet, autre PC, téléphone verrouillé), le serveur n'attend plus indéfiniment pour écrire : après 20 secondes il renonce à cette page et la réponse continue, enregistrée dans la conversation. Un battement toutes les 15 secondes garde aussi le flux ouvert derrière un reverse proxy quand le modèle charge ou qu'une commande est longue.
- **Quand le modèle tourne en rond** (même appel 5 fois), Lutin ne coupe plus net : il lui demande une dernière réponse **sans outil** pour conclure avec ce qu'il a obtenu.
- **La liste de tâches ne reste plus affichée pour toujours** : si le modèle ne la met pas à jour pendant 3 réponses, il en est prévenu, puis la liste est fermée.
- Le rang où le scribe en est (« jusqu'où il a lu ») suit désormais le retrait du début, aussi en mode résumé.

**English.** Tracking-sheet mode no longer leaves the conversation “full”: the oldest half now leaves the context in one block (no model call, never before the scribe has read it, still findable with “rappeler”), so Ollama's cache is reused and the gauge goes back down. /compact in sheet mode removes the beginning right away instead of adding a summary on top of the sheet. The scribe's reading position follows the removal.

## 0.10.11

- Documentation Intel : résultat mesuré sur un Core Ultra 5 125H — la puce graphique intégrée fonctionne (`100% GPU`) mais est plus lente que le processeur pour générer du texte (environ 8 contre 11 jetons/s sur `qwen3:4b`). **English.** Intel documentation: measured result, the integrated chip works but is slower than the processor.

## 0.10.10

- Documentation Intel : `OLLAMA_IGPU_ENABLE=1` est nécessaire, sinon Ollama voit la puce intégrée et l'écarte. **English.** Intel documentation: `OLLAMA_IGPU_ENABLE=1` is required, otherwise Ollama drops the integrated chip.

## 0.10.9

- Documentation Intel : carte graphique intégrée par Vulkan (`docker-compose.intel.yml`), NPU non utilisé. **English.** Intel documentation: integrated graphics through Vulkan, NPU not used.

## 0.10.8

- **Plus de silence sur « Réflexion »** : quand le modèle réfléchit puis ne répond rien (fréquent après un résultat d'outil, surtout si la conversation dépasse sa fenêtre de contexte), Lutin relance deux fois (réflexion coupée, avec un rappel de répondre) puis, si le modèle reste muet, dit clairement pourquoi et quoi faire. Avant, la page restait sur « Réflexion » sans aucune explication.
- **Résultats du banc d'essai lisibles** : pour chaque domaine (outils, code, français, consignes), un verdict ✅ réussi / 🟠 partiel / ❌ raté, ce que le domaine veut dire, et chaque question avec ✔ ou ✘. Un clic sur la ligne 📊 déplie le détail.
- Un modèle choisi mais **pas installé** n'est plus marqué « ★ actif » : la liste dit « choisi, mais pas installé ».

**English.** No more silence on “Thinking”: when the model thinks and then answers nothing, Lutin retries twice (thinking off, with a reminder to answer) and, if it stays mute, says why and what to do. Benchmark results are readable: a verdict per domain (✅ passed / 🟠 partial / ❌ failed), what it means, and each question with ✔ or ✘. A chosen but uninstalled model is no longer marked “★ active”.

## 0.10.7

- **Un diagnostic clair dès l'ouverture** : si Lutin ne peut pas répondre, une bannière en haut de la page dit pourquoi (Ollama arrêté ou absent, **aucun modèle installé**, modèle choisi absent ou trop gros, disque presque plein) avec le bouton qui règle le problème (*Installer ce modèle* — le plus adapté à la machine —, *Démarrer Ollama*, *Ouvrir les modèles*). Dans Docker, un conteneur neuf a Ollama mais aucun modèle : la pastille verte ne le disait pas.
- **Les erreurs d'Ollama sont nommées** : un modèle introuvable (HTTP 404) ne s'affiche plus « Ollama ne répond pas » mais « Le modèle … n'est pas installé », avec quoi faire.
- **Limite de processeurs d'un conteneur** (`cpus:`) : Lutin la lit et règle le nombre de fils de calcul en conséquence, au lieu de compter les cœurs de l'hôte.

**English.** A clear diagnosis on opening: when Lutin cannot reply, a banner at the top of the page says why (Ollama stopped or missing, **no model installed**, chosen model missing or too big, disk nearly full) with the button that fixes it (*Install this model*, *Start Ollama*, *Open the models*). Ollama errors are named: a missing model (HTTP 404) no longer reads “Ollama is not responding”. A container CPU limit (`cpus:`) is read and sets the compute threads accordingly.

## 0.10.6

- **Les fiches de suivi se gèrent depuis le menu « … » de chaque conversation** : *Voir ou modifier la fiche…* (celle de la conversation du menu, même si elle n'est pas ouverte) et *Supprimer la fiche* (avec confirmation). L'éditeur propose maintenant « Supprimer la fiche » au lieu de « Vider ».

**English.** Tracking sheets are managed from each conversation's “…” menu: *View or edit the sheet…* (the menu conversation's, even if not open) and *Delete the sheet* (with confirmation). The editor now offers “Delete the sheet” instead of “Empty”.

## 0.10.5

- **Exemples génériques partout** : le compose d'exemple, le tutoriel et le prompt n'ont plus de domaine, d'identifiant ni de matériel précis (`lutin.example.com`, `alice`), et les jeux de test n'ont plus de noms venant de projets personnels. Le prompt demande maintenant à l'IA de découvrir elle-même la machine.

**English.** Generic examples everywhere: the example compose file, the tutorial and the prompt no longer carry a specific domain, user name or hardware (`lutin.example.com`, `alice`), and test fixtures no longer use names from personal projects. The prompt now asks the AI to discover the machine itself.

## 0.10.4

- **Tutoriel Docker complet pour Debian** (`docs/TUTO-DOCKER-DEBIAN.fr.md`) : installer Docker, préparer les dossiers et le réseau, le `docker-compose.yml`, démarrer, installer un modèle, brancher le reverse proxy et Authelia, mises à jour, sauvegarde, dépannage.
- **Un prompt prêt à coller pour ton IA locale** (`docs/PROMPT-DOCKER-COMPOSE.fr.md`) : elle retrouve ta charte de docker-compose, explore ta machine en lecture seule et te rend un `docker-compose.yml` prêt à l'emploi, son `.env`, les blocs du reverse proxy et d'Authelia, les commandes et les vérifications.

**English.** Complete Docker tutorial for Debian (install Docker, folders and network, the compose file, start, model, reverse proxy and Authelia, updates, backup, troubleshooting) and a ready-to-paste prompt for your local AI (it finds your docker-compose charter, explores your machine read-only and hands you a ready-to-use compose file, its `.env`, the reverse-proxy and Authelia blocks, the commands and the checks).

## 0.10.3

- **La mission longue devient un mode** (« 🎯 Mission longue », dans la liste des modes de la colonne de gauche), comme Recherche ou Écriture : tu décris la mission dans le champ habituel, la **conversation sert de compte rendu en direct** et un **bandeau** montre l'état avec Pause / Reprendre / Arrêter. Plus de bouton 🎯 ni de section dans l'onglet Automatisation. L'autonomie est celle de la conversation (Fichiers auto + Commandes auto, relus à chaque tour) ; la durée max est une option du mode ; écrire pendant la mission lui donne une consigne ou répond à sa question ; Arrêter pendant un tour met en pause.
- **Telegram te prévient** quand une mission est finie ou bloquée (si l'addon est activé).

**English.** The long mission becomes a mode (“🎯 Long mission”, in the left column's mode list), like Research or Writing: you describe the mission in the usual box, the conversation is the live report and a banner shows the state with Pause / Resume / Stop. No more 🎯 button or section in the Automation tab. Autonomy is the conversation's (Auto files + Auto commands, re-read at every turn); the max duration is an option of the mode; writing during the mission gives it an instruction or answers its question; Stop during a turn pauses. Telegram notifies you when a mission is finished or stuck (if the addon is on).

## 0.10.2

- **Un faux appel d'outil caché dans un document n'est plus exécuté** : si un fichier ou une page lue contient un bloc `<tool_call>` et que le modèle le recopie dans sa réponse, c'est traité comme une citation (les appels que le modèle écrit lui-même continuent de marcher).
- **Le premier affichage est plus rapide avec beaucoup de conversations** : l'index de la liste est gardé sur le disque et n'est cru que si la date et la taille de chaque fichier n'ont pas changé (sinon le fichier est relu). Mesuré avec 800 conversations : environ 5 s de relecture au démarrage évitées.
- **Les tests nettoient leurs dossiers temporaires** (ils en laissaient des centaines, des Go sur le disque).

**English.** A fake tool call hidden in a document is no longer run: if a file or page that was read contains a `<tool_call>` block and the model copies it into its answer, it is treated as a quotation (calls the model writes itself still work). The first display is faster with many conversations: the list index is kept on disk and only trusted when each file's date and size are unchanged (otherwise the file is re-read); measured with 800 conversations, about 5 s of re-reading at startup avoided. Tests clean up their temporary folders (they used to leave hundreds, gigabytes on the disk).

## 0.10.1

- **Le modèle est collé au nom « Lutin »** en haut à gauche, et sa liste prend toute la place restante (le nom complet se lit).
- **Le bouton Mission est à côté d'Envoyer** (« 🎯 Mission ») et son rôle est clair : tu écris ta demande, tu cliques, une fenêtre te la rappelle et te demande le dossier, la durée et l'autonomie, puis **« Lancer la mission »** la démarre vraiment ; champ vide, il ouvre la liste des missions.

**English.** The model sits right next to the “Lutin” name at the top left, and its list takes all the remaining room. The Mission button is next to Send (“🎯 Mission”) and its role is clear: write your request, click, a window recalls it and asks for the folder, duration and autonomy, then “Start the mission” really starts it; with an empty box it opens the list of missions.

## 0.10.0

- **Les options suivent chaque conversation** : mode, réflexion, **Fichiers auto**, **Commandes auto**, essai à blanc, web et longueur max sont propres à la conversation ouverte ; changer de conversation retrouve ses réglages, une nouvelle conversation repart avec les accords automatiques **décochés**. Seul le modèle reste commun, et il passe **en haut à gauche, à côté du nom Lutin**. Une case cochée ou décochée pendant une réponse compte dès l'outil suivant.
- **Les accords automatiques ne dépendent plus du chemin d'accès** : ils marchent depuis un téléphone ou derrière un reverse proxy (la règle qui les coupait hors du niveau « cette machine seulement » disparaît, avec sa grosse note). Une lecture web dans la demande en cours les suspend toujours. « Accord auto » devient **« Fichiers auto »** (« Commandes auto » ne change pas) ; `/fichiers` remplace `/accord`, qui reste un alias.
- **Correction** : deux cases cochées à la suite pouvaient s'écraser (deux enregistrements en vol, le plus ancien gagnait) ; les enregistrements partent maintenant un par un et le dernier état l'emporte.

- **ComfyUI : le modèle se choisit dans une liste déroulante** (« Automatique » ou un modèle utilisable, avec sa famille), plus de champ libre. Les modèles que Lutin ne sait pas faire tourner ne sont plus proposés, ni dans la liste ni au modèle de langage, qui ne voit que les modèles et les types (image, vidéo, son) réellement disponibles ; le panneau montre les « moteurs de rendu » et dit pourquoi un modèle n'est pas proposé.
- **On peut ajouter ses propres familles de modèles** (workflow + `familles` dans « Flux… »), sans attendre une nouvelle version.

**English.** ComfyUI: the model is chosen in a drop-down list (“Automatic” or a usable model, with its family), no more free text. Models Lutin cannot run are no longer offered, neither in the list nor to the language model, which only sees the models and types (image, video, sound) that are really available; the panel shows the “rendering engines” and says why a model is not offered. You can add your own model families (workflow + `familles` in “Flow…”) without waiting for a new version.

## 0.9.0

- **Missions longues et Traitement de documents sortent des extensions** : sections de l'onglet Automatisation, toujours disponibles, rien à activer ; et un bouton **🎯** à côté du champ de saisie transforme ce que tu viens d'écrire en cahier des charges d'une mission.
- **Fichiers créés par Lutin** (Réglages > Dossiers et données) : tout ce que Lutin a produit (documents, images, vidéos, sons) avec taille, date et chemin ; sélection, « plus de 30 jours », suppression d'un geste, dossier ouvrable.
- **Accord auto / Commandes auto** : le navigateur de la machine où tourne Lutin les garde aussi au niveau d'accès « réseau » (un appareil appairé ne les a jamais) ; enregistrer un autre réglage n'efface plus ces cases ; quand elles sont cochées mais sans effet, la page et la conversation disent pourquoi.
- **Pastille verte « réponse terminée »** : elle apparaît aussi quand tu étais sur un autre onglet (Mémoire, Réglages…) pendant la réponse, et s'éteint quand tu reviens lire.
- **Homelab / Docker derrière un reverse proxy et Authelia** : `docker-compose.proxy.yml` prêt à l'emploi, guide complet (nginx, Traefik, Caddy), `LUTIN_ADMINS` (les identifiants Authelia qui configurent depuis la page ; les autres discutent), `mem_limit` du conteneur pris en compte pour les conseils de modèles, `LUTIN_BUDGET_GO`, nom du processeur lu sous Linux, disques des volumes, en-tête `X-Accel-Buffering: no` pour que nginx laisse passer la réponse mot à mot, « Ouvrir » masqué sur un serveur sans bureau.
- Robustesse : une lecture de conversation qui échoue un instant (partage réseau, Windows) ne la remplace plus par sa copie de secours ; supprimer, renommer ou épingler une conversation qui répond est refusé ; une demande refusée ne laisse plus de conversation vide ; les secrets sont comparés sur des octets (un caractère non ASCII ne fait plus planter) ; « Restaurer une sauvegarde » fonctionne (deux boutons avaient le même identifiant) ; les cartes de fichier fonctionnent aussi dans une conversation toute neuve ; supprimer ou ouvrir un fichier demande d'être sur la machine (ou administrateur).
- Nouveau test de parcours (cases auto qui tiennent au rechargement, file d'attente, icône « travail en cours », pastille verte).

**English.** Long missions and Document processing leave the extensions: sections of the Automation tab, always available, nothing to turn on; a **🎯** button next to the message box turns what you just wrote into a mission specification. Files created by Lutin (Settings > Folders and data): everything Lutin produced with size, date and path; select, “older than 30 days”, delete in one gesture, openable folder. Auto approval / Auto commands: the browser of the machine where Lutin runs keeps them at the “network” access level too (a paired device never has them); saving another setting no longer erases these boxes; when ticked but ineffective, the page and the conversation say why. Green “answer finished” dot: now also appears when you were on another tab during the answer, and goes out when you come back to read. New journey test (auto boxes surviving a reload, waiting queue, “working” icon, green dot).

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
