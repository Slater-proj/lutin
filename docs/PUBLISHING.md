**English** · [Français](PUBLISHING.fr.md)

# Publishing: versions, candidates, images

Everything is automatic; nobody sets a version number by hand.

## The principle

| What happens | What is produced |
|---|---|
| **Merge (or push) into `main`** | **A release**: computed version, **tag** `vX.Y.Z`, **GitHub Release** (wheel, source archive, `SHA256SUMS.txt`, generated notes), Docker images `:X.Y.Z` and `:latest` (complete) and `:X.Y.Z-slim` and `:slim` (slim). |
| **Push to another branch** | **A candidate (rc), with no tag or Release**: wheel, archive and Windows installer attached to the workflow run (30 days), Docker images `:rc-<branch>` and `:rc-<branch>-slim`. |
| **The button** (Actions > release > Run workflow, on a branch) | **A pre-release of that branch**: tag `vX.Y.ZaN`, GitHub Release marked *pre-release*, Docker image `:next`. See « The button » below. |
| **Pull request** | Tests only (`ci.yml`). |

The tests (Windows and Linux, Python 3.10 to 3.13), the package check, the build of the Docker images and the secret scan run **before** any publication. If a test fails, nothing is published.

**Built once, tested, published as it is.** The version is computed first; `ci.yml` builds the interface, the wheel, the source archive and the Windows installer once, with that version, and tests them. What is published are those very files: nothing is built a second time after the tests. The page of every run says at its top which version it makes and where to take it.

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

## Release channel: pre-releases during the migration to 1.0

The file `tools/release_channel.json`, when the repository has one, decides what `main` publishes ([ADR 0004](adr/0004-release-cadence.md)):

| File | What `main` publishes |
|---|---|
| none (the 0.x line) | a stable release per merge, as described above |
| `{"channel": "alpha", "target": "1.0.0"}` | **pre-releases** `1.0.0a1`, `1.0.0a2`… (`beta`: `b1`…, `rc`: `rc1`…): tag `v1.0.0a1`, GitHub Release marked *pre-release*, Docker images `:1.0.0a1` and `:next` — **never** `:latest` |
| `{"channel": "stable", "target": "1.0.0"}` | the stable `1.0.0`, then the usual computation |

A pre-release is never « the latest release » for GitHub: the install scripts, `lutin update` and the update notice in the page all ask for the latest release, so none of them offers it. To try one, name it: `docker pull ghcr.io/slater-proj/lutin:next`, or the wheel of that Release.

On a branch that carries a target, the candidate is called `1.0.0.devN+branch` (always lower than `1.0.0a1`). An unreadable or inconsistent file stops the computation: nothing is published rather than a stable version by accident.

The `modernization` branch carries the `alpha` file: should it reach `main` before 1.0 is ready, what comes out is a pre-release.

## Using a candidate

```bash
# Docker image of the branch "my-branch"
docker pull ghcr.io/slater-proj/lutin:rc-my-branch

# or the wheel: Actions tab > the branch's run > Artifacts > lutin-X.Y.ZrcN+…
pip install lutin-0.5.0rc17+my.branch-py3-none-any.whl
```

The Windows installer of the candidate is in the same place: **Artifacts > `installateur-…`** (GitHub asks to be signed in to download an artifact, and gives it as a zip).

## The button: a test version of a branch that anyone can download

A candidate is built on every push, but it has no tag and no Release, and its files need a GitHub account. To hand a real test version of a feature branch to someone (alpha/beta/rc as chosen in `tools/release_channel.json`):

1. open **[Actions > release](https://github.com/Slater-proj/lutin/actions/workflows/release.yml)**;
2. click **Run workflow**, pick the branch;
3. click the green **Run workflow**. There is nothing else to fill in.

The version is computed (`1.0.0a1`, then `a2`…), everything is built with it and tested, then the tag `vX.Y.ZaN`, a GitHub Release marked *pre-release* (wheel, archive, Windows installer, checksums) and the Docker images `:X.Y.ZaN` and `:next` are published; never `:latest`, and the installers and the update notice ignore it. The link to the Release is at the top of the page of the run. Count twenty to thirty minutes, most of it the tests.

Refused outside `main` if the channel says « stable ». Only this button does it: a push never publishes from a branch, and a push on the branch does not cancel a publication under way.

From a terminal, with [GitHub CLI](https://cli.github.com/): `gh workflow run release.yml --ref my-branch`.

## Setting up GitHub (once)

1. **Settings > Actions > General**: « Workflow permissions » = *Read and write permissions* (needed to create tags and publish the image).
2. **Settings > Branches**: protect `main` (require a pull request and the success of the `tests / ci (résultat)` check, which gathers all the others). Without protection, a direct push to `main` publishes too.
   Require that exact name: it is the run of `release.yml` on every push, the one that tests. The bare `ci (résultat)` of a pull request from this repository is **skipped** on purpose (the push already ran the tests), and GitHub counts a skipped required check as a success. A pull request from a fork gets only the bare name: push its branch to this repository to get the real check.
3. **Packages**: after the first image, make the `lutin` package public (Package settings > Change visibility) so that `docker pull` works without signing in.
4. Optional: **Security > Code security**: enable private vulnerability reporting and Dependabot.

## The Windows installer is not signed

Signing was considered (SignPath Foundation, free for open source) and dropped for now: too much set-up for the current audience. Windows SmartScreen may warn when the `.exe` is downloaded (« More info > Run anyway »); the checksum is in `SHA256SUMS.txt`. The installer scripts (`install.ps1`) are an alternative that does not trigger the warning.

## Fixing things

| Problem | What to do |
|---|---|
| A release is bad | Delete it (Release + tag), fix, merge: a new version comes out. Never reuse a number. |
| The computation gives an unexpected version | `python tools/prochaine_version.py --mode release` locally (it creates nothing); adjust the commit title. |
| The Docker image was not published | Actions > the run > the « image Docker » job; check the *packages: write* permission and the package visibility. |
