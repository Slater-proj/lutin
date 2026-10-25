# syntax=docker/dockerfile:1
# Lutin dans un conteneur : le serveur et la commande `lutin`. Ollama tourne dans SON conteneur (voir docker-compose.yml) ou sur la machine hôte.

FROM python:3.12-slim AS construction
WORKDIR /src
# Version fixée par la CI (pas d'historique git dans l'image de construction).
ARG LUTIN_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${LUTIN_VERSION}
COPY pyproject.toml README.md LICENSE CHANGELOG.md MANIFEST.in ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.12-slim
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
