[English](ENGINE_STUDY.md) · **Français**

# Étude des moteurs d'inférence (2026-11-06)

Cette étude sert de base à la [feuille de route](ROADMAP.fr.md). Elle dit ce qui a été **lu** (pages officielles, README, notes de version), ce qui est **annoncé par les auteurs** sans mesure indépendante, et ce qui **n'a pas été vérifié**. Rien n'a été installé ni exécuté pour l'écrire : toute performance citée vient des auteurs des projets.

Légende : ✔ lu dans une source officielle · ◐ annoncé par les auteurs, non vérifié · ✘ non vérifié.

## 1. Ce que Lutin a déjà (0.16.1)

Trois moteurs : Ollama (historique), llama.cpp (géré par Lutin ou externe par adresse) et « serveur compatible OpenAI » (adresse + clé). Ce dernier suffit à brancher n'importe quel moteur qui parle `/v1/chat/completions`. **Rien de llama.cpp n'a encore tourné pour de vrai** : tout est testé avec de faux serveurs.

## 2. Moteurs étudiés

### llama.cpp / `llama-server` — retenu, c'est le moteur de référence
- ✔ **Mode routeur natif** (annoncé le 11 décembre 2025) : `llama-server` lancé sans modèle sert plusieurs modèles ; `--models-dir`, `--models-max` (défaut 4, éviction du moins récemment utilisé), `--models-preset` (fichier INI par modèle), `--models-memory-margin`, `--no-models-autoload` ; endpoints `GET /models`, `POST /models/load`, `POST /models/unload`. Chaque modèle tourne dans son propre processus. Un lecteur signale que `--models-max` n'est pas toujours respecté sous requêtes concurrentes (non officiel, à vérifier).
- ✔ **Clé d'API** : `--api-key`, `--api-key-file` ; `/health` reste public.
- ✔ **Appels d'outils** : `--jinja` (actif par défaut), formats natifs pour Llama 3.x, Hermes, Qwen 2.5, Mistral Nemo, GPT-OSS…, sinon un format générique plus coûteux en jetons. La doc déconseille les caches KV très quantifiés (`-ctk q4_0`).
- ✔ **Modèles à experts (MoE)** : `--cpu-moe`, `--n-cpu-moe N`, `--moe-cache-mib`, `-ot` ; **`--fit` actif par défaut** (ajuste ce qui n'est pas fixé pour tenir en mémoire).
- ✔ **Vision** : `--mmproj` (expérimental). **Embeddings** : `/v1/embeddings`, `--embedding`, `--pooling`. **Reranking** : `/v1/rerank`.
- ✔ **Binaires officiels** (version b12129 relevée le 2026-11-05) : Windows (CPU, CUDA 12.4 et 13.4 + bibliothèques d'exécution, Vulkan, ROCm, SYCL, OpenVINO), Linux (CPU, CUDA 12.8/13.4, Vulkan, ROCm, SYCL, OpenVINO), macOS (arm64, x64). **Toutes les versions sont marquées « préversion » sur GitHub** : la règle « jamais de préversion » n'a pas de sens ici, il faut épingler une version **testée**.
- ✔ **Images Docker officielles** `ghcr.io/ggml-org/llama.cpp` : `server`, `server-cuda`, `server-cuda13`, `server-vulkan`, `server-intel` (SYCL), `server-openvino`, `server-rocm`. La doc note que les images GPU ne sont pas testées par la CI du projet au-delà de leur construction.
- ✔ Port par défaut du serveur : 9931 d'après le README (Lutin impose son propre port, 8089).
- ✘ Format exact des réponses de `/models/load`, `/models/unload` et de `/v1/models` (champ de capacité « multimodal »).
- Mesures publiques sur le gain face à Ollama : de quelques % à une vingtaine de % à l'écriture (surtout MoE), parfois plus ; les sources se contredisent et comparent rarement des conversions identiques. **Aucune mesure sur du matériel réel pour l'instant.**

### Ollama — conservé
- Gestion des modèles la plus simple (bibliothèque, `pull`, déchargement automatique), un service de plus. Sur GPU Intel : Vulkan **expérimental** (0.12.6, 2025) ; un article de 2026 le dit actif par défaut mais prévient qu'il peut ralentir sur un petit GPU intégré ; un rapport communautaire (mars 2026) signale Ollama à 100 % CPU sur Arc après une mise à jour de pilote. ✘ rien de vérifié sur un Core Ultra série 1.
- Les blobs d'Ollama **sont des fichiers GGUF** : llama.cpp peut lire exactement les mêmes octets, ce qui permet une comparaison équitable.

### Colibri (JustVugg/colibri) — réel, actif, **expérimental** (candidat)
- ✔ Moteur en C pour grands modèles MoE : experts « chauds » sur le GPU, « tièdes » en RAM, « froids » lus sur NVMe. Apache-2.0. v2.1.0 publiée le 2026-10-31 ; 48 300 étoiles ; 5 150 commits (compteurs GitHub, non audités).
- ✔ Archives précompilées Windows x86-64 (AVX2, + archive CUDA séparée, cartes capacité de calcul ≥ 8.0), Linux x86-64, macOS arm64 ; CPU seul possible ; Vulkan 1.2 (AMD, Intel, NVIDIA).
- ✔ API compatible OpenAI (`http://127.0.0.1:8000/v1`) et Anthropic ; serveur MCP. **Lit les GGUF tels quels depuis la 2.1.0** (`coli import`), mais utilise aussi son propre format converti.
- ◐ Performances (machine des auteurs : i5-13500, 62 Go de RAM, RTX PRO 4000 Blackwell 24 Go) : Qwen3.6-35B-A3B Q4_K_M ≈ 105 jetons/s en CUDA ; Qwen3.8-Flash-Next IQ2_XS (68 Go) ≈ 51 jetons/s avec les experts en RAM. Les très gros modèles tombent à quelques jetons/s, voire moins, « le disque fixe la vitesse ».
- ✔ Limites écrites par les auteurs : « plateforme de recherche ouverte », un GPU intégré peut perdre face au CPU, WSL : dossier de modèles sous `/mnt/c` « bien plus lent », décodage spéculatif parfois contre-productif.
- ✘ Incohérences internes relevées (taille de Qwen3.8, vitesse de Kimi K3). Cohérence avec une machine à **32 Go de RAM** : un modèle de 68 Go ne tiendrait pas en RAM et irait sur NVMe, donc bien plus lent que les chiffres ci-dessus.

### Strata (Niko1221/Strata) — réel, actif, **expérimental** (externe)
- ✔ MIT. v0.2.11 publiée le 2026-11-05 ; 40 800 étoiles. Application de bureau + CLI (`strata launch`), API OpenAI/Anthropic locale, installeurs Windows / Linux / macOS (le README cite encore la 0.2.9).
- ✔ NVIDIA RTX 20–50 (Windows et Linux), AMD RX 7700+ (Linux), Intel Arc (Linux). CPU seul et Vulkan : **non mentionnés**.
- ◐ Le tableau de performances du README porte sur DeepSeek V4.1, pas sur Qwen3.8 ; chiffres auto-mesurés, non refaits sur la version publiée.
- ✘ Base logicielle (llama.cpp ou non), port et endpoints, section « problèmes connus » non lus.
- Article lu plus tôt dans la session : exige 12 Go de VRAM et 32 Go de RAM au minimum ; **une machine à 32 Go de RAM est à la limite**.

### llama-swap — **redondant** avec le mode routeur
- ✔ v270, MIT, binaires Windows/Linux, images Docker `unified-cuda13`, `unified-vulkan`, `intel`, `cpu`. Échange à la demande des serveurs llama.cpp (ou d'autres), `ttl`, `matrix`. Il reste utile pour quelqu'un qui veut faire tourner **plusieurs moteurs différents** derrière une adresse unique ; ce n'est pas notre besoin. → **externe** (adresse), non géré.

### LocalAI — externe seulement
- ✔ MIT, v4.11.0 (octobre 2026), 50 200 étoiles. Tout-en-un (texte, image, voix, vidéo), API OpenAI / Anthropic (et Ollama d'après les notes d'avril–mai 2026), images Docker CPU / CUDA / Intel / Vulkan. Windows natif et WSL2 **non mentionnés**. Lourd ; ses backends s'installent à la demande dans d'autres images.

### RamaLama — externe seulement
- ✔ MIT, v0.26.0, 3 100 étoiles. Exécute llama.cpp/vLLM dans des conteneurs (Podman par défaut) ; Windows via Docker/Podman Desktop + WSL2. Reconnaît Meteor Lake. Redondant avec les profils Compose prévus. ✘ statut « alpha » (résumé automatique, non vérifié dans le texte).

### vLLM — externe seulement, pas géré
- ✔ « Ne gère pas Windows nativement » (WSL2 ou forks communautaires). NVIDIA capacité de calcul ≥ 7.5 ; Intel GPU : fonctions de base, compilation depuis les sources (Python 3.12) ; CPU x86 avec AVX512 (recommandé) ou AVX2. WSL n'alloue que 50 % de la mémoire par défaut. Conçu pour le débit de **nombreux utilisateurs simultanés** : aucun intérêt pour un usage personnel.

### SGLang — externe seulement, pas géré
- ✔ Apache-2.0, v0.5.23, images Docker. Cite RTX 30/40/50, Intel Arc, AMD, Apple. Windows et WSL2 **non mentionnés**. Même public que vLLM (serveur de production).

### GPUStack — écarté
- ✔ Apache-2.0, v2.3.0. **Les nœuds de calcul ne tournent que sous Linux** (« si Windows, utiliser WSL2 »). Moteurs : vLLM, SGLang, TensorRT-LLM ; llama.cpp non nommé. Pensé pour des équipes ; fonctions « Enterprise ». Les nœuds de Lutin (voir feuille de route) couvrent le besoin d'une personne.

### KTransformers — écarté
- ✔ Apache-2.0, v0.7.2. « Projet de recherche », roues Linux x86-64 uniquement, aucune instruction Windows ni WSL2 ; la RTX 4090 n'apparaît que dans des mesures de **fine-tuning**. Colibri et llama.cpp (`--n-cpu-moe`) couvrent l'usage visé.

### Exo — irréalisable aujourd'hui
- ✔ (sources secondaires, à vérifier sur le dépôt) moteur MLX d'abord pour Apple Silicon ; sous Linux, CPU seul d'après le README cité ; NVIDIA et Windows sont sur la feuille de route des auteurs, **pas livrés**. Inutilisable avec les deux machines de référence.

### LM Studio — géré sans son interface (révisé le 2026-11-09)
- Application fermée (gratuite) avec un serveur local compatible OpenAI. **Révisé après lecture de sa documentation** : elle fournit un démon sans interface, `llmster`, installé par un script officiel (`lmstudio.ai/install.sh`, `install.ps1` sous Windows ; le script vérifie la somme SHA-512 de ce qu'il télécharge) et piloté par la commande `lms` (`daemon up/down/update`, `server start --port`, `get`, `ls --json`). Lutin l'installe donc, le démarre, l'arrête et lui télécharge des modèles. **Pas essayé sur une vraie installation.**
- Retirés du catalogue (pas intégrables simplement) : vLLM et SGLang (Linux + CUDA, plusieurs Go de paquets pip, aucun gain pour un seul utilisateur), LocalAI (pas de binaire Windows), llama-swap (redondant avec le routeur de llama.cpp). Un utilisateur averti les joint toujours avec « Autre serveur » et leur adresse.

### Ancien avis sur LM Studio (avant révision)
- Application fermée (gratuite) avec serveur local compatible OpenAI ; utile sous Windows pour tester. Pas d'installation gérée possible par Lutin.

## 3. Réexamen de ce que j'avais classé « irréalisable » ou « sans intérêt »

| Point | Verdict après étude |
|---|---|
| Un adaptateur dédié par moteur | **Confirmé inutile.** Deux familles d'API (Ollama, OpenAI) ; le reste est de la **donnée** (catalogue). Exception : un moteur dont Lutin gère le cycle de vie (llama.cpp ; Colibri si l'essai est concluant). |
| llama-swap | **Redondant**, le mode routeur de llama.cpp fait l'essentiel nativement. |
| vLLM, SGLang | **Pas gérés**, externes. Windows natif impossible (vLLM), aucun gain à un seul utilisateur. |
| GPUStack, KTransformers, Exo | **Écartés** (Linux seulement / recherche / Apple d'abord). |
| Colibri, Strata | **Je me trompais sur leur existence/maturité apparente : ils sont réels et actifs.** Mais leurs chiffres sont auto-déclarés, 0.x ou « recherche », et une machine à 32 Go de RAM est à la limite de leurs modèles phares. → **expérimentaux**, jamais proposés par défaut, essai mesuré avant toute intégration gérée. |
| Catalogue signé (Ed25519) | **J'avais tort : c'est réalisable.** La bibliothèque standard n'a pas Ed25519, mais la **vérification** (RFC 8032) tient en une centaine de lignes avec `hashlib` (SHA-512) et des entiers Python ; une implémentation de référence en Python pur vérifie en ≈ 10 ms. Pas de secret manipulé : l'absence de temps constant est sans conséquence pour une vérification. À tester avec les vecteurs du RFC. Clé privée hors dépôt, deux clés publiques embarquées (rotation). |
| « Version stable » d'un moteur | **Remplacée** par « version testée et épinglée » (llama.cpp ne publie que des préversions). |
| Service Windows | **Déconseillé par défaut.** Un service tourne en « session 0 », sans accès au pilote d'affichage : les sources (anciennes) disent que CUDA y est impossible sur GeForce (possible avec les pilotes TCC des cartes pro). NSSM/WinSW n'y changent rien. → **tâche planifiée « à l'ouverture de session »**. Conséquence pour le réveil à distance : sans session ouverte (auto-connexion Windows, choix de sécurité de l'utilisateur), l'agent ne démarre pas. À confirmer par un essai sur le poste à carte NVIDIA. |
| Sept états d'une machine | **Quatre observables** : injoignable, réveil envoyé (attente), nœud joignable, moteur opérationnel. « Éteinte » et « en veille » sont indiscernables à distance. |
| Wake-on-LAN | **Réalisable** (paquet UDP, bibliothèque standard) sur un même sous-réseau, câble Ethernet, option BIOS/UEFI et carte réseau « Wake on Magic Packet » ; « Démarrage rapide » de Windows à essayer dans les deux positions (sources contradictoires) ; pare-feu UDP 9. Jamais depuis Internet par défaut. |
| CI avec GPU | **Pas gratuit** : les exécuteurs GitHub à GPU sont payants (≈ 0,052 $/min Linux 4 cœurs GPU, 0,102 $ Windows) et réservés aux offres Team/Enterprise. Un exécuteur **auto-hébergé** est gratuit mais risqué sur un dépôt public → déclenchement **manuel seulement**, jamais sur les demandes de fusion externes. Sinon : tests matériels manuels scriptés. |
| Découverte automatique des machines | **Hors périmètre** (mDNS demande une dépendance) : adresse saisie + code d'appairage, ce qui respecte « jamais d'acceptation automatique ». |
| Docker Desktop (Windows) pour un poste à carte NVIDIA | **Déconseillé** : GPU en quasi-natif d'après des sources secondaires (90–100 %), mais la machine virtuelle WSL2 ne reçoit que **50 % de la RAM par défaut** (16 Go sur 32), et un dossier de modèles sous `/mnt/c` est « bien plus lent » (Colibri). Windows natif recommandé ; Docker pour Debian. |
| Installer un moteur *dans* l'image Lutin | **Remplacé** par des moteurs **compagnons** (images officielles) reliés par adresse : pas de socket Docker monté dans Lutin (risque), le GPU reste géré par Docker. Binaire dans le volume possible mais à valider (glibc de `python:3.12-slim` face aux binaires Ubuntu : essai de CI prévu). |
| Couverture à 80 % | **Mesurer sans seuil bloquant** au début. |

## 4. Petit PC à GPU Intel intégré (Core Ultra série 1, Debian, Docker) : ce qu'on sait et ne sait pas

- ◐ Un benchmark IPEX-LLM sur un Ultra 5 : le GPU intégré est un peu plus rapide que le CPU sur de petits modèles (≈ 9,8 → 12,7 jetons/s sur un 8 B ; 20,6 → 23,2 sur un 3 B), très limité par la bande passante mémoire partagée.
- ✔ Dans llama.cpp, SYCL et Vulkan donnent des résultats qui dépendent beaucoup des pilotes (Vulkan jusqu'à 2,9 × plus rapide que SYCL sur une Arc dans un cas, l'inverse dans un autre).
- ✔ Le **backend OpenVINO de llama.cpp** (préversion, OpenVINO 2026.1) est validé sur la série Core Ultra 1 (Meteor Lake) et seul à pouvoir utiliser le NPU ; ✘ aucune mesure convaincante.
- ✘ **Aucune mesure trouvée pour ce type de machine** en Docker. Conclusion : il faut **mesurer** (CPU / Vulkan / OpenVINO / Ollama, même GGUF) avant de recommander quoi que ce soit pour ce type de machine.

## 5. Sources principales (consultées le 2026-11-06)

- llama.cpp : README du serveur et `docs/function-calling.md` (ggml-org/llama.cpp), article « New in llama.cpp: Model Management » (Hugging Face, 11 décembre 2025), page des versions (b12129), documentation des images Docker.
- Colibri : dépôt JustVugg/colibri, page de versions (v2.1.0), site du projet. Strata : dépôt Niko1221/Strata, versions (v0.2.11).
- llama-swap, KTransformers, LocalAI, GPUStack, RamaLama, SGLang : dépôts officiels et pages de dernière version ; vLLM : documentation d'installation (pages « aperçu développeur »).
- Intel / OpenVINO : article Phoronix (OpenVINO 2026.1) et blogs OpenVINO ; Ollama et Vulkan : Phoronix, discussions Intel Community (sources secondaires).
- Wake-on-LAN : fils Microsoft Q&A et Intel Community (sources communautaires). Session 0 : fils du forum NVIDIA (anciens). GPU de GitHub Actions : tableaux de prix de la documentation GitHub (versions Enterprise Server) et sites tiers.
- Ed25519 : package `pyrixos-ed25519` (≈ 10 ms par vérification) ; RFC 8032.

Ce document sera **mis à jour** quand les essais réels (voir la feuille de route, « Essais ») donneront des chiffres.
