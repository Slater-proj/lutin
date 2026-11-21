# Baseline (step 0)

What was measured before any change, how to measure it again, and what the first two steps changed. Figures are those of the run described here, not promises.

## Starting point

- Commit `e3de979` (branch `evolutions`, version line 0.50.3), 2026-11-11.
- 382 tracked files; 108 Python modules in `src/lutin` (33 086 lines); 119 test files, 1 757 test methods; one page, `src/lutin/web/index.html` (543 kB).
- No run-time dependency. Ruff rules `E9`, `F`. No type annotation (0 of 2 022 functions). No coverage measurement.

## How the suite was run

```
python -B tests/lancer_tests.py            # every file, each in its own process
python -B tests/lancer_tests.py net_guard  # only the files whose name contains the text
python -m ruff check src tests tools
```

Machine of the run: Windows 11, Python 3.12.15, Chrome installed (the browser tests need it), **a real Ollama installed and running**, the repository on a network share.
`LUTIN_HOME` pointed at an empty temporary folder, as a precaution, so that no test could touch the real data of the Lutin installed on that machine.

## Result before any change

**116 of 119 files passed.** Three files failed (5 tests), all for the same reason — they read the machine instead of a fake:

| Test | What it found |
|---|---|
| `test_adequation.py` — 3 tests on the models folder | the folder of the real Ollama (asked through its API on port 11434) |
| `test_correctifs_moteurs.py` — first launch with Colibri | « Ollama, already installed » (the real executable, found on the PATH) |
| `test_navigateur.py` — switching engine | the same, in a real browser |

These were defects of the tests, not of the code under test.

## Not run (and why)

| What | Why |
|---|---|
| Python 3.10 and 3.13, Linux | one interpreter and one system available |
| Packaging job (wheel, source archive, install in an empty environment) | not attempted |
| Docker images, Linux installer, Windows installer | no Docker on the machine; installers not attempted |
| Secret scan (gitleaks) | CI only |
| Any engine on real hardware | out of scope for a baseline; see « Known but not verified » in [DECISIONS.md](../DECISIONS.md) |

The CI covers the first four on every pull request. **Nothing in this work has gone through the CI yet**: the branch has not been pushed.

## What steps 0 and 1 changed

- `tests/context.py` isolates every test from a real Ollama (address, executable, models folder); `chemin_ollama()` does not look at the standard install folders during tests.
- New tests: `test_safe_commands.py`, `test_net_guard.py`, `test_api_contract.py` (with `tools/api_inventory.py` and `tests/fixtures/api_contract.json`: 184 exact routes, 17 prefixes, 15 stream events).
- The two security fixes of [ADR 0006](../adr/0006-approval-free-commands.md) and [ADR 0008](../adr/0008-outbound-web-guard.md).

## Result after steps 0 and 1

Same machine, same command, on the tree of the commit that adds this file:

- **122 of 122 files passed** (the 119 files of the start plus the three new ones), exit code 0.
- `ruff check src tests tools`: clean (Ruff 0.17.4, the project's rules).
- Two files report a skipped test: `test_outils_externes.py` (as before) and `test_safe_commands.py`, whose test that starts `ls` and `cat` for real only runs on POSIX.
  **That test has therefore never been executed**: its first run will be on the Linux jobs of the CI.

Still true after these steps: everything listed under « Not run », and the limits written in the two ADRs (system proxy; add-ons not pinned; `git` obeying a hostile repository configuration).
