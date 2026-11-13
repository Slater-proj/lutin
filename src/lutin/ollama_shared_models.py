"""Les modèles déjà téléchargés par Ollama, utilisables tels quels par un autre moteur (llama.cpp).

Ollama range un modèle en deux endroits : un petit fichier « manifeste » (`manifests/registry.ollama.ai/library/qwen3/8b`) qui liste les morceaux, et les morceaux eux-mêmes dans `blobs/sha256-…`.
Le morceau de type « modèle » EST un fichier GGUF (le format de llama.cpp), sans extension. On n'en fait donc aucune copie : llama.cpp lit les mêmes octets, avec les mêmes noms (`qwen3:8b`,
`huihui_ai/qwen3-abliterated:4b`). Les modèles « sans filtre » d'Ollama sont donc, eux aussi, disponibles sous llama.cpp, sans rien retélécharger.

Rien n'est jamais écrit ni supprimé ici : lecture seule. Le gabarit de conversation et le texte système d'Ollama (autres morceaux) ne sont pas repris : llama.cpp utilise ceux que le fichier GGUF contient."""
import json
import re
from pathlib import Path

HOTE_OFFICIEL = "registry.ollama.ai"
TYPE_MODELE = "application/vnd.ollama.image.model"
TYPE_PROJECTEUR = "application/vnd.ollama.image.projector"
RE_EMPREINTE = re.compile(r"^sha256[:-]([0-9a-f]{64})$")
RE_PARTIE = re.compile(r"^[A-Za-z0-9][\w.-]*$")


def _blob(dossier, digest):
    m = RE_EMPREINTE.match(str(digest or ""))
    if not m:
        return None
    f = Path(dossier) / "blobs" / ("sha256-" + m.group(1))
    return f if f.is_file() else None


def lire(dossier_ollama):
    """{nom: {fichier, taille, projecteur}} pour chaque modèle de l'installation d'Ollama située dans `dossier_ollama` (son dossier « models »). Vide si le dossier n'existe pas ou n'est pas lisible.
    Les modèles hébergés ailleurs que sur le registre officiel d'Ollama sont ignorés. Un manifeste illisible ou dont le fichier manque est ignoré sans bruit."""
    sortie = {}
    if not dossier_ollama:
        return sortie
    base = Path(dossier_ollama) / "manifests" / HOTE_OFFICIEL
    try:
        fichiers = [f for f in base.rglob("*") if f.is_file()]
    except OSError:
        return sortie
    for f in fichiers:
        parties = f.relative_to(base).parts
        if len(parties) < 3 or not all(RE_PARTIE.match(p) for p in parties):
            continue
        espace, nom, tag = parties[0], "/".join(parties[1:-1]), parties[-1]
        ident = "{}:{}".format(nom if espace == "library" else "{}/{}".format(espace, nom), tag)
        if espace == "library" and len(parties) > 3:
            continue
        try:
            manifeste = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        couches = manifeste.get("layers") if isinstance(manifeste, dict) else None
        modele = projecteur = None
        for c in couches or []:
            if not isinstance(c, dict):
                continue
            if c.get("mediaType") == TYPE_MODELE:
                modele = _blob(dossier_ollama, c.get("digest"))
            elif c.get("mediaType") == TYPE_PROJECTEUR:
                projecteur = _blob(dossier_ollama, c.get("digest"))
        if modele is None:
            continue
        try:
            taille = modele.stat().st_size
        except OSError:
            continue
        sortie[ident] = {"fichier": modele, "taille": taille, "projecteur": projecteur}
    return sortie
