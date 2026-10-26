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
  # Image complète : Ollama tourne dans ce conteneur (LUTIN_OLLAMA_INTERNE=1, posé par le Dockerfile). Il écoute sur 127.0.0.1 seulement ; ses modèles sont dans /models.
  if [ "${LUTIN_OLLAMA_INTERNE:-}" = "1" ]; then
    if [ ! -w "${OLLAMA_MODELS:-/models}" ]; then
      echo "[Lutin] The ${OLLAMA_MODELS:-/models} volume must be writable by user 1000 / Le volume ${OLLAMA_MODELS:-/models} doit être accessible en écriture pour l'utilisateur 1000." >&2
      exit 1
    fi
    {
      echo "[Lutin] GPU visible from the container / carte visible depuis le conteneur :"
      if command -v nvidia-smi > /dev/null 2>&1 && nvidia-smi -L 2> /dev/null; then :; else echo "  NVIDIA : none (docker run --gpus all / aucune)"; fi
      [ -e /dev/kfd ] && echo "  AMD : /dev/kfd present" || echo "  AMD : /dev/kfd absent"
      [ -d /dev/dri ] && echo "  /dev/dri : $(ls /dev/dri | tr '\n' ' ')" || echo "  /dev/dri : absent"
    } >> "$LUTIN_HOME/ollama.log" 2>&1
    ollama serve >> "$LUTIN_HOME/ollama.log" 2>&1 &
    for _ in $(seq 1 60); do
      curl -fsS "http://127.0.0.1:11434/api/version" > /dev/null 2>&1 && break
      sleep 1
    done
  fi
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
