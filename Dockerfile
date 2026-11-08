# syntax=docker/dockerfile:1
# Lutin dans un conteneur : Lutin seul, léger. Au premier lancement, la page propose d'installer un moteur (Ollama, llama.cpp) ; il vit dans le volume /engines
# (sinon /data/engines) et survit aux mises à jour de l'image. Les modèles sont dans /models. Les cibles « complet » et « leger » donnent la même image.
# Lutin alone and light: the page installs the engine you pick (Ollama, llama.cpp) into the /engines volume, so image updates never erase it. docker build .

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
# git : bouton Git ; tini : arrêt propre ; ca-certificates : recherche web et catalogue ; zstd : décompresser Ollama ; libvulkan1 + mesa : cartes AMD / Intel (Vulkan) pour llama.cpp et Ollama
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tini curl libgomp1 zstd libvulkan1 mesa-vulkan-drivers \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 lutin \
 && mkdir -p /data /workspace /models /engines \
 && chown lutin:lutin /data /workspace /models /engines
COPY --from=construction /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# Réglages par défaut (tous modifiables, voir docs/DOCKER.md). Dans un conteneur, « cette machine seulement » n'a pas de sens : l'accès se fait par code PIN (réseau)
# ou derrière un proxy. Le port n'est publié que sur 127.0.0.1 de l'hôte par docker-compose.yml.
ENV LUTIN_DOCKER=1 \
    LUTIN_HOME=/data \
    LUTIN_NIVEAU=reseau \
    LUTIN_ECOUTE=0.0.0.0 \
    LUTIN_PORT=8777 \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_URL=http://127.0.0.1:11434 \
    OLLAMA_MODELS=/models \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    PYTHONUNBUFFERED=1

USER lutin
WORKDIR /workspace
# /engines n'est PAS déclaré en VOLUME : All container paths are English (/data /workspace /models /engines). Sans montage explicite, les moteurs vont dans /data/engines (qui est un volume)
VOLUME ["/data", "/workspace", "/models"]
EXPOSE 8777
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LUTIN_PORT}/" -o /dev/null || exit 1
ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["serve"]

# --- image complète (balise « latest ») : la MÊME image que la légère. Elle ne contient plus Ollama (plus d'1,5 Go re-téléchargés à chaque mise à jour) :
# le moteur se choisit et s'installe depuis la page de Lutin, dans le dossier /engines (ou engines/ dans /data) ; les modèles restent dans /models.
FROM leger AS complet
