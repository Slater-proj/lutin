"""Signe le catalogue des moteurs, ou vérifie un catalogue déjà signé.

    python tools/signer_catalogue_moteurs.py                 # signe tools/moteurs.source.json -> src/lutin/data/moteurs.json
    python tools/signer_catalogue_moteurs.py --verifier      # vérifie src/lutin/data/moteurs.json (code de sortie 1 s'il est refusé)
    python tools/signer_catalogue_moteurs.py --cle 2026b     # signe avec l'autre clé (rotation)

La clé privée (une graine de 32 octets en hexadécimal) reste HORS du dépôt : par défaut ~/.lutin-signature/cle-a.seed pour la clé « 2026a », cle-b.seed pour « 2026b »
(`--graine` indique un autre fichier). Voir docs/ENGINE_CATALOG.md."""
import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from lutin import engine_catalog as cm  # noqa: E402

SOURCE = RACINE / "tools" / "moteurs.source.json"


def signer_fichier(source, destination, cle, graine):
    catalogue = cm.valider(json.loads(Path(source).read_text(encoding="utf-8")))
    enveloppe = cm.signer(catalogue, bytes.fromhex(Path(graine).read_text(encoding="utf-8").strip()), cle)
    cm.verifier(enveloppe)          # on ne publie jamais un fichier que Lutin refuserait
    Path(destination).write_text(json.dumps(enveloppe, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return enveloppe


def principal(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")          # console Windows en cp1252
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verifier", action="store_true", help="vérifier le catalogue livré au lieu de le signer")
    p.add_argument("--cle", default="2026a", help="identifiant de la clé (2026a ou 2026b)")
    p.add_argument("--graine", help="fichier de la clé privée (par défaut ~/.lutin-signature/cle-a.seed ou cle-b.seed)")
    p.add_argument("--source", default=str(SOURCE))
    p.add_argument("--destination", default=str(cm.FICHIER_LIVRE))
    a = p.parse_args(argv)
    if a.verifier:
        try:
            c = cm.lire_fichier(a.destination)
        except (OSError, ValueError) as e:
            print("✘ catalogue refusé : {}".format(e))
            return 1
        print("✔ catalogue valide et bien signé (version {}, {} moteurs)".format(c["version"], len(c["moteurs"])))
        return 0
    graine = a.graine or str(Path.home() / ".lutin-signature" / ("cle-%s.seed" % a.cle[-1]))
    if not Path(graine).is_file():
        print("✘ clé privée introuvable : {}".format(graine))
        return 1
    e = signer_fichier(a.source, a.destination, a.cle, graine)
    print("✔ signé avec la clé {} : {} ({} moteurs)".format(a.cle, a.destination, len(e["catalogue"]["moteurs"])))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
