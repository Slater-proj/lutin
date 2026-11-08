#!/bin/sh
# Point d'entrée de l'image Lutin.
#   (sans argument) / serve : applique les variables d'environnement à la configuration, puis lance le serveur
#   autre chose            : passé tel quel à la commande lutin (docker compose exec lutin lutin pin, lutin models install qwen3:8b…)
# Les variables d'environnement sont la source de vérité pour l'accès (niveau, écoute, port, proxy) et les dossiers de travail : elles sont réappliquées à chaque démarrage.
set -eu

commande="${1:-serve}"
# All container paths are English: /data /workspace /models /engines. The old French names are still read: LUTIN_TRAVAIL, LUTIN_TRAVAUX, LUTIN_MOTEURS, and a /travail volume if you still mount one.
# Les chemins du conteneur sont en anglais ; les anciens noms français restent lus.
WORKSPACE="${LUTIN_WORKSPACE:-${LUTIN_TRAVAIL:-}}"
if [ -z "$WORKSPACE" ]; then
  if awk '$5 == "/travail" { trouve = 1 } END { exit !trouve }' /proc/self/mountinfo 2>/dev/null; then
    WORKSPACE=/travail
    echo "[Lutin] /travail (old name) is mounted and still works; the new name is /workspace / /travail (ancien nom) est monté et fonctionne encore ; le nouveau nom est /workspace." >&2
  else
    WORKSPACE=/workspace
  fi
fi

if [ "$commande" = "serve" ]; then
  mkdir -p "$LUTIN_HOME"
  if [ ! -w "$LUTIN_HOME" ] || [ ! -w "$WORKSPACE" ]; then
    echo "[Lutin] The /data and ${WORKSPACE} volumes must be writable by user 1000 (see docs/DOCKER.md, \"Folder permissions\")." >&2
    echo "[Lutin] Les volumes /data et ${WORKSPACE} doivent être accessibles en écriture pour l'utilisateur 1000 (voir docs/DOCKER.fr.md, « Droits sur les dossiers »)." >&2
    exit 1
  fi
  # Les moteurs (Ollama, llama.cpp) ne sont plus dans l'image : Lutin les installe et les lance lui-même depuis la page (dossier /engines, sinon /data/engines).
  # Les modèles sont dans /models.
  [ -d "${OLLAMA_MODELS:-/models}" ] && [ ! -w "${OLLAMA_MODELS:-/models}" ] && echo "[Lutin] The ${OLLAMA_MODELS:-/models} volume should be writable by user 1000 / Le volume ${OLLAMA_MODELS:-/models} devrait être accessible en écriture pour l'utilisateur 1000." >&2
  [ -d /engines ] && [ ! -w /engines ] && echo "[Lutin] /engines is not writable by user 1000: engines go to /data/engines instead (fix: sudo chown -R 1000:1000 on the host folder) / /engines n'est pas accessible en écriture pour l'utilisateur 1000 : les moteurs iront dans /data/engines." >&2
  set -- setup --yes --no-models --no-ollama --level "${LUTIN_NIVEAU:-reseau}" --port "${LUTIN_PORT:-8777}" --workspace "$WORKSPACE" --reconfigure
  [ -n "${LUTIN_ECOUTE:-}" ] && set -- "$@" --listen "$LUTIN_ECOUTE"
  [ -n "${LUTIN_URL_PUBLIQUE:-}" ] && set -- "$@" --url "$LUTIN_URL_PUBLIQUE"
  for ip in $(echo "${LUTIN_PROXY_IP:-}" | tr ',' ' '); do set -- "$@" --proxy-ip "$ip"; done
  lutin "$@" > /dev/null
  # Autres dossiers de travail : LUTIN_WORKSPACES=/workspace/a,/workspace/b (ajoutés s'ils n'y sont pas déjà)
  for dossier in $(echo "${LUTIN_WORKSPACES:-${LUTIN_TRAVAUX:-}}" | tr ',' ' '); do lutin workspaces add "$dossier" > /dev/null || echo "[Lutin] Dossier de travail ignoré : $dossier" >&2; done
  # Mode hors ligne strict : LUTIN_HORS_LIGNE=1 (lu directement par Lutin à chaque connexion sortante)
  exec lutin serve --no-browser --no-supervisor
fi

exec lutin "$@"
