"""Calcule la version d'une publication à partir de l'historique git. Utilisé par .github/workflows/release.yml.

    python tools/prochaine_version.py --mode release   # fusion dans main : nouvelle version stable + étiquette vX.Y.Z
    python tools/prochaine_version.py --mode rc --branche ma-branche --numero 42      # branche : candidate X.Y.ZrcN+ma.branche, SANS étiquette

Règles (commits « conventionnels », titre de la forme `type: description`) :
  `feat!:` / `fix!:` ou « BREAKING CHANGE » dans le message  -> version majeure (tant que la majeure est 0 : mineure)
  `feat:`                                                    -> version mineure
  tout le reste (`fix:`, `docs:`, `chore:`, titre libre…)    -> correctif
Chaque fusion dans main produit une publication (au moins un correctif). La première publication est 0.1.0. Si HEAD porte déjà une étiquette, il n'y a rien à publier.
Sortie : lignes `clé=valeur` (version, base, niveau, publier, etiquette, prerelease), prêtes pour $GITHUB_OUTPUT.

Canal de publication (docs/adr/0004-release-cadence.md) : le fichier `tools/release_channel.json` du dépôt versionné, s'il existe, dit ce que `main` publie.
  {"channel": "alpha", "target": "1.0.0"}   -> des PRÉ-versions 1.0.0a1, 1.0.0a2… (« beta » : b1… ; « rc » : rc1…), étiquette v1.0.0a1, `prerelease=true` :
                                               jamais « dernière version » sur GitHub, jamais l'image Docker :latest, jamais proposée par l'annonce de mise à jour
  {"channel": "stable", "target": "1.0.0"}  -> la version stable visée (1.0.0), puis le calcul habituel
  pas de fichier                            -> le calcul habituel (c'est le cas de la ligne 0.x)
Sur une branche, avec une cible, la candidate s'appelle `1.0.0.devN+ma.branche` (toujours plus petite que 1.0.0a1).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RE_ETIQUETTE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RE_PRE = re.compile(r"^v(\d+\.\d+\.\d+)(a|b|rc)(\d+)$")
RE_CIBLE = re.compile(r"^\d+\.\d+\.\d+$")
PHASES = {"alpha": "a", "beta": "b", "rc": "rc"}
FICHIER_CANAL = Path("tools") / "release_channel.json"
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


def lire_canal(chemin=FICHIER_CANAL):
    """Le canal de publication du dépôt : {"channel", "target"}. Fichier absent : canal stable sans cible. Un fichier illisible ou incohérent est une erreur
    (ValueError), jamais un retour silencieux au canal stable : il publierait une version « dernière » par accident."""
    chemin = Path(chemin)
    if not chemin.is_file():
        return {"channel": "stable", "target": ""}
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("{} illisible : {}".format(chemin, e))
    canal, cible = (d.get("channel"), d.get("target") or "") if isinstance(d, dict) else (None, "")
    if canal not in ("stable",) + tuple(PHASES) or not isinstance(cible, str) or (cible and not RE_CIBLE.match(cible)) or (canal in PHASES and not cible):
        raise ValueError("{} : il faut \"channel\" (stable, alpha, beta ou rc) et, sauf pour stable, \"target\" de la forme X.Y.Z".format(chemin))
    return {"channel": canal, "target": cible}


def numero_de_pre_version(etiquettes, cible, phase):
    """Le numéro de la prochaine pré-version de cette cible et de cette phase : 1, ou le plus haut déjà publié + 1."""
    deja = [int(m.group(3)) for e in etiquettes if (m := RE_PRE.match(e.strip())) and m.group(1) == cible and m.group(2) == phase]
    return max(deja, default=0) + 1


def calcul(etiquettes, messages, mode, branche="", numero=0, etiquettes_de_head=(), canal=None):
    canal = canal or {"channel": "stable", "target": ""}
    base = derniere_etiquette(etiquettes)
    niveau = niveau_de_changement(messages)
    prochaine = suivante(base, niveau)
    cible = tuple(int(x) for x in canal["target"].split(".")) if canal["target"] else None
    if cible and (base is None or cible > base):
        prochaine = cible                                 # la version visée, tant qu'elle n'est pas publiée
    elif cible and canal["channel"] in PHASES:
        raise ValueError("la cible {} est déjà publiée (dernière version stable : {}) : change tools/release_channel.json".format(canal["target"], texte(base)))
    sortie = {"base": texte(base) if base else "", "niveau": niveau if base else "premiere", "prerelease": "false"}
    if mode == "release":
        deja = any(RE_ETIQUETTE.match(e.strip()) or RE_PRE.match(e.strip()) for e in etiquettes_de_head)
        version = texte(prochaine)
        if canal["channel"] in PHASES:
            phase = PHASES[canal["channel"]]
            version = "{}{}{}".format(version, phase, numero_de_pre_version(etiquettes, version, phase))
            sortie["prerelease"] = "true"
        sortie.update(version=version, etiquette="v" + version, publier="false" if deja else "true")
    elif cible and prochaine == cible:
        sortie.update(version="{}.dev{}+{}".format(texte(prochaine), int(numero), identifiant_local(branche)), etiquette="", publier="true")
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
    p.add_argument("--canal", default=str(FICHIER_CANAL), help="fichier du canal de publication (par défaut tools/release_channel.json du dépôt courant)")
    a = p.parse_args(argv)
    try:
        canal = lire_canal(a.canal)
    except ValueError as e:
        print("canal de publication : {}".format(e), file=sys.stderr)
        return 2
    etiquettes = git("tag", "--list", "v*").split()
    base = derniere_etiquette(etiquettes)
    plage = "v{}..HEAD".format(texte(base)) if base else "HEAD"
    messages = [m for m in git("log", plage, "--format=%B%x00").split("\x00") if m.strip()]
    try:
        sortie = calcul(etiquettes, messages, a.mode, a.branche, a.numero, git("tag", "--points-at", "HEAD").split(), canal)
    except ValueError as e:
        print("canal de publication : {}".format(e), file=sys.stderr)
        return 2
    for cle, valeur in sortie.items():
        print("{}={}".format(cle, valeur))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
