"""Le catalogue de modèles : un fichier de données (jamais du code), validé avant usage.

Ordre de lecture : copie récupérée en ligne (cache) si elle est valide et plus récente, sinon copie livrée avec l'application. Un catalogue abîmé
ou incohérent est ignoré, jamais appliqué à moitié.
"""
import json
from pathlib import Path

ROLES = ("polyvalent", "rapide", "creatif", "code", "vision")
LIBELLES = {
    "polyvalent": ("Polyvalent", "Pour tout faire au quotidien : le choix par défaut."),
    "rapide": ("Rapide", "Réponses presque immédiates, pour les questions simples."),
    "creatif": ("Créatif", "Écriture, histoires, idées et reformulations."),
    "code": ("Code", "Programmation, scripts, correction d'erreurs."),
    "vision": ("Images", "Comprend les images, captures d'écran et documents."),
}
CAPACITES = {"outils", "vision", "reflexion"}
OBLIGATOIRES = ("id", "nom", "phrase", "go", "params_b", "actifs_b", "ctx_max", "kv_mo_1k", "capacites", "licence", "notes")
FICHIER_LIVRE = Path(__file__).resolve().parent / "data" / "modeles.json"


class ErreurCatalogue(ValueError):
    pass


def valider(catalogue):
    """Lève ErreurCatalogue au premier défaut ; renvoie le catalogue sinon."""
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("modeles"), list) or not catalogue["modeles"]:
        raise ErreurCatalogue("catalogue vide ou mal formé")
    if not isinstance(catalogue.get("version"), int):
        raise ErreurCatalogue("numéro de version manquant")
    vus = set()
    for m in catalogue["modeles"]:
        if not isinstance(m, dict):
            raise ErreurCatalogue("entrée de modèle invalide")
        for cle in OBLIGATOIRES:
            if cle not in m:
                raise ErreurCatalogue("{} : champ « {} » manquant".format(m.get("id", "?"), cle))
        ident = m["id"]
        if not isinstance(ident, str) or not ident.strip() or ident in vus:
            raise ErreurCatalogue("identifiant vide ou en double : {!r}".format(ident))
        vus.add(ident)
        if not (isinstance(m["go"], (int, float)) and 0 < m["go"] < 2000):
            raise ErreurCatalogue("{} : taille incohérente".format(ident))
        if not isinstance(m["capacites"], list) or not set(m["capacites"]) <= CAPACITES:
            raise ErreurCatalogue("{} : capacités inconnues".format(ident))
        if len(m["phrase"]) > 140:
            raise ErreurCatalogue("{} : la description doit tenir en une phrase courte (140 caractères)".format(ident))
        if not isinstance(m["notes"], dict) or not m["notes"] or any((k not in ROLES or not isinstance(v, (int, float)) or not 0 <= v <= 10) for k, v in m["notes"].items()):
            raise ErreurCatalogue("{} : notes invalides".format(ident))
        if "vision" in m["notes"] and "vision" not in m["capacites"]:
            raise ErreurCatalogue("{} : noté en vision sans la capacité".format(ident))
        if m.get("avance") and not m.get("avertissement"):
            raise ErreurCatalogue("{} : un modèle avancé doit porter un avertissement".format(ident))
    return catalogue


def charger(cache=None, fichier=FICHIER_LIVRE):
    """Catalogue à utiliser. `cache` : chemin d'une copie récupérée en ligne (facultatif)."""
    livre = valider(json.loads(Path(fichier).read_text(encoding="utf-8")))
    if cache and Path(cache).is_file():
        try:
            distant = valider(json.loads(Path(cache).read_text(encoding="utf-8")))
            if (distant["version"], distant.get("date", "")) > (livre["version"], livre.get("date", "")):
                return distant
        except (OSError, ValueError):
            pass                                     # cache abîmé : on garde la copie livrée
    return livre


def par_id(catalogue):
    return {m["id"]: m for m in catalogue["modeles"]}
