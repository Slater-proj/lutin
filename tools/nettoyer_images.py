"""Supprime du registre ghcr.io les anciennes images de candidates (« rc ») : chaque branche en publie une, elles s'accumulent.

    python tools/nettoyer_images.py [--garder 5] [--jours 14] [--oui]        # sans --oui : montre ce qui serait supprimé, ne supprime rien

Règles : seules les versions dont TOUTES les étiquettes sont des candidates (`rc-<branche>`, `0.2.0rc12-branche`, avec ou sans `-slim`) sont concernées ; les `latest`, `X.Y.Z` et `slim` ne sont jamais touchées.
On garde les `--garder` plus récentes et tout ce qui a moins de `--jours` jours. Les versions sans étiquette sont laissées (ce sont des morceaux d'images multi-plateformes ou des attestations).
Utilise GITHUB_TOKEN (droit packages: write) ; propriétaire et paquet viennent de GITHUB_REPOSITORY.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

RE_RC = re.compile(r"^(rc-.+|\d+\.\d+\.\d+rc\d+.*)$")


def est_candidate(etiquettes):
    return bool(etiquettes) and all(RE_RC.match(e) for e in etiquettes)


def date(texte):
    return datetime.fromisoformat(texte.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def selectionner(versions, garder=5, jours=14, maintenant=None):
    """Les versions à supprimer : candidates uniquement, hors les `garder` plus récentes, et plus vieilles que `jours` jours."""
    maintenant = time.time() if maintenant is None else maintenant
    candidates = sorted((v for v in versions if est_candidate(v.get("metadata", {}).get("container", {}).get("tags", []))), key=lambda v: date(v["updated_at"]), reverse=True)
    return [v for v in candidates[garder:] if maintenant - date(v["updated_at"]) > jours * 86400]


def appel(url, jeton, methode="GET"):
    req = urllib.request.Request(url, method=methode, headers={"Authorization": "Bearer " + jeton, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "lutin-nettoyage"})
    with urllib.request.urlopen(req, timeout=30) as r:
        corps = r.read()
        suite = re.search(r'<([^>]+)>; rel="next"', r.headers.get("Link", ""))
        return (json.loads(corps) if corps else None), (suite.group(1) if suite else None)


def lister(base, jeton):
    versions, url = [], base + "/versions?per_page=100"
    while url:
        page, url = appel(url, jeton)
        versions += page
    return versions


def principal(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--garder", type=int, default=5)
    p.add_argument("--jours", type=int, default=14)
    p.add_argument("--oui", action="store_true", help="supprimer pour de bon")
    a = p.parse_args(argv)
    jeton, depot = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not jeton or "/" not in depot:
        print("GITHUB_TOKEN et GITHUB_REPOSITORY sont nécessaires.", file=sys.stderr)
        return 2
    proprietaire, paquet = depot.lower().split("/")
    versions = None
    for genre in ("users", "orgs"):
        base = "https://api.github.com/{}/{}/packages/container/{}".format(genre, proprietaire, paquet)
        try:
            versions = lister(base, jeton)
            break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    if versions is None:
        print("Paquet introuvable : {}/{}".format(proprietaire, paquet), file=sys.stderr)
        return 1
    aSupprimer = selectionner(versions, a.garder, a.jours)
    print("{} versions au total, {} candidates à supprimer (on garde les {} plus récentes et ce qui a moins de {} jours).".format(len(versions), len(aSupprimer), a.garder, a.jours))
    for v in aSupprimer:
        etiquettes = ", ".join(v["metadata"]["container"]["tags"])
        if a.oui:
            appel("{}/versions/{}".format(base, v["id"]), jeton, "DELETE")
            print("supprimée :", etiquettes)
        else:
            print("serait supprimée :", etiquettes)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
