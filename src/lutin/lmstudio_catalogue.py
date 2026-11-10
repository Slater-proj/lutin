"""Les modèles de LM Studio : où les trouver, comment les juger pour cette machine.

LM Studio lit des fichiers GGUF. Sa communauté officielle (lmstudio-community) en publie sur Hugging Face, un dépôt par modèle et un fichier par quantification (« Q4_K_M » : petit et rapide,
« Q8_0 » : plus fidèle, plus gros). Même mécanique que pour ExLlamaV3 (voir exllamav3_catalogue.py) : recherche par l'API publique de Hugging Face, taille exacte de chaque fichier, estimation
d'après le nom. Rien n'est téléchargé ici : `lms get <dépôt>@<quantification>` le fait, sur clic."""
import re
import urllib.parse

from . import exllamav3_catalogue as base
from . import miseajour
from .i18n import t as _t

AUTEUR_OFFICIEL = "lmstudio-community"
BPW_ESTIME = 4.85          # Q4_K_M, la quantification la plus courante
RE_QUANT = re.compile(r"[-_.]((?:IQ|Q)\d\w*?|BF16|F16|F32|MXFP4)(?:-\d{5}-of-\d{5})?\.gguf$", re.I)


def chercher(q="", tri="recent", communaute=False, page=1, http=miseajour.http_get):
    return base.chercher(q, tri, communaute, page, http, auteur=AUTEUR_OFFICIEL, etiquette="gguf", bpw=BPW_ESTIME)


def quantifications(depot, http=miseajour.http_get):
    """Les fichiers GGUF d'un dépôt regroupés par quantification : [{revision (la quantification), go, fichiers}] du plus léger au plus lourd. Les projecteurs d'images (mmproj) ne sont pas des modèles."""
    if not base.RE_DEPOT.match(str(depot)):
        raise ValueError(_t("Nom de dépôt invalide : écris « propriétaire/modèle » (Hugging Face)."))
    fichiers = base._json(base.API + "/" + urllib.parse.quote(depot, safe="/") + "/tree/main", http)
    groupes = {}
    for f in fichiers if isinstance(fichiers, list) else []:
        nom = str(f.get("path", ""))
        if f.get("type") != "file" or not nom.lower().endswith(".gguf") or "mmproj" in nom.lower():
            continue
        m = RE_QUANT.search(nom)
        quant = m.group(1).upper() if m else nom[:-5]
        g = groupes.setdefault(quant, {"revision": quant, "fichiers": 0, "octets": 0})
        g["fichiers"] += 1
        g["octets"] += int(f.get("size") or 0)
    sortie = [{"revision": g["revision"], "go": round(g["octets"] / 1e9, 1) or None, "fichiers": g["fichiers"]} for g in groupes.values()]
    return sorted(sortie, key=lambda q: (q["go"] is None, q["go"] or 0))
