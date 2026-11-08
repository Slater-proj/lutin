**English** · [Français](ROLLBACK.fr.md)

# Updating safely, and going back

## What Lutin does for you

- **Before any update** (`lutin update`, or the update button in the page) Lutin saves your data (settings, conversations, memory, action log) into a `.zip` and keeps the **last three**. If that backup fails (disk full…), you are told and the update goes on.
- **If the update fails** (no network, pip error), your current version stays in place: nothing is half-installed by Lutin itself.
- **A damaged or hand-edited data file** (cut by a power failure, a JSON that is no longer an object…) does not stop Lutin: it falls back to defaults for that file instead of crashing. Restore a backup to get your settings back.

## Where the automatic backups are

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\Lutin\cache\avant-mise-a-jour\` |
| Linux | `~/.cache/lutin/avant-mise-a-jour/` |
| macOS | `~/Library/Caches/Lutin/avant-mise-a-jour/` |

The file name tells which version it was made from: `lutin-0.22.0-20261107-101500.zip`.

## Going back to an earlier version

1. Stop Lutin (close the page's server, or `Ctrl+C` in its window).
2. Install the earlier published version:

   ```
   lutin update --rollback-to 0.22.0
   ```

   This reinstalls that release from GitHub (only a plain `X.Y.Z` number is accepted), after saving your data again. It works for an installation made with the installer script (source on GitHub); for a manual `pip install` of a file, install the wheel you want yourself with `python -m pip install <file>.whl`.
3. If the earlier version no longer understands your data (rare: data files only gain fields), put your data back:

   ```
   lutin restore <backup>.zip
   ```

   Lutin first saves the current state in an "avant-restauration" archive.
4. Start Lutin again.

> A normal `lutin update` **never** goes back: it only installs a strictly newer release.

## Docker

Images are published with a version tag. To go back, name the tag in your compose file and recreate the container:

```
image: ghcr.io/slater-proj/lutin:0.22.0
docker compose up -d
```

Your data lives in the `lutin-data` volume (and models in `lutin-models`): they survive the image change, as the CI checks by destroying and recreating the container. Do **not** run `docker compose down -v`: `-v` deletes the volumes.

## What this does not cover

- Models and engines (Ollama, llama.cpp) are updated and rolled back with their own tools; Lutin does not touch them when it rolls itself back.
- The machines' pairing tokens (Machines tab) are **not** in backups: they are secrets. After restoring on a new computer, pair the machines again.
- The rollback command has been tested with a simulated installer, not with a real release on a real installation. Try it once on your side before you need it.
