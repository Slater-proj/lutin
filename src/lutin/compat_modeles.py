"""Quels modèles du catalogue sont compatibles avec le moteur choisi, et pourquoi : la page ne propose JAMAIS un modèle que le moteur ne peut pas faire tourner.

Un modèle du catalogue est un nom de la bibliothèque d'Ollama (un fichier GGUF). Selon le moteur :
- Ollama : la bibliothèque est sa source ; tout le catalogue convient.
- llama.cpp géré par Lutin : lit les mêmes GGUF (Lutin les télécharge depuis la bibliothèque d'Ollama, sans Ollama) ; tout le catalogue convient tant que les capacités dont le modèle a besoin
  ne sont pas « non supportées » par ce moteur dans sa grille (voir moteurs.FONCTIONS).
- Un serveur externe (LM Studio, vLLM…) : il a ses propres modèles et Lutin ne peut pas en installer ; seuls ceux que le serveur propose (déjà installés) sont montrés.
Chaque réponse porte aussi : le format (GGUF), la quantification (celle du nom si elle y est, sinon celle par défaut de la bibliothèque) et la mémoire estimée (adequation.py), pour que la liste dise ce qu'elle propose.
Les rôles (polyvalent, rapide, code…) se choisissent sur le catalogue FILTRÉ : `roles_pour(...)`."""
import re

from . import selection
from .i18n import t as _t

CAPACITES = {"outils": "outils", "reflexion": "reflexion", "vision": "vision"}          # capacité du catalogue -> fonction de la grille des moteurs
CTX_ESTIMATION = 8192
RE_QUANT = re.compile(r"(?:^|[-_:])(q\d(?:_[a-z0-9]+)*|fp16|f16|bf16|int4|int8)$", re.I)


def quantification(ident):
    """La quantification lue dans le nom du modèle (« qwen3:8b-q8_0 » -> « Q8_0 »), ou « par défaut » (celle de la bibliothèque, en général Q4_K_M)."""
    m = RE_QUANT.search(str(ident or ""))
    return m.group(1).upper() if m else _t("par défaut")


def _etat_fonction(moteur, fonction):
    try:
        return (moteur.grille() or {}).get(fonction, ("non_teste", ""))
    except Exception:  # noqa: BLE001  (une grille illisible ne doit jamais masquer tout le catalogue)
        return ("non_teste", "")


def evaluer(modele, moteur, installes=(), profil=None):          # profil : réservé (l'adéquation à la machine reste dans adequation.py)
    """{compatible, raisons, avertissements, format, quant, memoire_go} pour ce modèle du catalogue sur ce moteur."""
    ident = modele["id"]
    sortie = {"compatible": True, "raisons": [], "avertissements": [], "format": "GGUF", "quant": quantification(ident), "memoire_go": None}
    try:
        sortie["memoire_go"] = round(selection.memoire_necessaire_go(modele, CTX_ESTIMATION), 1)          # poids + mémoire de conversation (8 192 jetons, cache compressé) + marge
    except (KeyError, TypeError):
        pass
    telechargeable = moteur.telechargeable() if hasattr(moteur, "telechargeable") else {"genre": "ollama"}
    if telechargeable.get("genre") == "aucun" and ident not in set(installes):
        sortie["compatible"] = False
        sortie["raisons"].append(_t("Ce serveur gère ses modèles lui-même : Lutin ne peut pas installer celui-ci."))
    for capacite in modele.get("capacites") or []:
        fonction = CAPACITES.get(capacite)
        if not fonction:
            continue
        etat, note = _etat_fonction(moteur, fonction)
        if etat == "non":
            sortie["compatible"] = False
            sortie["raisons"].append(_t("« {} » n'est pas pris en charge par {}.").format(capacite, moteur.nom) + (" " + note if note else ""))
        elif etat == "non_teste":
            sortie["avertissements"].append(_t("« {} » n'a pas été testé avec {}.").format(capacite, moteur.nom))
    return sortie


def pour_la_liste(catalogue_modeles, moteur, installes=(), profil=None):
    """{identifiant: évaluation} pour tout le catalogue."""
    return {m["id"]: evaluer(m, moteur, installes, profil) for m in catalogue_modeles}


def filtrer(catalogue, moteur, installes=(), profil=None):
    """Le catalogue sans les modèles incompatibles (même forme que `catalogue`), pour que les rôles ne choisissent jamais un modèle que le moteur ne sait pas faire tourner."""
    garde = [m for m in catalogue["modeles"] if evaluer(m, moteur, installes, None)["compatible"]]
    return dict(catalogue, modeles=garde)


def roles_pour(profil, catalogue, moteur, installes=()):
    """{rôle: Choix ou None} sur le catalogue filtré par ce moteur : les rôles sont propres à chaque moteur."""
    return selection.choisir(profil, filtrer(catalogue, moteur, installes))
