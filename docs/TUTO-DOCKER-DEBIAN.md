**English** · [Français](TUTO-DOCKER-DEBIAN.fr.md)

# Installing Lutin with Docker on Debian, step by step

This tutorial goes from “a bare Debian” to “Lutin reachable at `https://lutin.example.com` behind your reverse proxy and Authelia”. Each step says **what to type**, **what you should see**, and **what to do otherwise**. For the full reference (variables, volumes, graphics cards), see [DOCKER.md](DOCKER.md).

> **Honesty.** The images are built and started by the CI, and the “reverse proxy + Authelia” setup was checked with a fake proxy. None of this has run with **your** Debian, **your** Authelia or **your** processor: follow the steps checking each result, and tell me where it gets stuck.

## 0. What you need

| What | Detail |
|---|---|
| A Debian 12 or 13 server | a mini PC is enough; `sudo` access |
| Disk space | 5 GB for Lutin and Ollama, **+ 3 to 10 GB per model** (a 4-billion-parameter model weighs about 3 GB) |
| Memory | enough to run a model: **8 GB free** allows small models (3 to 4 billion parameters) and, borderline, 7 to 8 billion |
| A domain name | for example `lutin.example.com`, pointing to your server (or your router) |
| A reverse proxy + Authelia | nginx, Traefik or Caddy, already installed; otherwise skip step 7 and use the PIN code (step 8) |

## 1. Install Docker (if it is not there yet)

Check first:

```bash
docker --version && docker compose version
```

If both commands answer, go to step 2. Otherwise, install Docker Engine from the official repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

To use Docker without `sudo` (careful: belonging to the `docker` group amounts to having administrator rights on the machine):

```bash
sudo usermod -aG docker $USER      # then log out and back in
```

*You should see*: `docker run --rm hello-world` prints “Hello from Docker!”.

## 2. Prepare the folders

Lutin runs in the container as user **1000**. The server folders it must be able to write therefore belong to that user:

```bash
sudo mkdir -p /opt/lutin/workspace
sudo chown -R 1000:1000 /opt/lutin/workspace
cd /opt/lutin
```

`/opt/lutin/workspace` is the **only place Lutin can read and modify** (its missions, the documents it creates…). Put in it what you want to entrust to it. Conversations, memory and settings live in a Docker volume (`lutin-data`); the models in another one (`lutin-models`).

## 3. The network shared with your reverse proxy

Lutin publishes **no port**: your reverse proxy reaches it through a common Docker network. Create it once, with a fixed subnet (Lutin only accepts Authelia's identity when it comes from this network):

```bash
docker network create --subnet 172.30.0.0/24 proxy
docker network ls | grep proxy
```

If your reverse proxy already has a network, **use it** instead of creating one: `docker network inspect <name> | grep Subnet` gives its subnet. Your reverse proxy must be connected to this same network.

## 4. The `docker-compose.yml` file

```bash
curl -fsSL -o docker-compose.yml https://raw.githubusercontent.com/Slater-proj/lutin/main/docker-compose.proxy.yml
nano docker-compose.yml
```

Change these lines (the rest suits a small shared server):

| Line | Put |
|---|---|
| `LUTIN_URL_PUBLIQUE` | your address, with `https://`: `https://lutin.example.com` |
| `LUTIN_PROXY_IP` | the subnet from step 3: `172.30.0.0/24` |
| `LUTIN_ADMINS` | your **Authelia** user name (the `Remote-User` one): `alice` |
| `LUTIN_LANGUE` | `fr` or `en` |
| `mem_limit` and `LUTIN_BUDGET_GO` | the memory you want to reserve for Lutin: `10g` and `"8"` for about 10 GB free |
| `./workspace:/workspace` | `/opt/lutin/workspace:/workspace` |

Check the file without starting anything:

```bash
docker compose config > /dev/null && echo "valid file"
```

## 5. Start

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail 30 lutin
```

*You should see*: `lutin` in `Up (healthy)` state after about a minute. In the logs: the start-up line and the public address.

*If it does not start*:
- “volumes … writable” → step 2 (`chown 1000:1000`) was not done on that folder.
- `network proxy declared as external, but could not be found` → step 3.
- The container restarts in a loop → `docker compose logs lutin` says why.

## 6. Install a model

```bash
docker compose exec lutin lutin models                    # the models advised for this machine
docker compose exec lutin lutin models install qwen3:4b
```

With an 8 GB budget and a CPU alone, Lutin advises `qwen3:4b` or `llama3.2:3b` (comfortable); `qwen3:8b` is “borderline” (slow). The download goes to the `lutin-models` volume. You can also do it from the page (Models tab).

## 7. Connect the reverse proxy and Authelia

Three requirements, whatever the proxy: **Authelia in front** (passing the identity in `Remote-User`), the **original `Host` forwarded**, and **no buffering** of responses (Lutin shows the answer word by word). See the nginx, Traefik and Caddy examples in [DOCKER.md](DOCKER.md), “Homelab” section.

On Authelia's side, add an access rule for your domain (adapt to your configuration):

```yaml
access_control:
  rules:
    - domain: 'lutin.example.com'
      policy: 'two_factor'
```

Then reload Authelia and your reverse proxy.

## 8. First try

1. Open `https://lutin.example.com`: Authelia asks you to sign in, then Lutin's page opens.
2. At the top left, next to “Lutin”, pick the installed model.
3. Write “Hello, can you hear me?”: the answer must appear **word by word**. If it only shows at the end, the proxy buffers the responses (step 7).
4. Try “Create a short meeting summary as a PDF in the working folder”: a card with **Download** appears under the message.

*Without a reverse proxy* (trying on your network): in the file replace `LUTIN_NIVEAU: proxy` with `reseau`, remove `LUTIN_URL_PUBLIQUE`, `LUTIN_PROXY_IP` and `LUTIN_ADMINS`, add `ports: ["8777:8777"]`, then `docker compose exec lutin lutin pin` gives a code to enter on the page (read [SECURITY.md](SECURITY.md) first).

## 9. Day to day

| Need | Command |
|---|---|
| Update | `docker compose pull && docker compose up -d` (volumes are kept) |
| See the logs | `docker compose logs -f lutin` |
| Back up | `docker compose exec lutin lutin backup /data/sauvegarde.zip && docker compose cp lutin:/data/sauvegarde.zip .` |
| Stop | `docker compose down` (volumes stay; `down -v` **erases** them) |
| Diagnosis to paste in a report | `docker compose exec lutin lutin doctor` |
| See what Lutin modified | `docker compose exec lutin lutin log` |

Back up the `lutin-data` volume (conversations, memory, settings) and your `/opt/lutin/workspace` folder. Models can be downloaded again.

## 10. Quick troubleshooting

| Symptom | Lead |
|---|---|
| “host name not allowed” | the proxy does not forward the original `Host`, or `LUTIN_URL_PUBLIQUE` does not match the address typed |
| Lutin's sign-in page instead of Authelia | Authelia is not in front, or `LUTIN_PROXY_IP` is not the network Lutin sees (`docker network inspect proxy`) |
| Everything works but I cannot create a mission or delete a file | your user name is not in `LUTIN_ADMINS` |
| Jerky answers, or all at once | proxy buffering (`proxy_buffering off` for nginx) |
| Very slow answers | model too big for the CPU; take a smaller one and lower the context window (Settings) |
| “Ollama does not answer” | `docker compose exec lutin tail /data/ollama.log` |

To uninstall: `docker compose down -v` erases the volumes (conversations included), then `docker rmi ghcr.io/slater-proj/lutin:latest`; finally delete `/opt/lutin`.
