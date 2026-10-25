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
    echo "[Lutin] Les volumes /data et ${TRAVAIL} doivent être accessibles en écriture pour l'utilisateur 1000 (voir docs/DOCKER.md, « Droits sur les dossiers »)." >&2
    exit 1
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
