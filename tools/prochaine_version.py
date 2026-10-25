"""Calcule la version d'une publication à partir de l'historique git. Utilisé par .github/workflows/release.yml.

    python tools/prochaine_version.py --mode release   # fusion dans main : nouvelle version stable + étiquette vX.Y.Z
    python tools/prochaine_version.py --mode rc --branche ma-branche --numero 42      # branche : candidate X.Y.ZrcN+ma.branche, SANS étiquette

Règles (commits « conventionnels », titre de la forme `type: description`) :
  `feat!:` / `fix!:` ou « BREAKING CHANGE » dans le message  -> version majeure (tant que la majeure est 0 : mineure)
  `feat:`                                                    -> version mineure
  tout le reste (`fix:`, `docs:`, `chore:`, titre libre…)    -> correctif
Chaque fusion dans main produit une publication (au moins un correctif). La première publication est 0.1.0. Si HEAD porte déjà une étiquette, il n'y a rien à publier.
Sortie : lignes `clé=valeur` (version, base, niveau, publier, etiquette), prêtes pour $GITHUB_OUTPUT.
"""
import argparse
import re
import subprocess
import sys

RE_ETIQUETTE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RE_TITRE = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<rupture>!)?:\s")


def derniere_etiquette(etiquettes):
    """La plus haute étiquette stable vX.Y.Z (tuple), ou None."""
    versions = [tuple(int(x) for x in m.groups()) for e in etiquettes if (m := RE_ETIQUETTE.match(e.strip()))]
    return max(versions) if versions else None


def niveau_de_changement(messages):
    """'majeur' | 'mineur' | 'correctif' d'après les messages de commit (titre et corps)."""
    niveau = "correctif"
    for message in messages:
        titre = message.strip().splitlines()[0] if message.strip() else ""
        m = RE_TITRE.match(titre)
        if "BREAKING CHANGE" in message or (m and m.group("rupture")):
            return "majeur"
        if m and m.group("type") == "feat":
            niveau = "mineur"
    return niveau


def suivante(base, niveau):
    """Version suivante (tuple) ; None -> première publication 0.1.0. Tant que la majeure est 0, une rupture ne fait qu'une mineure."""
    if base is None:
        return (0, 1, 0)
    majeure, mineure, correctif = base
    if niveau == "majeur" and majeure > 0:
        return (majeure + 1, 0, 0)
    if niveau in ("majeur", "mineur"):
        return (majeure, mineure + 1, 0)
    return (majeure, mineure, correctif + 1)


def texte(v):
    return "{}.{}.{}".format(*v)


def identifiant_local(branche):
    """Partie locale PEP 440 (lettres, chiffres, points) à partir d'un nom de branche."""
    return re.sub(r"[^a-z0-9]+", ".", branche.lower()).strip(".") or "branche"


def calcul(etiquettes, messages, mode, branche="", numero=0, etiquettes_de_head=()):
    base = derniere_etiquette(etiquettes)
    niveau = niveau_de_changement(messages)
    prochaine = suivante(base, niveau)
    sortie = {"base": texte(base) if base else "", "niveau": niveau if base else "premiere"}
    if mode == "release":
        deja = any(RE_ETIQUETTE.match(e.strip()) for e in etiquettes_de_head)
        sortie.update(version=texte(prochaine), etiquette="v" + texte(prochaine), publier="false" if deja else "true")
    else:
        sortie.update(version="{}rc{}+{}".format(texte(prochaine), int(numero), identifiant_local(branche)), etiquette="", publier="true")
    return sortie


def git(*args):
    return subprocess.run(["git", "-c", "safe.directory=*"] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def principal(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("release", "rc"), required=True)
    p.add_argument("--branche", default="")
    p.add_argument("--numero", type=int, default=0, help="numéro de la candidate (numéro d'exécution de la CI)")
    a = p.parse_args(argv)
    etiquettes = git("tag", "--list", "v*").split()
    base = derniere_etiquette(etiquettes)
    plage = "v{}..HEAD".format(texte(base)) if base else "HEAD"
    messages = [m for m in git("log", plage, "--format=%B%x00").split("\x00") if m.strip()]
    sortie = calcul(etiquettes, messages, a.mode, a.branche, a.numero, git("tag", "--points-at", "HEAD").split())
    for cle, valeur in sortie.items():
        print("{}={}".format(cle, valeur))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
