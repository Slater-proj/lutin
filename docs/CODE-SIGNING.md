**English** · [Français](CODE-SIGNING.fr.md)

# Code signing policy

The Windows installer (`lutin-setup-*.exe`) is built by GitHub Actions from this repository, from the public source only, by the workflow `.github/workflows/release.yml`. Signing is **being applied for** through the SignPath Foundation (free for open source); until it is approved the installer is **not signed** and Windows SmartScreen may warn. The checksum of every release is in `SHA256SUMS.txt`.

When signing is active:

- **Only artifacts built by this repository's workflow** are signed, from a commit on `main` (a verifiable build: SignPath checks the origin of the artifact).
- **Roles**: Slater-proj (owner) is committer, reviewer and approver. Every signing request is **approved manually** before the file is signed. Contributions from others are reviewed by the owner before being merged.
- **Two-factor authentication** is required on the GitHub account and on SignPath.
- **Privacy**: see [PRIVACY.md](PRIVACY.md). Lutin sends no information about you; the contacts it can make are listed there.
- The installer is a per-user installer (no administrator rights), asks before changing the PATH, and can be uninstalled from Windows' installed apps.
- Product name `Lutin`, product version = the release version.

Setting it up (for the maintainer): [PUBLISHING.md](PUBLISHING.md), « Signing the Windows installer ».
