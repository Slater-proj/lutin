**English** · [Français](DOCKER.fr.md)

# Lutin with Docker

A ready-to-use image: **Lutin and Ollama in the same container**. You start it, you open the page, you install a model: that is all. Handy on Linux, on a server or a NAS.

> **Honesty.** The images are built and started by the CI (login page, PIN code, Ollama inside the complete image) and published on `ghcr.io`. They have **never been run with a real NVIDIA card** nor on a NAS: if something does not work, open a [bug](https://github.com/Slater-proj/lutin/issues/new/choose) with `docker compose logs`.

## Two images

| Tag | Content | Size | For |
|---|---|---|---|
| `ghcr.io/slater-proj/lutin:latest` (or `:X.Y.Z`) | **Lutin + Ollama** | several GB (Ollama's libraries) + the models | **most people**: nothing else to install |
| `ghcr.io/slater-proj/lutin:slim` (or `:X.Y.Z-slim`) | Lutin alone | a few hundred MB | if Ollama already runs elsewhere (host, another container): [docker-compose.slim.yml](../docker-compose.slim.yml) |

## Requirements

| What | Detail |
|---|---|
| Docker | Docker Engine 24 or more (Linux), or Docker Desktop (Windows, macOS), with **Docker Compose v2** (`docker compose`). |
| Disk space | **8 to 60 GB for the models** (volume `lutin-models`), 4 GB for the rest. |
| Memory | That of the models you choose: 8 GB of RAM at least for a small model, much more for a big one. |
| Graphics card (optional) | NVIDIA + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host. Without a card, Ollama uses the processor (slower). AMD: see Ollama's documentation (ROCm image). |
| Port | `8777`, published on the host's `127.0.0.1` only (see « Security »). |

## Quick start

**One command** (no card, models kept in a Docker volume, your files in `./travail`):

```bash
mkdir -p lutin/travail && cd lutin
sudo chown 1000:1000 travail          # Linux: the container runs as user 1000
docker run -d --name lutin --restart unless-stopped \
  -p 127.0.0.1:8777:8777 \
  -v lutin-data:/data -v lutin-models:/models -v "$PWD/travail":/travail \
  ghcr.io/slater-proj/lutin:latest
```

With an NVIDIA card, add `--gpus all`.

**Or with Compose** (a file you can keep and edit):

```bash
mkdir lutin && cd lutin
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.yml
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.gpu.yml   # only with an NVIDIA card
mkdir travail && sudo chown 1000:1000 travail

docker compose up -d                                              # no graphics card
# or with an NVIDIA card:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

1. **The PIN code**: `docker logs lutin 2>&1 | grep PIN` (`docker compose logs lutin | grep PIN` with Compose), or `docker exec lutin lutin pin` for a new one.
2. Open **http://localhost:8777**, enter the PIN: your browser is paired.
3. **Install a model**: `docker exec lutin lutin modeles` shows the models recommended for your machine, then  
   `docker exec lutin lutin modeles installer qwen3:8b`  
   (or the Models tab of the interface). The download goes through the Ollama inside the container and stays in the `lutin-models` volume.

In the terminal: `docker exec -it lutin lutin chat`.

**Language**: English by default. Change it in the page (Settings > Language), with `docker exec lutin lutin langue fr`, or with `-e LUTIN_LANGUE=fr`.

## The volumes

| Volume | In the container | Content | Back it up? |
|---|---|---|---|
| `lutin-data` | `/data` | configuration, conversations, memory, action log, paired devices, Ollama log (`ollama.log`) | **yes** |
| `./travail` | `/travail` | **your workspace folder**: the only place Lutin can read and modify | it is your project: already at your place |
| `lutin-models` | `/models` | the models (complete image) | no (can be downloaded again), but heavy |

To put the models on another disk, replace `lutin-models:/models` with a path (`/mnt/big-disk/models:/models`).

**Folder permissions.** The container is not an administrator: it runs as user **1000**. A folder mounted from the host (`./travail`, and a models folder) must be writable by it: `sudo chown 1000:1000 travail`. Without that, Lutin refuses to start with a clear message.

**Several workspace folders.** Mount them under `/travail` and declare them:

```yaml
    environment:
      LUTIN_TRAVAUX: /travail/project-2,/travail/documents
    volumes:
      - ./travail:/travail
      - ./project-2:/travail/project-2
      - ./documents:/travail/documents
```

## The variables

| Variable | Default | Role |
|---|---|---|
| `LUTIN_LANGUE` | – (English) | `fr` or `en`. Forces the language (otherwise, the setting of the page applies). |
| `LUTIN_NIVEAU` | `reseau` | `reseau` (PIN code) or `proxy`. « this machine only » does not exist in a container: the port must not be open without protection. |
| `LUTIN_URL_PUBLIQUE`, `LUTIN_PROXY_IP` | – | `proxy` level: public address (`https://…`) and address(es) of the proxy as Lutin sees them (comma-separated). |
| `LUTIN_TRAVAUX` | – | other workspace folders (commas). |
| `LUTIN_HORS_LIGNE` | – | `1`: strict offline mode (no connection to the Internet; the models must have been downloaded beforehand). |
| `LUTIN_GPU` | – | card declared by hand if it is not detected: `24` or `NVIDIA RTX 4090=24` (memory in GB). |
| `LUTIN_PORT` | `8777` | port inside the container. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` (complete) · `http://ollama:11434` (slim) | where Ollama is. For an Ollama on the host machine (slim image): `http://host.docker.internal:11434` (add `extra_hosts: ["host.docker.internal:host-gateway"]` on Linux). |

These variables are **re-applied at every start**: they are the source of truth for access and workspace folders.

## Security

- The port is published on **`127.0.0.1:8777`**: only the host machine can reach it. For your local network, write `"8777:8777"` in `ports` (the PIN code protects, but read [SECURITY.md](SECURITY.md)); for the Internet, go **behind a proxy** with strong authentication (`LUTIN_NIVEAU=proxy`).
- Automatic approvals (writes, commands) are **turned off** at the `reseau` and `proxy` levels.
- The container is not an administrator; the commands Lutin runs execute **in the container** (with only what it contains: Python, git, sh) and only see `/travail`, `/data` and `/models`. It is one more protection, and a limit: for it to run your project's tools (compiler, tests…), install them in a derived image.
- In the complete image, Ollama listens on the container's `127.0.0.1` only, and its port `11434` is never published. Never publish it.

## NVIDIA card

1. Install the NVIDIA Container Toolkit on the host and restart Docker (`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`).
2. Check: `docker run --rm --gpus all ubuntu nvidia-smi`.
3. Start with `--gpus all` (`docker run`) or `-f docker-compose.gpu.yml` (Compose). Lutin **reads** the card (`nvidia-smi`) to recommend models that fit in it; Ollama uses it.

If the card is not detected (AMD, special configuration): `LUTIN_GPU="My card=16"`. For AMD, use the slim image with Ollama's ROCm image.

## Update, back up, stop

```bash
docker compose pull && docker compose up -d                       # update (volumes are not touched)
docker compose exec lutin lutin sauvegarde /data/backup.zip       # then: docker compose cp lutin:/data/backup.zip .
docker compose down                                               # stop (volumes stay); « down -v » ERASES them
```

Restore: copy the `.zip` into `/data` (`docker compose cp backup.zip lutin:/data/`), stop Lutin (`docker compose stop lutin`), then  
`docker compose run --rm lutin restaurer /data/backup.zip --oui` and `docker compose start lutin`.

Published images: `ghcr.io/slater-proj/lutin:latest` (latest version, complete), `:X.Y.Z` (a precise version), `:slim` and `:X.Y.Z-slim` (Lutin alone), `:rc-<branch>` and `:rc-<branch>-slim` (candidate of a branch, to test before merging).

## Troubleshooting

| Symptom | Lead |
|---|---|
| Lutin stops with « volumes … must be writable » | `sudo chown 1000:1000 travail` (and `docker compose down` then `up` if the `lutin-data` volume was created by another user: `docker compose run --rm --user root lutin chown -R 1000:1000 /data /models`) |
| « Ollama is not responding » | Complete image: look at `/data/ollama.log` (`docker compose exec lutin tail /data/ollama.log`). Slim image: `docker compose logs ollama`; with Ollama on the host: `OLLAMA_URL=http://host.docker.internal:11434`. |
| The page answers « host name not allowed » | You reach it by a name Lutin does not know. Use `localhost`, a private address, or (`proxy` level) the address declared in `LUTIN_URL_PUBLIQUE`. |
| The recommended models are too small | The card is not seen by Lutin: `--gpus all` / `-f docker-compose.gpu.yml`, or `LUTIN_GPU`. |
| Model download impossible | `LUTIN_HORS_LIGNE=1` is on, or there is no access to the Internet. |
