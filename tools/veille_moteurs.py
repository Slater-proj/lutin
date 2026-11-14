"""Veille des moteurs : y a-t-il une nouvelle version d'un moteur du catalogue (llama.cpp, Ollama, vLLM, SGLang, LocalAI, llama-swap…) depuis la dernière fois ?

    python tools/veille_moteurs.py                # compare, met à jour tools/veille_moteurs.json, écrit le rapport
    python tools/veille_moteurs.py --sans-ecrire  # compare seulement

Les moteurs surveillés sont ceux de tools/moteurs.source.json qui ont un champ « depot » (propriétaire/nom sur GitHub). L'état (dernière version vue) est tools/veille_moteurs.json.
Le workflow hebdomadaire (.github/workflows/veille.yml) ouvre une DEMANDE DE FUSION avec ce changement : une personne la relit, teste le moteur si besoin, met à jour le catalogue
(version_testee, notes), le signe avec sa clé, puis fusionne. Rien n'est jamais publié ni signé tout seul. Une erreur réseau n'est pas une nouvelle version : le moteur est simplement ignoré cette fois.

Code de sortie 0 (même s'il y a du neuf : c'est la demande de fusion qui l'annonce). Le rapport est écrit dans veille-rapport.md (corps de la demande de fusion)."""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from lutin import engine_updates  # noqa: E402

SOURCE = RACINE / "tools" / "moteurs.source.json"
ETAT = RACINE / "tools" / "veille_moteurs.json"
RAPPORT = RACINE / "veille-rapport.md"


def http_json(url, delai=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "lutin-veille"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read().decode("utf-8"))


PRE_PUBLICATION = re.compile(r"(rc|alpha|beta|dev|pre)[.\-_]?\d*$", re.I)


def derniere_version(depot, lire=http_json, motif=None):
    """(étiquette, adresse de la publication) de la dernière publication stable du dépôt, ou None si introuvable. On lit la liste des publications (et non « latest », que certains dépôts
    pointent vers autre chose que leurs versions : llama.cpp numérote ses versions bNNNN) ; `motif` : expression régulière que l'étiquette doit respecter. Brouillons sont ignorés ; sans motif, pré-publications et rc aussi (llama.cpp marque toutes ses versions « pré-publication » : son motif suffit)."""
    liste = lire("https://api.github.com/repos/{}/releases?per_page=15".format(depot))
    for r in liste if isinstance(liste, list) else []:
        etiquette = str(r.get("tag_name") or "")
        if not etiquette or r.get("draft") or (motif and not re.match(motif, etiquette)) or (not motif and (r.get("prerelease") or PRE_PUBLICATION.search(etiquette))):
            continue
        return etiquette, str(r.get("html_url") or "https://github.com/{}/releases".format(depot))
    return None


def surveiller(moteurs, etat, lire=http_json):
    """(nouvel état, changements) : `moteurs` = [{id, nom, depot, version_testee?}], `etat` = {id: {depot, vue}}. Un changement : {id, nom, depot, ancienne, nouvelle, adresse, testee}.
    Le premier passage pour un moteur (aucune version vue) enregistre sa version sans l'annoncer. Une erreur réseau garde l'ancien état."""
    neuf, changements = dict(etat), []
    for m in moteurs:
        if not m.get("depot"):
            continue
        try:
            r = derniere_version(m["depot"], lire, m.get("etiquette"))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if r is None:
            continue
        etiquette, adresse = r
        ancienne = (etat.get(m["id"]) or {}).get("vue", "")
        neuf[m["id"]] = {"depot": m["depot"], "vue": etiquette}
        if ancienne and etiquette != ancienne and engine_updates.plus_recente(etiquette, ancienne):
            changements.append({"id": m["id"], "nom": m["nom"], "depot": m["depot"], "ancienne": ancienne, "nouvelle": etiquette, "adresse": adresse, "testee": m.get("version_testee", "")})
    return neuf, changements


def rapport(changements):
    """Le texte de la demande de fusion."""
    if not changements:
        return "Aucune nouvelle version de moteur depuis la dernière veille.\n"
    lignes = ["# Nouvelles versions de moteurs", "",
              "Cette demande de fusion a été ouverte automatiquement. **Rien n'a été testé, signé ni publié.** Pour chaque moteur : lire les notes de publication, essayer si besoin,",
              "puis mettre à jour `tools/moteurs.source.json` (`version_testee`, notes, version du catalogue), relancer `python tools/signer_catalogue_moteurs.py` et fusionner.", ""]
    for c in changements:
        testee = " (version testée par Lutin : {})".format(c["testee"]) if c["testee"] else " (aucune version testée enregistrée)"
        lignes.append("- **{}** : {} → [{}]({}){}".format(c["nom"], c["ancienne"], c["nouvelle"], c["adresse"], testee))
    return "\n".join(lignes) + "\n"


def principal(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sans-ecrire", action="store_true", help="comparer sans toucher à l'état ni au rapport")
    a = p.parse_args(argv)
    moteurs = json.loads(SOURCE.read_text(encoding="utf-8"))["moteurs"]
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.is_file() else {}
    neuf, changements = surveiller(moteurs, etat)
    texte = rapport(changements)
    print(texte)
    if not a.sans_ecrire:
        ETAT.write_text(json.dumps(neuf, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        if changements:
            RAPPORT.write_text(texte, encoding="utf-8", newline="\n")
        elif RAPPORT.exists():
            RAPPORT.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
