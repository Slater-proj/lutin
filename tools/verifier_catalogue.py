"""Vérifie que chaque modèle du catalogue existe dans le registre d'Ollama.

    python tools/verifier_catalogue.py

Code de sortie 1 si au moins un modèle a disparu (la CI hebdomadaire ouvre alors une alerte). Les erreurs réseau ne comptent pas comme des disparitions :
un modèle n'est déclaré absent que si le registre répond explicitement « introuvable ».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lutin import catalogue, miseajour  # noqa: E402


def disparus(cat, http=miseajour.http_get):
    """[(identifiant, raison)] pour les modèles que le registre ne connaît plus."""
    manquants, incertains = [], []
    for m in cat["modeles"]:
        espace, nom, tag = miseajour.separer(m["id"])
        try:
            statut, _, _ = http("{}/{}/{}/manifests/{}".format(miseajour.REGISTRE, espace, nom, tag), {"Accept": miseajour.ACCEPT_MANIFESTE})
        except OSError as e:
            incertains.append((m["id"], "réseau : {}".format(e)))
            continue
        if statut in (404, 400):
            manquants.append((m["id"], "introuvable dans le registre"))
        elif statut != 200:
            incertains.append((m["id"], "réponse {}".format(statut)))
    return manquants, incertains


def principal():
    manquants, incertains = disparus(catalogue.charger())
    for ident, raison in incertains:
        print("? {} : {} (ignoré)".format(ident, raison))
    for ident, raison in manquants:
        print("✘ {} : {}".format(ident, raison))
    if not manquants:
        print("✔ tous les modèles du catalogue existent ({} vérifiés, {} incertains)".format(len(catalogue.charger()["modeles"]), len(incertains)))
    return 1 if manquants else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(principal())
