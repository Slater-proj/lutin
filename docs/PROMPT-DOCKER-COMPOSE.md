**English** · [Français](PROMPT-DOCKER-COMPOSE.fr.md)

# A prompt for your local AI to write Lutin's `docker-compose.yml`

This prompt is written **for your local AI** (the one that knows your machine and your docker-compose charter). Copy the block below and paste it into a conversation with it. It must be able to work alone: explore your machine read-only, find **your charter**, then hand you a ready-to-use `docker-compose.yml`, a `.env` file, the commands to run and the checks, without asking needless questions.

Before pasting it, replace the three values marked **TO REPLACE** (your domain name, your Authelia user name, the memory budget for the models): the AI discovers the rest itself (processor, memory, reverse proxy, networks). The human step-by-step tutorial is in [TUTO-DOCKER-DEBIAN.md](TUTO-DOCKER-DEBIAN.md).

````text
# MISSION

You are my Docker system administrator. Produce, AUTONOMOUSLY, a ready-to-use `docker-compose.yml` (plus its `.env` and the start-up commands) to deploy **Lutin**, a local AI assistant, on my Debian mini PC, following **MY docker-compose charter** (my usual conventions). Only ask me a question if a piece of information cannot be found AND is blocking; in that case, group all your questions in one go.

# WHAT I GIVE YOU

My machine: a server running Debian with Docker and Docker Compose v2 (installed, or to be installed). Describe it yourself: processor, total AND FREE memory, disk, graphics card if any (`lscpu`, `free -h`, `df -h`, `nvidia-smi` if it exists). My other services share the machine: only count on the FREE memory.
Domain: Lutin must be reachable by my reverse proxy at **https://lutin.example.com**   ← TO REPLACE with my real domain name, protected by **Authelia** (which passes the identity in the `Remote-User` header).
My Authelia user name (Lutin administrator): **alice**   ← TO REPLACE.
Memory I reserve for Lutin's models: **8 GB**   ← TO REPLACE (with no value, take about 60% of the free memory, at most).
My reverse proxy: you must discover it (nginx / Nginx Proxy Manager / SWAG / Traefik / Caddy).

# MY DOCKER-COMPOSE CHARTER

It is authoritative for the form (names, directory layout, networks, labels, logs, security, backups…). Find it yourself: look in your memory, in your reference files, and in my existing stacks (for example `/opt/stacks`, `/srv`, `~/docker`, `/home/*/docker`, any folder containing several `docker-compose.yml`). Read 2 or 3 of my stacks that already run to confirm my real habits: stack folder name, project name, external network used, how volumes are named, use of a `.env`, restart policy, resource limits, logging, reverse-proxy labels, time zone, user/UID, location of persistent data, container naming.
- If you find my charter: apply it point by point, and quote where it comes from in one line.
- If you cannot find it: say so in one line, infer my habits from my existing stacks, and list the conventions you kept.
- Where my charter and Lutin's technical constraints (below) contradict each other, Lutin's constraints win: flag each deviation in one line, with the reason.

# DISCOVERY (READ-ONLY, CHANGE NOTHING)

If you have a terminal on the machine, run (and analyse) for example:
`docker --version && docker compose version` · `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Networks}}'` · `docker network ls` then `docker network inspect <the reverse proxy's network>` (subnet and gateway) · `free -h` · `df -h` · `id` · `ls` of the stack folders · the existing `docker-compose*.yml` files · the reverse proxy configuration and the Authelia middleware (exact names of middlewares, entrypoints, certificate resolver) · `docker volume ls`.
If you do NOT have terminal access: give me, in one go, the exact list of commands to run and of what I must paste back, then wait.
Run NO command that changes anything (no `up`, `down`, `rm`, `prune`, `chown`, `mkdir`) before my explicit agreement.

# WHAT YOU MUST KNOW ABOUT LUTIN (everything is exact; invent nothing else)

- Image: `ghcr.io/slater-proj/lutin:latest` = Lutin alone, light (this is the one to use; the engine, e.g. Ollama, is installed from the page into the `/engines` volume). A precise version: `ghcr.io/slater-proj/lutin:X.Y.Z`. The `:slim` and `:rocm` tags are the same image.
- Port inside the container: **8777** (HTTP). Do not publish it if the reverse proxy is in Docker: it reaches `http://lutin:8777` through a common Docker network. If the reverse proxy runs on the host: publish `127.0.0.1:8777:8777` only.
- Ollama (once installed from the page) listens inside the container (127.0.0.1:11434): **never publish port 11434**. Mount a volume on `/engines` (engines) in addition to `/data`, `/models` and `/workspace`.
- The container runs as user **1000:1000**: any host folder mounted writable must belong to 1000:1000 (`chown 1000:1000`), otherwise Lutin refuses to start with a clear message.
- Volumes: `/data` (configuration, conversations, memory, devices: TO BE BACKED UP), `/models` (Ollama models: big, can be downloaded again), `/workspace` (the ONLY folder Lutin can read and modify; a host folder to mount). Other working folders, if any: under `/workspace/...` and listed in `LUTIN_WORKSPACES` (comma-separated).
- Environment variables (the ONLY ones to use):
  `LUTIN_NIVEAU=proxy` (identity provided by the reverse proxy) · `LUTIN_URL_PUBLIQUE=https://lutin.example.com` (any other host name is refused) · `LUTIN_PROXY_IP=<network or address of the reverse proxy as Lutin sees it>` (e.g. `172.30.0.0/24`; the value must match the real subnet of the shared network) · `LUTIN_ADMINS=alice` (Authelia user names allowed to configure from the page; empty = command line only) · `LUTIN_LANGUE=fr` · `LUTIN_BUDGET_GO=8` (maximum GB for the models) · `LUTIN_HORS_LIGNE=1` (optional: no outgoing connection at all) · `LUTIN_WORKSPACES` · `LUTIN_GPU` (useless here) · `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=5m` (memory saving).
- Memory limit: `mem_limit` (or `deploy.resources.limits.memory`) a bit above the models' budget (for example 10g for 8 GB): Lutin adapts its model advice to this limit. With ~8 GB for the models, the right choices are models of 3 to 4 billion parameters (`qwen3:4b`, `llama3.2:3b`); 7 to 8 billion is borderline. Without an NVIDIA or AMD card given to the container, everything runs on the CPU (integrated graphics chips are not used).
- Health: the image already has a HEALTHCHECK (`curl -fsS http://127.0.0.1:8777/`). Only redefine it if my charter requires it, with the same command and a `start_period` of at least 20 s (40 s advised: Ollama starts in the same container).
- The reverse proxy must: (1) be behind Authelia and pass the identity in `Remote-User`, overwriting any `Remote-User` coming from the client; (2) forward the original `Host`; (3) NOT buffer responses (the answer is shown word by word: `proxy_buffering off` for nginx); (4) allow long timeouts (3600 s) and 30 MB uploads.
- `restart: unless-stopped`. No secret is needed for Lutin itself (the identity comes from Authelia).

# DELIVERABLES (in this order)

1. **Summary** (5 lines at most): what you discovered (reverse proxy, network, subnet, conventions) and where my charter comes from.
2. A complete **`docker-compose.yml`**, commented in one line per non-obvious choice, with the reverse-proxy labels/blocks I really use (and only those).
3. **`.env`** (concrete values, no needless secret).
4. **Reverse proxy / Authelia files to add**: the exact block (nginx, Traefik, Caddy…) AND the Authelia `access_control` rule for my domain (`two_factor` policy unless my charter says otherwise).
5. **Start-up commands**, in order: creating the stack folder and the working folder, `chown 1000:1000`, creating the network if missing, `docker compose config`, `pull`, `up -d`, installing a model (`docker compose exec lutin lutin modeles installer qwen3:4b`), verification.
6. **Checks** with the expected result for each: container `healthy`, page reachable behind Authelia, answer shown word by word, my user name recognised as administrator.
7. **Rollback**: how to undo everything without touching my other stacks.
8. **Deviations** between my charter and Lutin's constraints, one per line.

# RULES

- Check your file before handing it over: `docker compose config` must pass (run it if you can without starting anything; otherwise re-read it as that tool would: indentation, valid keys, declared networks and volumes).
- No `latest` if my charter pins versions: in that case, put the latest Lutin release you know and tell me to check https://github.com/Slater-proj/lutin/releases.
- Expose no needless port, add no service I did not ask for, do not touch my other stacks.
- If a value depends on my machine and you cannot read it (subnet, network name, middleware name), put a clear value between angle brackets `<…>`, explain how to find it, and do not silently guess it.
- Run nothing that changes anything without my explicit agreement: end with “Ready to apply?” and wait.
````

## What it gives in practice

The AI hands you a summary, the `docker-compose.yml`, the `.env`, the block to add to your reverse proxy and to Authelia, the list of commands and the checks, then asks for your agreement before applying. If it cannot find your charter, it tells you and lists the conventions it inferred from your existing stacks: re-read them before accepting.

**What Lutin guarantees**: the image, port, user 1000, volumes and variables in the prompt match exactly what Lutin reads (the [docker-compose.proxy.yml](../docker-compose.proxy.yml) file is the reference version: the AI can use it as a model). **What it does not**: everything that depends on your charter and your machine, which the AI must discover.
