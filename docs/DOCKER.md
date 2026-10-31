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

## Graphics card in the container

A container does not see the graphics card unless you hand it over. Without it, everything runs on the processor (slower, but it works).

| Your card | What to do | Image |
|---|---|---|
| **NVIDIA** (Linux) | install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host, then `docker run --gpus all …` or `-f docker-compose.gpu.yml` | `:latest` |
| **NVIDIA** (Windows) | Docker Desktop with the WSL 2 backend and a recent NVIDIA driver; then the same `--gpus all` | `:latest` |
| **AMD** (Linux, ROCm-supported card) | amdgpu driver on the host, then `--device /dev/kfd --device /dev/dri --group-add video --group-add <render group id>` or `-f docker-compose.amd.yml` | `:rocm` |
| **Intel / integrated graphics** | not used by Ollama in the containers: the processor does the work (budget = RAM) | `:latest` |
| **Mac** | Docker on macOS cannot give the Apple GPU to a container: run Ollama natively on the Mac and use the `:slim` image with `OLLAMA_URL=http://host.docker.internal:11434` | `:slim` |

**Check that it works** (do not trust, check):

1. NVIDIA: `docker run --rm --gpus all ubuntu nvidia-smi` must list the card; then `docker exec lutin nvidia-smi` too.
2. The first lines of `/data/ollama.log` (`docker exec lutin head -20 /data/ollama.log`) say which card the container sees (NVIDIA, `/dev/kfd`, `/dev/dri`); Ollama's own lines then say whether it found a compute device.
3. In the page, **Health > video memory** shows the card, and once a model is loaded, « model loaded at … % on the card »: **100 %** means the card does the work; **0 %** means the processor does (the card was not given or not supported).
4. `docker exec lutin lutin doctor` says « No usable graphics card » and what to add if the container sees none.

AMD: ROCm supports a limited list of cards; for others, Ollama's documentation explains `HSA_OVERRIDE_GFX_VERSION`. The `:rocm` image and `docker-compose.amd.yml` have **never been tried on a real AMD card**: tell me what you get.

If Lutin does not see the card but Ollama does, declare it by hand so that the recommended models fit: `LUTIN_GPU="My card=16"` (memory in GB).

## Homelab: a Debian mini PC behind a reverse proxy and Authelia

The case of a small shared server (for example an Intel Core Ultra 5 mini PC with 32 GB of RAM of which only about ten are free), running Debian, where Lutin is reachable at `https://lutin.example.com` behind your reverse proxy and **Authelia**.

> **Honesty.** This setup was checked with a **fake proxy** (simulated `Host` and `Remote-User` headers: access, refusal without identity, refusal of a wrong host name, administration rights) and by the CI tests. It has **never run with a real Authelia, a real Debian or this processor**: the response times below are orders of magnitude, not measurements.

### 1. Run Lutin

```bash
docker network create --subnet 172.30.0.0/24 proxy      # once; your reverse proxy must be on this network too
mkdir -p travail && sudo chown 1000:1000 travail
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.proxy.yml
# edit: LUTIN_URL_PUBLIQUE, LUTIN_PROXY_IP (the proxy's network), LUTIN_ADMINS (your Authelia user name)
docker compose -f docker-compose.proxy.yml up -d
```

The [docker-compose.proxy.yml](../docker-compose.proxy.yml) file publishes **no port**: the reverse proxy reaches `http://lutin:8777` on the shared network. If your proxy runs on the host rather than in Docker, publish `127.0.0.1:8777:8777` and set `LUTIN_PROXY_IP: 172.17.0.1`.

| Variable | Role here |
|---|---|
| `LUTIN_NIVEAU=proxy` | the identity comes from the proxy (`Remote-User` header set by Authelia); Lutin trusts this header **only** when it comes from an address in `LUTIN_PROXY_IP` |
| `LUTIN_URL_PUBLIQUE` | the public address: any other host name is refused (so the proxy must **forward the original `Host`**) |
| `LUTIN_PROXY_IP` | the proxy's address or network as Lutin sees it (`docker network inspect proxy`) |
| `LUTIN_ADMINS` | the Authelia user names allowed to **configure from the page**: working folders, extensions, missions, deleting created files. Empty: everything is configured with `docker exec lutin lutin …` and the page is only for chatting. Other Authelia users can only chat. |
| `mem_limit` | the memory the container may take: **Lutin adapts to it** (without a limit it would see the machine's 32 GB and advise models that are too big) |
| `LUTIN_BUDGET_GO` | sets the maximum for the models (GB) if you prefer not to limit the container |
| `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=5m` | one request at a time, one model at a time, RAM given back after 5 minutes of silence |

### 2. Set up the reverse proxy

Three things matter to Lutin, whatever the proxy:

1. **Authelia in front**, passing the identity in `Remote-User` (and the proxy **overwrites** any `Remote-User` the client sends).
2. **The original `Host` is forwarded** (`lutin.example.com`), otherwise Lutin answers “host name not allowed”.
3. **No buffering of responses**: Lutin shows the answer word by word (a continuous stream). A proxy that holds everything in memory until the end makes it look like nothing happens. Lutin sends `X-Accel-Buffering: no` (nginx honours it); other proxies do not buffer by default. Also allow **long timeouts** (an answer on a CPU can take several minutes) and **30 MB** uploads (attachments).

nginx (with Authelia's usual `auth_request` snippets):

```nginx
location / {
    include /config/nginx/authelia-location.conf;       # or your equivalent: auth_request + $user from Remote-User
    proxy_pass http://lutin:8777;
    proxy_set_header Host $host;
    proxy_set_header Remote-User $user;                 # the identity Authelia saw, never the client's
    proxy_buffering off;
    proxy_read_timeout 3600s;
    client_max_body_size 30m;
}
```

Traefik (service labels, with your `authelia` middleware exposing `Remote-User` in `authResponseHeaders`):

```yaml
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy
      - traefik.http.routers.lutin.rule=Host(`lutin.example.com`)
      - traefik.http.routers.lutin.entrypoints=websecure
      - traefik.http.routers.lutin.tls.certresolver=letsencrypt
      - traefik.http.routers.lutin.middlewares=authelia@docker
      - traefik.http.services.lutin.loadbalancer.server.port=8777
```

Caddy:

```caddy
lutin.example.com {
    forward_auth authelia:9091 {
        uri /api/authz/forward-auth
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }
    reverse_proxy lutin:8777 {
        flush_interval -1
    }
}
```

### 3. Pick models for this kind of machine

With no usable graphics card (the Intel integrated graphics are not used by Ollama in a container), everything runs on the CPU. With ~8 GB for the models, Lutin advises:

| Model | Lutin's verdict | What to expect (estimate) |
|---|---|---|
| `qwen3:4b`, `llama3.2:3b`, `qwen3:1.7b` | comfortable | a few words per second; the right choice for chatting and simple missions |
| `qwen3:8b`, `qwen2.5-coder:7b` | borderline | slower; workable for code or careful writing, not for a lively conversation |
| `qwen3:14b` and up | too big | does not fit the budget |

`docker exec lutin lutin modeles` gives the list for your machine. Lower the **context window** to 8,192–12,288 tokens in Settings: on a CPU, re-reading 24,000 tokens at every answer takes minutes.

### 4. What works and what does not in this setup

| Feature | In the container |
|---|---|
| Conversation, tools, files in `/travail`, PDF and Word, long missions (they run **inside the container**: they only see `/travail`) | ✔ |
| Telegram, email, X, web search | ✔ (outgoing connections) |
| Download a created file, the “Created files” list and tidying up | ✔ |
| **Open** a file with an application | ✘ hidden: a server has no desktop, use Download |
| Auto approval / Auto commands in the conversation | ✘ off at the proxy level (security rule): every command asks for your click. An **“Autonomous” mission** runs by itself, inside the container. |
| Page preview (`apercu_page`) | ✘ no browser in the image: the message says so |
| ComfyUI (images) | ✘ ComfyUI does not run in the container, and a CPU alone is too slow to generate images |
| Intel integrated graphics | ✘ not used by Ollama in a container |

**Updates and backup**: see below; back up the `lutin-data` volume and your `travail` folder.

## Addons in the container

The settings, secrets and state of the addons live in the `/data` volume, so they survive an update. **Telegram, email, X and background work** work as on the host (background work only sees the work folders mounted in the container). **ComfyUI** cannot be started by a container that does not hold it: run Lutin directly on the machine for that addon, or install ComfyUI in your own image and mount its folder.

## Update, back up, stop

```bash
docker compose pull && docker compose up -d                       # update (volumes are not touched)
docker compose exec lutin lutin sauvegarde /data/backup.zip       # then: docker compose cp lutin:/data/backup.zip .
docker compose down                                               # stop (volumes stay); « down -v » ERASES them
```

Restore: copy the `.zip` into `/data` (`docker compose cp backup.zip lutin:/data/`), stop Lutin (`docker compose stop lutin`), then  
`docker compose run --rm lutin restaurer /data/backup.zip --oui` and `docker compose start lutin`.

Published images: `ghcr.io/slater-proj/lutin:latest` (latest version, complete), `:X.Y.Z` (a precise version), `:slim` and `:X.Y.Z-slim` (Lutin alone), `:rocm` and `:X.Y.Z-rocm` (complete, for AMD cards), `:rc-<branch>` and its `-slim` / `-rocm` variants (candidate of a branch, to test before merging).

## Troubleshooting

| Symptom | Lead |
|---|---|
| Lutin stops with « volumes … must be writable » | `sudo chown 1000:1000 travail` (and `docker compose down` then `up` if the `lutin-data` volume was created by another user: `docker compose run --rm --user root lutin chown -R 1000:1000 /data /models`) |
| « Ollama is not responding » | Complete image: look at `/data/ollama.log` (`docker compose exec lutin tail /data/ollama.log`). Slim image: `docker compose logs ollama`; with Ollama on the host: `OLLAMA_URL=http://host.docker.internal:11434`. |
| The page answers « host name not allowed » | You reach it by a name Lutin does not know. Use `localhost`, a private address, or (`proxy` level) the address declared in `LUTIN_URL_PUBLIQUE`. |
| The recommended models are too small | The card is not seen by Lutin: `--gpus all` / `-f docker-compose.gpu.yml`, or `LUTIN_GPU`. |
| Model download impossible | `LUTIN_HORS_LIGNE=1` is on, or there is no access to the Internet. |
