**English** · [Français](PUBLISHING.fr.md)

# Publishing: versions, candidates, images

Everything is automatic; nobody sets a version number by hand.

## The principle

| What happens | What is produced |
|---|---|
| **Merge (or push) into `main`** | **A release**: computed version, **tag** `vX.Y.Z`, **GitHub Release** (wheel, source archive, `SHA256SUMS.txt`, generated notes), Docker images `:X.Y.Z` and `:latest` (complete) and `:X.Y.Z-slim` and `:slim` (slim). |
| **Push to another branch** | **A candidate (rc), with no tag or Release**: wheel and archive attached to the workflow run (30 days), Docker images `:rc-<branch>` and `:rc-<branch>-slim`. |
| **Pull request** | Tests only (`ci.yml`). |

The tests (Windows and Linux, Python 3.10 to 3.13), the package check, the build of the Docker images and the secret scan run **before** any publication. If a test fails, nothing is published.

## How the number is chosen

`tools/prochaine_version.py` reads the history since the last `vX.Y.Z` tag and looks at the commit titles (form `type: description`):

| In the commits | Effect | Example |
|---|---|---|
| `feat!:` or `fix!:`, or « BREAKING CHANGE » in the message | **major** (while the major is 0: minor) | 1.4.2 → 2.0.0 |
| `feat:` | **minor** | 1.4.2 → 1.5.0 |
| everything else (`fix:`, `docs:`, `chore:`, free title…) | **patch** | 1.4.2 → 1.4.3 |

The first release is **0.1.0**. Every merge into `main` produces a release, even a simple documentation fix. If the commit is already tagged (a workflow re-run), there is nothing to publish.

**Candidates**: the version is `X.Y.ZrcN+branch` (for example `0.5.0rc17+my.branch`) where `N` is the workflow run number; it is a real PEP 440 version, `pip` accepts it, and it is **always lower** than the stable version that will follow.

Tip: so that the version follows what you did, merge with a **squash** and a conventional title (`feat: multiple workspace folders`).

## Using a candidate

```bash
# Docker image of the branch "my-branch"
docker pull ghcr.io/slater-proj/lutin:rc-my-branch

# or the wheel: Actions tab > the branch's run > Artifacts > lutin-X.Y.ZrcN+…
pip install lutin-0.5.0rc17+my.branch-py3-none-any.whl
```

## Setting up GitHub (once)

1. **Settings > Actions > General**: « Workflow permissions » = *Read and write permissions* (needed to create tags and publish the image).
2. **Settings > Branches**: protect `main` (require a pull request and the success of the `ci / …` checks). Without protection, a direct push to `main` publishes too.
3. **Packages**: after the first image, make the `lutin` package public (Package settings > Change visibility) so that `docker pull` works without signing in.
4. Optional: **Security > Code security**: enable private vulnerability reporting and Dependabot.

## Fixing things

| Problem | What to do |
|---|---|
| A release is bad | Delete it (Release + tag), fix, merge: a new version comes out. Never reuse a number. |
| The computation gives an unexpected version | `python tools/prochaine_version.py --mode release` locally (it creates nothing); adjust the commit title. |
| The Docker image was not published | Actions > the run > the « image Docker » job; check the *packages: write* permission and the package visibility. |
