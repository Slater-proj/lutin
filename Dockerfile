# syntax=docker/dockerfile:1
# Lutin dans un conteneur. Deux images, une seule construction :
#   complet (par défaut, c'est la dernière étape) : Lutin ET Ollama dans le même conteneur. On lance l'image, ça fonctionne.
#   leger                                          : Lutin seul ; Ollama est ailleurs (autre conteneur, machine hôte) : docker-compose.slim.yml
# Lutin and Ollama in one container (target "complet", the default), or Lutin alone (target "leger"): docker build --target leger .

ARG OLLAMA_VERSION=0.40.11

# --- la roue Python de Lutin (même construction pour les deux images)
FROM python:3.12-slim AS construction
WORKDIR /src
# Version fixée par la CI (pas d'historique git dans l'image de construction).
ARG LUTIN_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${LUTIN_VERSION}
COPY pyproject.toml README.md LICENSE CHANGELOG.md MANIFEST.in ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# --- image légère : Lutin seul
FROM python:3.12-slim AS leger
# git : pour le bouton Git de l'interface ; tini : arrêt propre ; ca-certificates : recherche web et catalogue (inutiles en mode hors ligne)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tini curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 lutin \
 && mkdir -p /data /travail \
 && chown lutin:lutin /data /travail
COPY --from=construction /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# Réglages par défaut (tous modifiables, voir docs/DOCKER.md). Dans un conteneur, « cette machine seulement » n'a pas de sens : l'accès se fait par code PIN (réseau)
# ou derrière un proxy. Le port n'est publié que sur 127.0.0.1 de l'hôte par docker-compose.yml.
ENV LUTIN_HOME=/data \
    LUTIN_NIVEAU=reseau \
    LUTIN_ECOUTE=0.0.0.0 \
    LUTIN_PORT=8777 \
    LUTIN_TRAVAIL=/travail \
    OLLAMA_URL=http://ollama:11434 \
    PYTHONUNBUFFERED=1

USER lutin
WORKDIR /travail
VOLUME ["/data", "/travail"]
EXPOSE 8777
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LUTIN_PORT}/" -o /dev/null || exit 1
ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["serve"]

# --- image complète : Lutin + Ollama (l'image officielle d'Ollama sert de base : mêmes bibliothèques, donc la carte NVIDIA fonctionne comme avec Ollama seul)
FROM ollama/ollama:${OLLAMA_VERSION} AS complet
# L'image Ubuntu a déjà un utilisateur 1000 (« ubuntu ») : on le remplace par « lutin », pour que les volumes aient les mêmes droits que dans l'image légère.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates tini curl \
 && rm -rf /var/lib/apt/lists/* \
 && (userdel -r ubuntu 2>/dev/null || true) \
 && useradd --create-home --uid 1000 lutin \
 && mkdir -p /data /travail /models \
 && chown lutin:lutin /data /travail /models
COPY --from=construction /dist/*.whl /tmp/
RUN python3 -m venv /opt/lutin \
 && /opt/lutin/bin/pip install --no-cache-dir /tmp/*.whl \
 && rm -f /tmp/*.whl
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# Ollama écoute à l'intérieur du conteneur seulement (127.0.0.1) : son port n'est jamais publié. Les modèles sont dans /models (volume).
ENV PATH=/opt/lutin/bin:$PATH \
    LUTIN_HOME=/data \
    LUTIN_NIVEAU=reseau \
    LUTIN_ECOUTE=0.0.0.0 \
    LUTIN_PORT=8777 \
    LUTIN_TRAVAIL=/travail \
    LUTIN_OLLAMA_INTERNE=1 \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_URL=http://127.0.0.1:11434 \
    OLLAMA_MODELS=/models \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    PYTHONUNBUFFERED=1

USER lutin
WORKDIR /travail
VOLUME ["/data", "/travail", "/models"]
EXPOSE 8777
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LUTIN_PORT}/" -o /dev/null || exit 1
ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
