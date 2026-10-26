**English** · [Français](SECURITY.fr.md)

# Security

Lutin can read files and run commands on your machine, at the request of a language model. That is useful, and it is exactly what must not be left to just anyone. This page explains what protects you, level by level, and what remains your responsibility.

## Rules that apply everywhere

- **Ollama (port 11434) is never exposed by Lutin.** It stays on `127.0.0.1`. Do not change that.
- Every file change and every command asks for your **approval**, unless you tick the « automatic approval » boxes.
- Lutin only reads and modifies the **workspace folder** chosen at installation.
- The token written into the page protects against requests coming from **other websites** (CSRF). The host name (`Host`) and the origin (`Origin`) are checked: a malicious site cannot make your browser talk to Lutin (« DNS rebinding »).
- Content read on the web is considered **untrusted**: after a web read, automatic approval is suspended for the rest of the request.

## Level 1: this machine only (default)

The server listens on `127.0.0.1`. Nobody else can open a connection. No password.

## Level 2: local network

- The server listens on the local network address.
- **Pairing**: `lutin pin` (or the display at startup) gives a 6-digit code valid for 10 minutes, usable once. Five mistakes invalidate the code and block attempts for 5 minutes. Attempts are also limited per address.
- Each device gets a session (`HttpOnly`, `SameSite=Strict` cookie, 30 days). `lutin appareils` lists them, `lutin appareils revoquer [id]` cuts them. Only the **fingerprints** of the sessions are stored.
- The requested host name must be a private address or a local name.
- **Automatic approvals are turned off**, even if the settings file turns them on.
- Firewall: open it **only** for your private network. On Windows, a rule limited to the « Private » profile and to your subnet; never open it on the « Public » profile.
- Plain HTTP on your network: the PIN and the session travel in clear text over your Wi-Fi. For a shared or unsafe network, use level 3 with HTTPS.

> Anyone who knows a valid PIN on your network can ask Lutin to read the files of the workspace folder. Do not put secrets in that folder.

## Level 3: behind a reverse proxy

Lutin is not exposed: the proxy (Authelia, Authentik, oauth2-proxy…) is, and it authenticates.

At installation, you give:

- the **public address** (`https://lutin.example.com`), used to validate `Host` and `Origin`;
- the **trusted proxy address**, that is the one Lutin sees when the proxy talks to it.

Lutin only accepts the identity (`Remote-User` by default) **if the connection comes from the declared proxy address**. Anyone can write `Remote-User: admin` in a request: if it does not come from the proxy, the header is ignored (tested).

> **Warning.** Exposing to the Internet an assistant able to read files and run commands is risky. Only do it behind strong authentication (ideally with a second factor), a valid HTTPS, and keep manual approvals (they are enforced at this level). A flaw in your proxy, or a bad configuration, opens your workspace folder.

### What the proxy must do

1. **Authenticate** before forwarding.
2. **Overwrite** the identity header (`Remote-User`) with the value coming from authentication, never the client's.
3. **Forward the original `Host` header** (otherwise `Host` and `Origin` no longer match and writes are refused).
4. **Not buffer the responses** (they arrive continuously) and accept **long durations** (an answer can last several minutes).

### Examples (to adapt, not tested here)

**Nginx with Authelia** (the `authelia-authrequest.conf` fragment is the one from Authelia's documentation and defines `$user`):

```nginx
server {
    listen 443 ssl;
    server_name lutin.example.com;
    # certificates ...
    location / {
        include /config/nginx/authelia-authrequest.conf;
        proxy_pass http://127.0.0.1:8777;
        proxy_set_header Host $host;
        proxy_set_header Remote-User $user;      # replaces any header sent by the client
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

**Caddy**:

```caddyfile
lutin.example.com {
    forward_auth authelia:9091 {
        uri /api/authz/forward-auth
        copy_headers Remote-User Remote-Groups
    }
    reverse_proxy 127.0.0.1:8777 {
        flush_interval -1
    }
}
```

**Traefik**: a `forwardAuth` middleware towards Authelia with `authResponseHeaders: [Remote-User]`, then the service towards `http://127.0.0.1:8777`.

In every case, tell Lutin the address the proxy uses to talk to it: `127.0.0.1` if the proxy runs on the same machine, the address of the proxy's container or machine otherwise.

## Strict offline mode

`lutin hors-ligne oui` (or the « Offline » box in the interface, or `LUTIN_HORS_LIGNE=1`): **no connection to the Internet at all**.

- Allowed: this machine, **Ollama** (the `OLLAMA_URL` address), and the extensions you declared (`LUTIN_OUTIL_URL`, `COMFY_URL`).
- Blocked: web search and reading (the tools are not even offered to the model any more), online catalogue, model and Lutin updates, model downloads (Ollama downloads them itself: the action is refused).
- A single place in the code decides (`lutin/horsligne.py`) and a test watches the **real connections** (`tests/test_hors_ligne.py`): none to anything other than this machine.
- It can only be **turned off** from this machine (not remotely, even with a valid session).
- Honest limits: Lutin does not control Ollama itself nor the rest of your system. For a total guarantee, also cut the network of the container or machine.

## Workspace folders

Lutin only reads and modifies the **workspace folder** of the conversation. Several folders are possible; only one is active at a time (if an answer is working in a folder, you cannot switch before it ends, nor start one in another).

- A folder must exist, must not be the root of a disk, nor **contain or be inside Lutin's folders** (configuration, data, memory, cache).
- **Adding or removing** a folder can only be done from this machine: at the « this machine only » level, or with `lutin travaux`. A paired device (network level) or a proxy identity can **choose** an already declared folder, never add one: otherwise a remote access could declare `/` or `C:\`.

## Action log

Every file modified, every command run, every module installed is recorded in `journal-actions.jsonl`: **when, which tool, on which target, in which folder, with which approval (manual, automatic, none for a simple read), for whom** (console, local, name given by the proxy, device) and the outcome (ok, refused, error, stopped). Never the contents of the files nor the output of the commands. Visible with `lutin journal` or the « ⋯ > Action log » menu. It rotates at 5 MB.

## Changing level

`lutin setup --niveau local|reseau|proxy` (with `--url` and `--proxy-ip` for level 3). Going back to a more closed level is always possible; to open a wider one, run the command on the machine itself.

## Docker

In the container, « this machine only » does not exist (the port is published by Docker): the level is `reseau` (PIN code) or `proxy`. Inside the complete image, Ollama listens on `127.0.0.1` of the container only and its port is never published. See [DOCKER.md](DOCKER.md).

## Reporting a vulnerability

See [../SECURITY.md](../SECURITY.md).
