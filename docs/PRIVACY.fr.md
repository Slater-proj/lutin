[English](PRIVACY.md) · **Français**

# Vie privée

**Lutin n'envoie rien sur toi, nulle part.** Pas de compte, pas de télémétrie, pas de statistiques. Tes conversations, ta mémoire et tes fichiers restent sur ta machine ; le seul programme qui reçoit tes messages est l'Ollama de ta machine (ou de ton conteneur).

Les contacts réseau que Lutin peut faire, et quand :

| Contact | Quand | Ce qui est envoyé | Pour le couper |
|---|---|---|---|
| `api.github.com` (dernière version de Lutin) | au démarrage, puis une fois par jour au plus | une requête anonyme (ton adresse IP et le nom du programme, comme pour toute requête web) | le réglage « vérifier les mises à jour » (`verifier_maj`), ou le mode hors ligne strict |
| `raw.githubusercontent.com` (catalogue de modèles) | au démarrage, une fois par jour au plus, et quand tu cliques sur « Chercher de nouveaux modèles » | une requête anonyme | pareil |
| `registry.ollama.ai` (empreintes des modèles) | avec la vérification des mises à jour de modèles | une requête anonyme qui nomme les modèles installés | pareil |
| `ollama.com` (téléchargement d'un modèle) | seulement quand **toi** tu installes un modèle (c'est Ollama qui le fait) | ce qu'envoie Ollama | le mode hors ligne strict le refuse |
| DuckDuckGo et les pages web demandées | seulement si la case « Web » est cochée, quand le modèle cherche ou lit une page | les mots recherchés, ou l'adresse de la page | décocher « Web », ou le mode hors ligne strict |
| Telegram, ton serveur de courrier, X (seulement si **tu** actives l'addon correspondant) | tant que l'addon est actif | ce que l'addon envoie : les réponses rédigées pour les messages reçus ou les publications que tu valides, et les identifiants de connexion (rangés à part, jamais écrits dans le journal) | laisse l'addon désactivé (ils le sont tous par défaut), ou mode hors ligne strict |
| GitHub et PyPI | seulement pendant les scripts d'installation ou `lutin update` | une requête anonyme | ne pas les lancer |

Le **mode hors ligne strict** (`lutin hors-ligne oui`, la case « Hors ligne », ou `LUTIN_HORS_LIGNE=1`) bloque tous ces contacts ; seules cette machine et Ollama sont jointes. Un test surveille les connexions réelles.

Ce qui reste sur ton disque : configuration, conversations, mémoire, journal des actions (jamais le contenu des fichiers ni la sortie des commandes), sauvegardes des fichiers modifiés. Voir [SECURITY.fr.md](SECURITY.fr.md) pour savoir qui peut atteindre la page.

Composants tiers : Ollama et les modèles ont leurs propres conditions de vie privée et de licence ; Lutin n'embarque aucun modèle.
