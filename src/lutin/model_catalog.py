"""Le catalogue de modèles : un fichier de données (jamais du code), validé avant usage.

Ordre de lecture : copie récupérée en ligne (cache) si elle est valide et plus récente, sinon copie livrée avec l'application. Un catalogue abîmé
ou incohérent est ignoré, jamais appliqué à moitié.
"""
import json
from pathlib import Path

ROLES = ("polyvalent", "rapide", "creatif", "code", "vision")
LABELS = {
    "polyvalent": ("Polyvalent", "Pour tout faire au quotidien : le choix par défaut."),
    "rapide": ("Rapide", "Réponses presque immédiates, pour les questions simples."),
    "creatif": ("Créatif", "Écriture, histoires, idées et reformulations."),
    "code": ("Code", "Programmation, scripts, correction d'erreurs."),
    "vision": ("Images", "Comprend les images, captures d'écran et documents."),
}
CAPABILITIES = {"outils", "vision", "reflexion"}
REQUIRED = ("id", "nom", "phrase", "go", "params_b", "actifs_b", "ctx_max", "kv_mo_1k", "capacites", "licence", "notes")
SHIPPED_FILE = Path(__file__).resolve().parent / "data" / "modeles.json"


class CatalogError(ValueError):
    pass


def validate(catalogue):
    """Lève ErreurCatalogue au premier défaut ; renvoie le catalogue sinon."""
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("modeles"), list) or not catalogue["modeles"]:
        raise CatalogError("catalogue vide ou mal formé")
    if not isinstance(catalogue.get("version"), int):
        raise CatalogError("numéro de version manquant")
    vus = set()
    for m in catalogue["modeles"]:
        if not isinstance(m, dict):
            raise CatalogError("entrée de modèle invalide")
        for cle in REQUIRED:
            if cle not in m:
                raise CatalogError("{} : champ « {} » manquant".format(m.get("id", "?"), cle))
        ident = m["id"]
        if not isinstance(ident, str) or not ident.strip() or ident in vus:
            raise CatalogError("identifiant vide ou en double : {!r}".format(ident))
        vus.add(ident)
        if not (isinstance(m["go"], (int, float)) and 0 < m["go"] < 2000):
            raise CatalogError("{} : taille incohérente".format(ident))
        if not isinstance(m["capacites"], list) or not set(m["capacites"]) <= CAPABILITIES:
            raise CatalogError("{} : capacités inconnues".format(ident))
        if len(m["phrase"]) > 140:
            raise CatalogError("{} : la description doit tenir en une phrase courte (140 caractères)".format(ident))
        if not isinstance(m["notes"], dict) or not m["notes"] or any((k not in ROLES or not isinstance(v, (int, float)) or not 0 <= v <= 10) for k, v in m["notes"].items()):
            raise CatalogError("{} : notes invalides".format(ident))
        if "vision" in m["notes"] and "vision" not in m["capacites"]:
            raise CatalogError("{} : noté en vision sans la capacité".format(ident))
        if m.get("avance") and not m.get("avertissement"):
            raise CatalogError("{} : un modèle avancé doit porter un avertissement".format(ident))
    return catalogue


def load(cache=None, fichier=SHIPPED_FILE):
    """Catalogue à utiliser. `cache` : chemin d'une copie récupérée en ligne (facultatif)."""
    livre = validate(json.loads(Path(fichier).read_text(encoding="utf-8")))
    if cache and Path(cache).is_file():
        try:
            distant = validate(json.loads(Path(cache).read_text(encoding="utf-8")))
            if (distant["version"], distant.get("date", "")) > (livre["version"], livre.get("date", "")):
                return distant
        except (OSError, ValueError):
            pass                                     # cache abîmé : on garde la copie livrée
    return livre


def by_id(catalogue):
    return {m["id"]: m for m in catalogue["modeles"]}
