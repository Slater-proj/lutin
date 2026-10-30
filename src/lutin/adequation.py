"""Un modèle convient-il à CETTE machine ? Une appréciation par modèle, calculée avec les mêmes règles que le choix automatique (selection.py).

Fonctions pures pour `evaluer` (testables sans matériel) ; la machine elle-même n'est détectée qu'une fois par minute au plus (la détection lance des programmes), et jamais pendant
l'affichage d'une page : tant qu'elle n'est pas prête, il n'y a simplement pas d'appréciation."""
import threading
import time

from . import selection
from .i18n import t as _t

NIVEAUX = ("ideal", "bien", "limite", "trop_gros")
DUREE = 120
KV_MO_PAR_DEFAUT = 120               # mémoire de contexte (Mo pour 1000 jetons) d'un modèle que le catalogue ne connaît pas : estimation prudente
_etat = {"profil": None, "quand": 0.0, "en_cours": False}
_verrou = threading.Lock()


def pseudo_modele(m):
    """Les données minimales d'un modèle hors catalogue (ajouté à la main, installé ailleurs) : sa taille seulement."""
    return {"go": m.get("go") or 0, "kv_mo_1k": KV_MO_PAR_DEFAUT, "ctx_max": 32768, "params_b": 1, "actifs_b": 1}


def evaluer(m, profil, ctx_voulu=0):
    """{niveau, texte} : ideal (large marge), bien, limite (tient à peine, contexte réduit, ou en partie sur le processeur), trop_gros. `m` : au moins `go`, et idéalement les champs du catalogue."""
    if not m.get("go"):
        return {"niveau": "bien", "texte": _t("Taille inconnue : je ne peux pas dire si ce modèle convient à ta machine.")}
    complet = dict(pseudo_modele(m), **{k: v for k, v in m.items() if k in ("kv_mo_1k", "ctx_max", "params_b", "actifs_b")})
    complet["go"] = m["go"]
    budget = profil.budget_go()
    place = selection.meilleur_contexte(complet, budget, profil.ram_libre_go or profil.ram_go * 0.5, experts_en_ram=not profil.sans_gpu())
    if place is None and not profil.sans_gpu() and selection.meilleur_contexte(complet, budget / 0.85, 0, experts_en_ram=False):
        return {"niveau": "limite", "texte": _t("Tient presque entièrement sur la carte graphique, sans marge : ferme les autres programmes qui l'utilisent et garde une conversation courte.")}
    if place is None:
        besoin = selection.memoire_necessaire_go(complet, selection.CTX_PLANCHER)
        return {"niveau": "trop_gros", "texte": _t("Trop gros pour ta machine : il demande environ {} Go et tu en as {} d'utilisables.").format(round(besoin, 1), budget)}
    ctx, besoin, tient = place
    if tient == "partiel":
        return {"niveau": "limite", "texte": _t("Tient en partie sur la carte graphique, le reste sur le processeur : utilisable mais lent.")}
    if profil.sans_gpu():
        if m["go"] <= 3:
            return {"niveau": "bien", "texte": _t("Sans carte graphique, un petit modèle comme celui-ci répond à un rythme correct.")}
        return {"niveau": "limite", "texte": _t("Sans carte graphique ce modèle tourne sur le processeur : il répond lentement.")}
    if ctx < 16384:
        return {"niveau": "limite", "texte": _t("Tient à peine : la mémoire ne laisse que {} jetons de conversation.").format(ctx)}
    if besoin <= budget * 0.6:
        return {"niveau": "ideal", "texte": _t("Très à l'aise sur ta machine : de la marge pour une longue conversation.")}
    return {"niveau": "bien", "texte": _t("Convient à ta machine ({} Go sur {} utilisables).").format(round(besoin, 1), budget)}


def profil_pret(detecter=None):
    """Le profil de la machine s'il est déjà connu ; sinon None, et la détection démarre en arrière-plan (la page l'affichera au prochain rafraîchissement)."""
    with _verrou:
        frais = _etat["profil"] is not None and time.time() - _etat["quand"] < DUREE
        if frais or _etat["en_cours"]:
            return _etat["profil"]
        _etat["en_cours"] = True

    def travail():
        try:
            if detecter is None:
                from .machine import detecter as d
            else:
                d = detecter
            profil = d()
            with _verrou:
                _etat["profil"], _etat["quand"] = profil, time.time()
        except Exception:  # noqa: BLE001 — une machine illisible ne doit pas casser la page
            pass
        finally:
            with _verrou:
                _etat["en_cours"] = False
    threading.Thread(target=travail, daemon=True, name="detection-machine").start()
    return _etat["profil"]


def pour_la_liste(modeles, profil, catalogue):
    """{identifiant: {niveau, texte}} pour la liste de l'onglet Modèles (vide tant que la machine n'est pas détectée). `catalogue` : les modèles complets (mémoire de contexte, taille maximale…)."""
    if profil is None:
        return {}
    connus = {c["id"]: c for c in catalogue}
    return {m["id"]: evaluer(dict(m, **{k: v for k, v in connus.get(m["id"], {}).items() if k in ("kv_mo_1k", "ctx_max", "params_b", "actifs_b")}), profil) for m in modeles}
