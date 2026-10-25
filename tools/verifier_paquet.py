"""Vérifie le contenu des fichiers construits (roue et archive source) : ce qui doit y être y est, ce qui ne doit pas y être n'y est pas.

    python tools/verifier_paquet.py dist/
"""
import sys
import tarfile
import zipfile
from pathlib import Path

DANS_LA_ROUE = ("lutin/__init__.py", "lutin/cli.py", "lutin/moteur.py", "lutin/web/index.html", "lutin/web/logo.svg", "lutin/web/lib/mermaid.min.js", "lutin/web/icones/icone-192.png",
                "lutin/web/icones/icone-512.png", "lutin/data/modeles.json", "lutin/data/CONTEXTE.md", "lutin/data/MEMOIRE.md")
JAMAIS = ("tests/", "docs/", "tools/", "assets/", "installateur/", ".github/", "docker/", "Dockerfile", ".git/", "__pycache__", ".pyc", "console.json", "config.json", ".log")


def problemes(dossier):
    dossier = Path(dossier)
    p = []
    roues, sources = sorted(dossier.glob("*.whl")), sorted(dossier.glob("*.tar.gz"))
    if len(roues) != 1:
        return ["il faut exactement une roue (.whl) dans {} : {} trouvée(s)".format(dossier, len(roues))]
    with zipfile.ZipFile(roues[0]) as z:
        noms = z.namelist()
        for attendu in DANS_LA_ROUE:
            if attendu not in noms:
                p.append("roue : « {} » manque".format(attendu))
        for n in noms:
            if any(j in n for j in JAMAIS):
                p.append("roue : « {} » ne devrait pas y être".format(n))
        meta = next((n for n in noms if n.endswith(".dist-info/METADATA")), None)
        if meta and "Requires-Dist" in z.read(meta).decode("utf-8", "replace"):
            p.append("roue : une dépendance est déclarée (Lutin n'en a aucune)")
        if not any(n.endswith("entry_points.txt") and b"lutin = lutin.cli:principal" in z.read(n) for n in noms):
            p.append("roue : la commande « lutin » n'est pas déclarée")
    for s in sources:
        with tarfile.open(s) as t:
            for nom in t.getnames():
                reste = nom.split("/", 1)[-1]
                if any(reste.startswith(j) or ("/" + j) in "/" + reste for j in ("tests/", "docs/", "tools/", "assets/", "installateur/", ".github/", "docker/")):
                    p.append("source : « {} » ne devrait pas y être".format(nom))
    return p


def principal(argv):
    if not argv:
        print(__doc__)
        return 2
    pb = problemes(argv[0])
    for ligne in pb:
        print("✘ " + ligne)
    if not pb:
        print("✔ roue et archive source conformes")
    return 1 if pb else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(principal(sys.argv[1:]))
