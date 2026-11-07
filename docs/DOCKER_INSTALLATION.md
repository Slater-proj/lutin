**English** · [Français](DOCKER_INSTALLATION.fr.md)

# Installing Lutin with Docker, engines included

For the all-in-one image (Lutin and Ollama in one container), read [DOCKER.md](DOCKER.md) first. This page covers the case where **the engine is a container next to Lutin** (Ollama or llama.cpp), and what to know about Docker on Linux and Docker Desktop (Windows, WSL2).

> **Honesty.** The Ollama and llama.cpp profiles in `docker-compose.moteurs.yml` are **checked on paper and by file tests**, **not on real hardware**. The `llamacpp-cuda`, `llamacpp-vulkan` and `llamacpp-intel` profiles have never run with a real card: if you try them, tell me what happened.

## 1. Choosing the engine: Compose profiles

One file, one profile per engine:

```bash
curl -fsSLO https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.moteurs.yml
mkdir travail && sudo chown 1000:1000 travail            # Linux: the container runs as user 1000

docker compose -f docker-compose.moteurs.yml --profile ollama up -d            # Ollama (the simplest)
docker compose -f docker-compose.moteurs.yml --profile llamacpp-cpu up -d      # llama.cpp on the processor
docker compose -f docker-compose.moteurs.yml --profile llamacpp-cuda up -d     # NVIDIA card
docker compose -f docker-compose.moteurs.yml --profile llamacpp-vulkan up -d   # AMD or Intel card
docker compose -f docker-compose.moteurs.yml --profile llamacpp-intel up -d    # Intel (SYCL)
```

Lutin already knows where the engine is: the file sets `OLLAMA_URL` and `LUTIN_LLAMACPP_URL`. The engine's card in **Settings > Engines** is pre-filled, nothing to type. An address you set in the page wins over the variable.

**Not sure which one?** Ollama. To compare on your machine, see [BENCH_MOTEURS.md](BENCH_MOTEURS.md).

### llama.cpp: one model file at a time

The llama.cpp container serves **one** GGUF file. Put it in the `lutin-models` volume, then give its name:

```bash
LUTIN_GGUF=qwen3-8b-q4_k_m.gguf docker compose -f docker-compose.moteurs.yml --profile llamacpp-cuda up -d
```

Changing model = starting again with another `LUTIN_GGUF`. (Router mode, several models without restarting, is reserved for the llama.cpp Lutin manages itself outside Docker.)

### Graphics cards

| Card | Profile | Needs |
|---|---|---|
| NVIDIA | `llamacpp-cuda` (or Ollama with `docker-compose.gpu.yml`) | the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host |
| AMD, Intel (Vulkan) | `llamacpp-vulkan` | `/dev/dri`; `RENDER_GID` = group of `/dev/dri/renderD*` (`getent group render \| cut -d: -f3`) |
| Intel (SYCL) | `llamacpp-intel` | same |
| none | `llamacpp-cpu` or `ollama` | nothing |

Measure, do not assume: an integrated graphics chip can be **slower** than the processor (one test on a Core Ultra 5: about 8 against 11 tokens/s).

## 2. Docker on Linux

Docker Engine 24 or more and the Compose v2 plugin (`docker compose`, with a space). Step by step from a bare Debian: [TUTO-DOCKER-DEBIAN.md](TUTO-DOCKER-DEBIAN.md).

## 3. Docker Desktop on Windows (WSL2)

- Docker Desktop uses **WSL2**, which takes half the PC's memory by default. A medium model needs more: create `%UserProfile%\.wslconfig` with

  ```ini
  [wsl2]
  memory=24GB
  ```

  then `wsl --shutdown` and restart Docker Desktop.
- **Keep your volumes inside Docker** (named volumes, as in our files): a mounted Windows folder (`C:\...`) is much slower for multi-GB files.
- The NVIDIA card is given to containers by the Windows driver (no Toolkit to install in WSL2 with a recent Docker Desktop). AMD and Intel are not reliable here: prefer the llama.cpp that Lutin installs directly on Windows.

## 4. Checking: `lutin doctor`

```bash
docker compose exec lutin lutin doctor      # inside the container
lutin doctor                                # on the host: Docker version, Compose, memory given to Docker
```

Inside the container, the diagnostic says: whether `/data` and `/models` are **real volumes** (otherwise your settings, conversations and models vanish when the container is recreated), whether they are writable, the memory the container sees, whether the engines next to it answer, and the visible card. It holds no personal data: you can paste it into a problem report.

## 5. Restarting, recreating, updating: nothing is lost

Settings, conversations, memory and engines live in `lutin-data`; models in `lutin-models`. These two **named volumes** survive `docker compose down`, `docker compose up -d --force-recreate` and `docker compose pull` (only `docker compose down -v` deletes them: do not type it lightly). Starting the container **re-applies** the configuration from the environment variables (it installs nothing again and erases nothing). A CI test checks it: it creates a container, writes a piece of data, recreates the container, and checks the data is still there.

To update: `docker compose pull && docker compose up -d`.

## 6. First launch

While **no engine is ready**, the page does not send you to the Models tab (where nothing would work): the tab is greyed out with the reason, and a card offers to install the recommended engine, pick another one, or do it later. With the engine's Compose profile, the engine is ready as soon as its container answers.
