#!/bin/sh
# Point d'entrée de l'image Lutin.
#   (sans argument) / serve : applique les variables d'environnement à la configuration, puis lance le serveur
#   autre chose            : passé tel quel à la commande lutin (docker compose exec lutin lutin pin, lutin modeles installer qwen3:8b…)
# Les variables d'environnement sont la source de vérité pour l'accès (niveau, écoute, port, proxy) et les dossiers de travail : elles sont réappliquées à chaque démarrage.
set -eu

commande="${1:-serve}"
TRAVAIL="${LUTIN_TRAVAIL:-/travail}"

if [ "$commande" = "serve" ]; then
  mkdir -p "$LUTIN_HOME"
  if [ ! -w "$LUTIN_HOME" ] || [ ! -w "$TRAVAIL" ]; then
    echo "[Lutin] The /data and ${TRAVAIL} volumes must be writable by user 1000 (see docs/DOCKER.md, \"Folder permissions\")." >&2
    echo "[Lutin] Les volumes /data et ${TRAVAIL} doivent être accessibles en écriture pour l'utilisateur 1000 (voir docs/DOCKER.fr.md, « Droits sur les dossiers »)." >&2
    exit 1
  fi
  # Les moteurs (Ollama, llama.cpp) ne sont plus dans l'image : Lutin les installe et les lance lui-même depuis la page (dossier /engines, sinon /data/moteurs).
  # Les modèles sont dans /models.
  [ -d "${OLLAMA_MODELS:-/models}" ] && [ ! -w "${OLLAMA_MODELS:-/models}" ] && echo "[Lutin] The ${OLLAMA_MODELS:-/models} volume should be writable by user 1000 / Le volume ${OLLAMA_MODELS:-/models} devrait être accessible en écriture pour l'utilisateur 1000." >&2
  [ -d /engines ] && [ ! -w /engines ] && echo "[Lutin] /engines is not writable by user 1000: engines go to /data/moteurs instead / /engines n'est pas accessible en écriture pour l'utilisateur 1000 : les moteurs iront dans /data/moteurs." >&2
  set -- setup --oui --sans-modeles --sans-ollama --niveau "${LUTIN_NIVEAU:-reseau}" --port "${LUTIN_PORT:-8777}" --travail "$TRAVAIL" --reconfigurer
  [ -n "${LUTIN_ECOUTE:-}" ] && set -- "$@" --ecoute "$LUTIN_ECOUTE"
  [ -n "${LUTIN_URL_PUBLIQUE:-}" ] && set -- "$@" --url "$LUTIN_URL_PUBLIQUE"
  for ip in $(echo "${LUTIN_PROXY_IP:-}" | tr ',' ' '); do set -- "$@" --proxy-ip "$ip"; done
  lutin "$@" > /dev/null
  # Autres dossiers de travail : LUTIN_TRAVAUX=/travail/a,/travail/b (ajoutés s'ils n'y sont pas déjà)
  for dossier in $(echo "${LUTIN_TRAVAUX:-}" | tr ',' ' '); do lutin travaux ajouter "$dossier" > /dev/null || echo "[Lutin] Dossier de travail ignoré : $dossier" >&2; done
  # Mode hors ligne strict : LUTIN_HORS_LIGNE=1 (lu directement par Lutin à chaque connexion sortante)
  exec lutin serve --sans-navigateur --sans-superviseur
fi

exec lutin "$@"
