**English** · [Français](SECURITY_AUDIT.fr.md)

# Security review before 1.0 (milestone 0.26.0)

A self-review of the surfaces added since 0.20 and of the long-standing ones. **It is not an independent audit**: it was done by the maintainers and their assistant. [SECURITY.md](SECURITY.md) describes the model; this page says what was checked and what is still open.

## What was checked

| Surface | Check | Result |
|---|---|---|
| Machine routes (`/api/noeud/*`) | Token required (SHA-256 hashed at rest, constant-time comparison), node switched off recognises nobody, token opens nothing outside these routes, request body reduced to a whitelist of keys, two simultaneous requests at most | OK, covered by `test_machines.py` |
| Pairing | 8-digit code, single use, 5 minutes, at most 3 pending, shared rate limiter, same message for a wrong or expired code | OK |
| Remote shutdown | Off by default on the machine to switch off, needs a valid node token, 30 s delay, cancellable, logged on both sides | OK |
| System commands | Lutin's own commands (engines, updates, system tools) are lists of arguments: no `os.system`, no `eval/exec/pickle` in `src/`; the version given to `--rollback-to` must match `X.Y.Z`. **Correction (2026-11-11):** this line used to say « no `shell=True` ». That was wrong: the agent's `executer` tool runs the command the model wrote in a shell (`outils.lancer_processus`), by design and after approval — and until this date the « simple reads » ran in it without approval and could be bypassed. They no longer go through a shell ([ADR 0006](adr/0006-approval-free-commands.md)) | OK for Lutin's own commands; fixed for approval-free reads |
| Web access of the agent | The address checked is the address connected (one resolution, by the connection); every redirection target is checked before it is contacted; carrier-grade NAT refused ([ADR 0008](adr/0008-outbound-web-guard.md)). Before 2026-11-11 a redirection reached its target before the check | **Fixed** (`test_net_guard.py`); not pinned behind a system proxy |
| "Unload / close" actions of the Health page | Fixed list of actions; ComfyUI is closed only if Lutin started it | OK |
| Files served (`/fichier/`, `/lib/`, `/image/`, `/piece/`) | `..` and encoded variants refused | OK, `test_parcours_vierge.py` |
| Request bodies | Size limits (2 MB JSON, 8 MB images, 20 MB documents); a non-numeric `Content-Length` counts as "too big"; JSON must be an object | OK |
| Cross-site and rebinding | `Host` / `Origin` checked, page token required for reads at level 1 | OK (`test_serveur_securite.py`) |
| Data files | A damaged or wrong-type JSON file falls back to defaults (before 0.26.0 a `reglages.json` that was not an object made every request crash) | **Fixed in 0.26.0** |
| `lutin colibri` (third-party program) | Runs only on your explicit command; archive downloaded from the project's own GitHub releases only, **SHA-256 mandatory** (no sums published = refused), unpacking cannot leave its folder (names with `..`, links and special files refused), server bound to `127.0.0.1` | OK in tests; it **downloads a third party's Python script and runs it when you start it**: that is its nature, read its licence and code if you care |
| Signed engine catalogue | Ed25519, two keys, tampering and unknown fields refused | OK |

## Known limits (not fixed, said plainly)

1. **Updates are verified (fixed after the first version of this page).** `lutin update` downloads the wheel, computes its SHA-256 and compares it with the `SHA256SUMS.txt` published next to it; a wrong sum, a file missing from the list or an oversized wheel refuses the update, and pip then installs the verified file itself. Limit: the sums file sits on the same host as the wheel, so this catches corruption and a swapped file, **not a compromised release**. A release without `SHA256SUMS.txt` (old ones) is accepted with a visible warning. Checked for real against the v0.24.0 and v0.21.0 releases.
2. **Plain HTTP on the local network** (levels 2 and 3 without a proxy certificate, and machine-to-machine traffic): anyone who can read the network can read what passes. Use level 3 behind a TLS reverse proxy outside a trusted network.
3. **Node token and pairing**: a machine you paired can run the engine of the machine that lent it, within the two-requests limit, until you revoke it. It cannot read conversations, files or settings.
4. **No independent audit**, no fuzzing campaign, no penetration test.
5. **Docker**: not tested against a hostile local user; the container does not mount the Docker socket.

## How to report

See [SECURITY.md](SECURITY.md#reporting-a-vulnerability).
