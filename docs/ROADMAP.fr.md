[English](ROADMAP.md) · **Français**

# Feuille de route : de la 0.16 à la 1.0

Écrite le 2026-11-06, à partir du plan directeur du mainteneur et de l'[étude des moteurs](ENGINE_STUDY.fr.md). Elle **remplace** la numérotation du plan : celui-ci partait de la 0.15.1 et Lutin est déjà en 0.16.1.

Lutin reste ce qu'il est : **simple à installer sur n'importe quelle machine Windows, Linux ou Docker, simple à utiliser**, et capable de tout ce qui suit **sans l'imposer**. Une seule machine doit rester parfaitement fonctionnelle.

## 1. Principes (non négociables)

Ceux du plan du mainteneur et de [DECISIONS.fr.md](DECISIONS.fr.md) :

1. **Bibliothèque standard seulement**, aucune dépendance (y compris pour la vérification des signatures : voir §3, D1).
2. **Installation par script, sans droits administrateur** ; rien d'installé sans accord (ni moteur, ni modèle) ; aucun gros téléchargement sans validation.
3. **Ollama et le fonctionnement actuel ne cassent jamais** : chaque jalon passe toute la suite de tests existante.
4. **Aucune télémétrie**, mode hors ligne strict respecté par chaque nouvelle fonction, rien n'est exposé sur Internet par défaut, aucune donnée envoyée à un service sans autorisation explicite.
5. **Deux langues** (français et anglais) pour l'interface et pour les documents, avec le test de complétude.
6. **Le choix appartient à l'utilisateur** : Lutin recommande et explique, ne décide pas.
7. **Ne jamais prétendre qu'une plateforme, un GPU ou un mécanisme a été testé s'il ne l'a pas été.** Les essais réels sont listés en §6 ; l'assistant qui développe ne peut ni utiliser une carte graphique, ni Docker, ni les deux machines : ils sont faits par le mainteneur (ou par la CI quand c'est possible).
8. Chaque grosse fonction passe par une **étude de faisabilité** et une **porte de validation** avant d'être écrite (§5).
9. **Version déduite des étiquettes git** : `feat:` monte la version mineure, `fix:` et `docs:` le correctif ; pas d'étiquette fictive.

## 2. État réel (0.16.1) face au plan

| Plan | État |
|---|---|
| Interface commune des moteurs | **Fait** (`moteurs.py`) : Ollama, llama.cpp (géré ou externe), serveur compatible OpenAI ; actions possibles par moteur avec raison ; tâches de fond. **À compléter** : grille de capacités (natif / adapté / non supporté / non testé), tests de conformité communs, healthcheck formel. |
| Installation à la demande | **Fait pour llama.cpp** (téléchargement, empreinte, extraction sûre, désinstallation, réinstallation) et **Ollama sous Windows** (signature). **Manque** : mises à jour, annulation et reprise propres, Docker, Ollama sous Linux/Mac guidé. |
| Onglet Modèles adaptatif | **Fait** (masque ce qui est propre à Ollama ; Hugging Face pour llama.cpp). |
| Catalogue de modèles actualisable | **Existe** (JSON sur GitHub, vérification hebdomadaire). **Catalogue de moteurs : à créer.** |
| Détection matérielle, banc, calibrage | **Existent** (`machine.py`, `bench.py`, « Tester mon PC ») mais centrés sur Ollama. |
| Sécurité | Niveaux d'accès, appairage par code, proxy, journal, accords, MCP. **Rien** pour l'authentification entre machines. |
| Docker | Image complète (Lutin + Ollama), image légère, profils GPU/AMD/Intel/proxy, volume persistant. |
| CI | Ruff, tests Linux/Windows, scripts d'installation, paquet, installateur Windows, image Docker, détection de secrets. **Manque** : couverture mesurée, test Docker de volumes. |
| Cluster, réveil à distance, démarrage automatique | **Rien.** |

## 3. Décisions d'architecture proposées

**D1. Le catalogue des moteurs est de la donnée signée, pas du code.** Un JSON (moteurs, versions testées, plateformes, fichiers à télécharger avec leur empreinte, capacités déclarées, prérequis, notes), servi en HTTPS depuis le dépôt comme le catalogue de modèles. **Signature Ed25519 vérifiée en Python pur** (≈ 100 lignes, vecteurs du RFC 8032 en test, ≈ 10 ms), clé privée **hors dépôt** (outil `tools/` pour signer), **deux** clés publiques embarquées pour la rotation. Un catalogue invalide ou hors ligne : on garde le catalogue **livré avec Lutin**, toujours valide. Aucun code distant n'est jamais exécuté ; un nouveau moteur qui parle déjà OpenAI s'ajoute **sans nouvelle version de Lutin**.

**D2. Deux familles d'adaptateurs seulement** : `ollama` et `openai`. Tout autre moteur est une entrée de catalogue (adresse par défaut, port, clé, aide d'installation). Du code propre n'existe que pour un moteur dont Lutin **gère le cycle de vie** : llama.cpp (fait), éventuellement Colibri si son essai est concluant.

**D3. llama.cpp passe au mode routeur natif.** Un seul serveur géré, `--models-dir`, `--models-max`, chargement et déchargement à la demande (`/models/load`, `/models/unload`) : on abandonne « un serveur redémarré à chaque changement de modèle ». Plusieurs modèles prêts → **plusieurs rôles** sans redémarrage. Lutin génère une **clé d'API aléatoire** pour le serveur qu'il gère (même en 127.0.0.1 : un autre programme local ne peut pas l'utiliser). **Version épinglée et testée** (jamais « la dernière » : toutes les versions sont des préversions) ; mise à jour **proposée**, jamais automatique.

**D4. Docker : moteurs compagnons, pas de moteur dans l'image Lutin.** L'image **complète** (Lutin + Ollama) **reste par défaut** (décision du 2026-10-26) **tant que le banc comparatif (D5) ne montre pas mieux sur du matériel réel**. En plus : des **profils Compose** ajoutant un conteneur compagnon (images officielles `ollama/ollama` ou `ghcr.io/ggml-org/llama.cpp:server[-cuda|-vulkan|-intel|-openvino]`), reliés à Lutin par **adresse** (le mode « externe » existe déjà) avec des préréglages dans le catalogue. Pas de socket Docker monté dans Lutin (risque), le GPU reste géré par Docker. Un moteur natif sur l'hôte depuis un conteneur reste **impossible sans agent hôte** : on ne le promet pas. Sous Windows, **natif recommandé pour un poste à carte NVIDIA** (WSL2 ne reçoit que la moitié de la RAM par défaut) ; Docker pour Debian. `lutin doctor` détecte et explique.

**D5. Un banc comparatif de moteurs** (`lutin bench-moteurs`, et bouton dans la page) : **même fichier GGUF** (les blobs d'Ollama sont des GGUF : llama.cpp lit les mêmes octets), mesures de chargement, premier jeton, jetons/s, RAM, VRAM, stabilité ; résultat en JSON partageable. Il **tranche** les questions ouvertes (petit PC à GPU intégré : CPU / Vulkan / OpenVINO / Ollama ; carte NVIDIA : Ollama / llama.cpp / Colibri sur modèles à experts). Il ne tourne jamais au premier lancement ; rapide (environ 1 minute avec un modèle déjà installé) ou approfondi, facultatif ; résultats conservés et refaits seulement si le matériel, un pilote ou une version change.

**D6. Recommandation de moteur explicable** : table de règles (matériel → moteur recommandé, avec la raison, l'espace disque, les dépendances, les limites) alimentée par le catalogue et par les résultats du banc quand ils existent. Diagnostic matériel en quelques secondes, **sans télécharger de modèle**. Si aucun modèle n'est installé : recommandation théorique, on ne télécharge rien.

**D7. Les machines, sans agent séparé : chaque Lutin est un nœud.** Une machine = nom, adresse, jeton propre, adresse MAC facultative. **Ajout par validation explicite** (code d'appairage déjà existant, jamais d'acceptation automatique, pas de découverte réseau). Le nœud expose le moteur de sa machine sur une interface authentifiée ; le Lutin principal route une requête vers lui et **bascule en silence sur le moteur local** s'il est injoignable. **Quatre états observables seulement** : injoignable · réveil envoyé · nœud joignable · moteur opérationnel. Routage d'abord, répartition de requêtes ensuite ; la **distribution d'un même modèle entre machines n'est pas au programme de la 1.0**. Premier palier **déjà possible aujourd'hui** : moteur « externe » pointant vers `llama-server --api-key` de l'autre machine.

**D8. Alimentation** : réveil par paquet magique (UDP, bibliothèque standard), extinction par le nœud (action **explicite, avec accord et journal**), démarrage automatique **par tâche planifiée à l'ouverture de session** sous Windows (pas de service : session 0), unité systemd sous Linux. Chaque limite est dite à l'utilisateur (BIOS, câble, auto-connexion Windows).

**D9. Rôles par moteur** : les cinq rôles actuels gardent leur sens ; chacun peut désigner moteur, modèle, contexte et repli.

## 4. Jalons

Chaque jalon : étude → porte de validation → code ciblé → tests → documentation FR/EN → bilan avec les limites connues. Les critères sont ceux qui doivent être vrais pour **livrer**.

### 0.16.x (`fix:`) — Valider llama.cpp pour de vrai
- Essais réels S1 et S2 (§6) sur un poste Windows à carte NVIDIA et en CI ; corrections.
- **Critère** : installation par Lutin sur un poste Windows à carte NVIDIA, un modèle GGUF téléchargé, une conversation avec appels d'outils qui fonctionne ; sinon, la liste précise de ce qui ne marche pas.

### 0.17.0 — Catalogue des moteurs signé
- Format et schéma stricts, vérificateur Ed25519 (RFC 8032), `tools/` de signature, copie livrée avec Lutin, lecture en ligne, veille hebdomadaire (nouvelle version de llama.cpp, Colibri, Strata… : une demande de fusion à relire, jamais publiée toute seule).
- La fiche d'un moteur (Réglages > Moteur) vient du catalogue ; les moteurs externes (LM Studio, vLLM, SGLang, LocalAI, llama-swap, Strata…) y sont des préréglages.
- `ENGINE_CATALOG.md`, `ENGINE_DEVELOPMENT.md` (ajouter un moteur).
- **Critère** : un moteur compatible OpenAI s'ajoute par une simple ligne de catalogue, sans toucher au code ; un catalogue modifié ou mal signé est refusé ; hors ligne, le catalogue livré suffit.

### 0.18.0 — llama.cpp en mode routeur, capacités et conformité
- Mode routeur, clé d'API générée, version épinglée, option `--fit`, modèles à experts (`--n-cpu-moe`), vision (`--mmproj`), embeddings via le moteur (recherche par le sens avec llama.cpp).
- Grille de capacités par moteur (natif / adapté / non supporté / non testé) affichée dans la fiche ; **suite de conformité commune** exécutée sur chaque adaptateur avec des faux serveurs.
- **Critère** : deux modèles utilisés par deux rôles sans redémarrage du serveur ; la suite de conformité passe pour les trois adaptateurs.

### 0.19.0 — Banc comparatif et recommandation
- D5 et D6 ; page Diagnostic ; résultats conservés.
- **Fait (versions 0.19.x)** : `lutin bench-moteurs`, carte « Quel moteur pour ma machine ? », recommandation avec sa raison, résultats conservés et à refaire si le matériel ou une version change (`BENCH_MOTEURS.fr.md`). **Reste à faire** : l'essai sur matériel réel et les décisions Docker / petit PC à carte intégrée, qui exigent des chiffres de plusieurs machines.
- **Critère** : sur une machine réelle, le banc compare au moins deux moteurs sur le même GGUF et produit un fichier lisible ; la recommandation affiche sa raison. **Les décisions Docker (image par défaut) et petit PC à GPU intégré sont prises ici, sur des chiffres.**

### 0.20.0 — Installation avancée et premier lancement
- **Fait (0.20.0)** : profils Compose compagnons (`docker-compose.moteurs.yml`), `lutin doctor` Docker, premier lancement (onglet Modèles grisé avec la raison), annulation d'une installation de moteur (la reprise des téléchargements existait), `DOCKER_INSTALLATION.fr.md`, test de CI des volumes. Ollama guidé Linux/Mac : la commande à lancer était déjà affichée. **Non vérifié sur du vrai matériel** : les profils llama.cpp avec carte.
- Mises à jour proposées, annulation et reprise, **profils Compose compagnons** (Ollama, llama.cpp CPU / CUDA / Vulkan / Intel) avec préréglages d'adresse, Ollama guidé sous Linux/Mac, `lutin doctor` Docker (mémoire WSL, dossier de modèles).
- Premier lancement : diagnostic rapide, recommandation, installer / choisir autre / plus tard ; **tant qu'aucun moteur n'est prêt, l'onglet Modèles est désactivé proprement avec la raison**.
- `DOCKER_INSTALLATION.md` (Docker Linux et Docker Desktop/WSL2).
- **Critère** : redémarrer ou recréer le conteneur ne réinstalle rien ni ne perd moteurs et modèles (test de CI sur les volumes).

### 0.21.0 — Modèles et rôles multi-moteurs
- **Fait (0.21.0)** : catalogue filtré par moteur (`compat_modeles.py`, format / quantification / mémoire estimée / raisons), installation incompatible refusée, rôles par moteur en ligne de commande, banc indépendant d'Ollama en ligne de commande (`lutin bench --moteur`). **Pas encore** : les boutons du banc dans la page restent propres à Ollama.
- **Déjà fait en 0.16.8** : les modèles d'Ollama (« sans filtre » compris) sont lus tels quels par llama.cpp, sous les mêmes noms ; mêmes lignes de dossiers sur chaque carte de moteur.
- Catalogue de modèles filtré par moteur (format, quantification, mémoire estimée, compatibilité) ; rôles par moteur ; banc rapide et approfondi indépendants d'Ollama.
- **Critère** : jamais un modèle proposé qui n'est pas compatible avec le moteur choisi.

### 0.22.0 — Ressources et modèles volumineux
- Estimation avant chargement et avertissement de saturation, mode prudent pour machines modestes, préréglages pour modèles à experts (carte de 24 Go + 32 Go de RAM : experts en RAM, reste sur la carte), recommandations de contexte et de cache KV.
- **Critère** : un modèle trop gros est signalé **avant** le chargement ; l'estimation est comparée aux mesures du banc et son écart documenté.

- **Fait (0.22.0)** : `estimation.py` (niveaux, où, conseils, préréglage experts, mode prudent), avertissement avant chargement, `/api/estimation`, écart estimation / mesure dans le banc. **Reste** : mesurer l'écart sur du vrai matériel et documenter les chiffres.
### 0.23.0 — Machines (cluster, niveau 1)
- D7 : registre, appairage, jeton de nœud, état visible (quatre états), routage, repli local silencieux, journal ; **une machine injoignable ne produit ni erreur ni avertissement dans la conversation**, seulement un état visible dans la page Machines.
- `CLUSTER_ARCHITECTURE.md`.
- **Critère** : le Lutin d'un petit PC Debian répond avec le moteur du poste à carte NVIDIA, bascule en local si elle s'éteint, sans interruption visible hors de la page Machines ; aucune donnée n'est envoyée à un nœud non autorisé.

- **Fait (0.23.0)** : `machines.py`, `CLUSTER_ARCHITECTURE.fr.md`, Réglages > Machines, jeton de nœud, quatre états, repli local silencieux, journal. **Reste** : l'essai sur deux vrais ordinateurs (petit PC Debian + poste à carte NVIDIA).

### 0.24.0 — Alimentation
- D8 : réveil, extinction, démarrage automatique ; états « réveil envoyé → nœud joignable → moteur opérationnel » ; raison claire quand ça ne marche pas.
- **Critère** : essais S5 et S6 réussis ou limites documentées (auto-connexion Windows, BIOS).

- **Fait (0.24.0)** : `alimentation.py` (paquet magique, extinction autorisée/annulable/journalisée, démarrage à l'ouverture de session). **Reste** : essais S5 et S6 sur du vrai matériel (réveil depuis le petit PC Debian, auto-connexion Windows, BIOS).

### 0.25.0 — Moteurs expérimentaux
- Colibri : intégration **gérée** (archives précompilées + empreinte) **seulement si l'essai S3 la justifie** ; Strata et autres : préréglages externes. Étiquette « expérimental », jamais proposés par défaut.
- **Critère** : chaque moteur ajouté est indépendant, testé avec un faux serveur, documenté avec ses limites.

### 0.26.0 — Stabilisation → 1.0.0
- Tests de bout en bout sur les deux machines, avec et sans carte graphique, Windows, Debian, Docker, panne réseau, mise à jour, migration ; audit de sécurité ; documentation complète ; procédure de retour arrière.
- **1.0.0** seulement si les critères de stabilité, de sécurité, de portabilité et de tests sont atteints ; les moteurs expérimentaux **ne sont pas** requis.

**En continu (pas une version)** : couverture mesurée sans seuil bloquant ; test de CI des volumes Docker ; exécuteur GPU auto-hébergé **facultatif, déclenché à la main, jamais sur les demandes de fusion externes**.

## 5. Méthode et portes de validation

Pour chaque jalon, avant d'écrire du code : faisabilité, informations techniques à jour, architecture, fichiers touchés, dépendances, risques, critères, tests, alternatives. **Le mainteneur valide**, puis : branche de travail, modifications ciblées, tests, correction des régressions, documentation, bilan. Jamais plusieurs grosses évolutions expérimentales dans une même modification ; jamais de fonctionnalité existante supprimée sans accord ; jamais un test échoué masqué.

## 6. Essais réels (à faire sur du matériel)

| # | Essai | Où | Décide |
|---|---|---|---|
| S1 | Installer llama.cpp par Lutin (CUDA 12.4 + bibliothèques), télécharger un GGUF, converser avec outils | Poste Windows, carte NVIDIA | 0.16.x |
| S2 | `llama-server` (archive Ubuntu) dans `python:3.12-slim` : démarre-t-il ? (glibc) + petit GGUF de test | **CI** | D4, 0.20.0 |
| S3 | Ollama / llama.cpp / Colibri sur le même GGUF, modèle dense puis à experts | Poste Windows, carte NVIDIA | 0.19.0, 0.25.0 |
| S4 | Petit PC à GPU Intel intégré : CPU / Vulkan (`/dev/dri` dans Docker) / OpenVINO / Ollama, même GGUF | Petit PC Debian, Docker | **image par défaut**, 0.19.0 |
| S5 | Docker Desktop : mémoire de la machine WSL2, GPU, vitesse vs natif ; CUDA en service Windows (GeForce) | Poste Windows, carte NVIDIA | D4, D8 |
| S6 | Réveil du poste Windows depuis le petit PC Debian (BIOS, carte réseau, « démarrage rapide », pare-feu) ; extinction | Les deux | 0.24.0 |
| S7 | Un exécuteur auto-hébergé sur le poste à carte NVIDIA pour des tests GPU déclenchés à la main | Poste Windows, carte NVIDIA | facultatif |

Aucun de ces essais n'a été fait à ce jour.

## 7. Risques

1. **Rien de llama.cpp n'a tourné pour de vrai.** Mitigation : jalon 0.16.x avant tout.
2. **llama.cpp évolue très vite** : version épinglée et testée, mise à jour proposée, veille hebdomadaire.
3. **Format des réponses du mode routeur non vérifié** (`/models/load`…) : adaptateur tolérant et tests contre le vrai serveur à l'essai S1.
4. **Gain de llama.cpp face à Ollama incertain** : on ne promet aucun chiffre avant le banc.
5. **Sécurité des machines** : un nœud reçoit des conversations. Authentification et autorisation explicites d'abord ; les accords actuels ne sont jamais affaiblis ; la clé de signature du catalogue est un point critique (hors dépôt, rotation prévue).
6. **Réveil à distance dépend du matériel** : un nœud Windows sans session ouverte n'a pas son agent (auto-connexion à décider par l'utilisateur).
7. **Charge de documentation** : tout document existe en français et en anglais ; nouveaux fichiers : `ENGINE_CATALOG`, `ENGINE_DEVELOPMENT`, `CLUSTER_ARCHITECTURE`, `DOCKER_INSTALLATION`, `BENCHMARKS` (les migrations vont dans le `MIGRATION` existant).
8. **Limites de l'assistant** : pas d'accès aux deux machines ni à une carte graphique ; les tests sont faits avec de faux moteurs, puis confirmés par les essais ci-dessus.

## 8. Ce qui est écarté, et pourquoi

Voir le détail et les sources dans l'[étude](ENGINE_STUDY.fr.md) : adaptateur dédié par moteur (remplacé par le catalogue), llama-swap (redondant avec le mode routeur), vLLM et SGLang (Linux d'abord, aucun intérêt à un seul utilisateur : externes), GPUStack (nœuds Linux seulement), KTransformers (recherche, Linux seulement), Exo (Apple d'abord, pas de Windows), service Windows (session 0), distribution d'un modèle entre machines (hors 1.0), découverte réseau automatique, couverture comme barrière, CI GPU payante.

## 9. À décider par le mainteneur

1. Valider cette feuille de route et sa numérotation.
2. L'**image Docker par défaut** reste « complète » jusqu'à la 0.19.0, où les chiffres décideront (essais S2, S4, S5).
3. L'auto-connexion Windows pour le réveil à distance (0.24.0) : choix de sécurité de l'utilisateur, à expliquer le moment venu.
