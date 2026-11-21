"""Un modèle convient-il à CETTE machine ? Une appréciation par modèle, calculée avec les mêmes règles que le choix automatique (model_selection.py).

Fonctions pures pour `evaluer` (testables sans matériel) ; la machine elle-même n'est détectée qu'une fois par minute au plus (la détection lance des programmes), et jamais pendant
l'affichage d'une page : tant qu'elle n'est pas prête, il n'y a simplement pas d'appréciation."""
import threading
import time

from . import model_selection
from .i18n import t as _t

NIVEAUX = ("ideal", "bien", "limite", "trop_gros")
DUREE = 120
KV_MO_PAR_DEFAUT = 120               # mémoire de contexte (Mo pour 1000 jetons) d'un modèle que le catalogue ne connaît pas : estimation prudente
_etat = {"profil": None, "quand": 0.0, "en_cours": False}
_verrou = threading.Lock()


def pseudo_modele(m):
    """Les données minimales d'un modèle hors catalogue (ajouté à la main, installé ailleurs) : sa taille seulement."""
    return {"go": m.get("go") or 0, "kv_mo_1k": KV_MO_PAR_DEFAUT, "ctx_max": 32768, "params_b": 1, "actifs_b": 1}


MOE_RAM_CONFORT_GO = 4.0          # mémoire vive qui reste libre, réserve comprise, en dessous de laquelle un modèle à experts en partie en mémoire vive est « limite »


def evaluer(m, profil, ctx_voulu=0, experts_en_ram=True):
    """{niveau, texte} : ideal (large marge), bien, limite (tient à peine, contexte réduit, ou en partie sur le processeur), trop_gros. `m` : au moins `go`, et idéalement les champs du catalogue.
    `experts_en_ram` : le moteur sait garder les experts d'un modèle à experts en mémoire vive (aptitude `experts_in_ram` du moteur choisi)."""
    if not m.get("go"):
        return {"niveau": "bien", "texte": _t("Taille inconnue : je ne peux pas dire si ce modèle convient à ta machine.")}
    complet = dict(pseudo_modele(m), **{k: v for k, v in m.items() if k in ("kv_mo_1k", "ctx_max", "params_b", "actifs_b")})
    complet["go"] = m["go"]
    budget = profil.budget_go()
    ram_libre = model_selection.ram_for_experts(profil)
    place = model_selection.best_context(complet, budget, ram_libre, experts_en_ram=experts_en_ram and not profil.sans_gpu())
    if place is None and not profil.sans_gpu() and model_selection.best_context(complet, budget / 0.85, 0, experts_en_ram=False):
        return {"niveau": "limite", "texte": _t("Tient presque entièrement sur la carte graphique, sans marge : ferme les autres programmes qui l'utilisent et garde une conversation courte.")}
    if place is None:
        besoin = model_selection.required_memory_gb(complet, model_selection.CTX_PLANCHER)
        if model_selection.expert_share(complet) and not profil.sans_gpu() and not experts_en_ram and model_selection.experts_split(complet, model_selection.CTX_PLANCHER, budget, ram_libre):
            return {"niveau": "trop_gros", "texte": _t("Trop gros pour la carte graphique avec ce moteur : il tiendrait en gardant ses experts en mémoire vive, ce que fait llama.cpp ou Ollama.")}
        return {"niveau": "trop_gros", "texte": _t("Trop gros pour ta machine : il demande environ {} Go et tu en as {} d'utilisables.").format(round(besoin, 1), budget)}
    ctx, besoin, tient = place
    if tient == "partiel":
        # seul un modèle à experts « tient en partie » (model_selection.best_context) : ce qui travaille à chaque mot va sur la carte, les experts qui n'y tiennent pas attendent en mémoire vive
        en_ram = max(0.0, besoin - budget)
        reste = ram_libre - en_ram
        if reste < MOE_RAM_CONFORT_GO or ctx < 16384:
            return {"niveau": "limite", "texte": _t("Modèle à experts, juste pour ta machine : {} Go d'experts attendent en mémoire vive et il n'en reste que {} Go de libres. Ferme les gros programmes ; conversation de {} jetons.").format(round(en_ram, 1), round(max(0.0, reste), 1), ctx)}
        return {"niveau": "bien", "texte": _t("Modèle à experts : ce qui travaille à chaque mot va sur la carte graphique, {} Go d'experts attendent en mémoire vive. Il répond à un bon rythme, mais lit plus lentement les longs messages.").format(round(en_ram, 1))}
    if profil.sans_gpu():
        if m["go"] <= 3:
            return {"niveau": "bien", "texte": _t("Sans carte graphique, un petit modèle comme celui-ci répond à un rythme correct.")}
        actif_go = m["go"] * (complet.get("actifs_b") or 0) / complet["params_b"] if complet.get("params_b") else 0          # sur processeur, la vitesse suit la part du modèle qui travaille à chaque mot
        if 0 < actif_go <= 1.5:
            return {"niveau": "bien", "texte": _t("Modèle à experts : seule une petite partie travaille à chaque mot, il répond à un rythme correct même sans carte graphique.")}
        return {"niveau": "limite", "texte": _t("Sans carte graphique ce modèle tourne sur le processeur : il répond lentement.")}
    if ctx < 16384:
        return {"niveau": "limite", "texte": _t("Tient à peine : la mémoire ne laisse que {} jetons de conversation.").format(ctx)}
    if besoin <= budget * 0.6:
        return {"niveau": "ideal", "texte": _t("Très à l'aise sur ta machine : de la marge pour une longue conversation.")}
    return {"niveau": "bien", "texte": _t("Convient à ta machine ({} Go sur {} utilisables).").format(round(besoin, 1), budget)}


CARTE_RESERVE_GO = 1.0          # ce que le bureau et les autres programmes gardent sur la carte graphique


def evaluer_carte_seule(go, profil, ctx):
    """Le verdict pour un moteur qui ne déborde JAMAIS en mémoire vive et réserve tout de suite le cache de la fenêtre de conversation (ExLlamaV3 :
    TabbyAPI réserve `cache_size`, compressé en Q8). Le jugement commun disait « Juste » d'un modèle qui ne tient qu'en débordant : chargé, il échouait
    sur « Insufficient VRAM in split for model and cache » (mainteneur, RTX 4090, 2026-11-21). Ici : poids + cache de `ctx` jetons + marge, sur la carte seule."""
    g = profil.gpu_principal() if profil is not None else None
    if not go or g is None or not g.vram_go:
        return evaluer({"go": go}, profil, experts_en_ram=False) if profil is not None and go else None
    besoin = model_selection.required_memory_gb(dict(pseudo_modele({"go": go}), go=go), max(4096, int(ctx or 0)))
    utilisable = g.vram_go - CARTE_RESERVE_GO
    if besoin > utilisable:
        return {"niveau": "trop_gros", "texte": _t("Ne tient pas avec ce moteur : tout doit tenir dans la carte graphique, environ {} Go avec {} jetons de conversation, et ta carte en a {} d'utilisables. Prends une quantification plus légère (moins de bpw) ou réduis la fenêtre de contexte (Réglages > Conversation).").format(round(besoin, 1), int(ctx), round(utilisable, 1))}
    if besoin > utilisable * 0.9:
        return {"niveau": "limite", "texte": _t("Tient dans la carte graphique, sans marge : environ {} Go avec {} jetons de conversation, sur {} d'utilisables. Ferme les autres programmes qui utilisent la carte.").format(round(besoin, 1), int(ctx), round(utilisable, 1))}
    if besoin <= utilisable * 0.6:
        return {"niveau": "ideal", "texte": _t("Très à l'aise sur ta carte graphique : environ {} Go avec {} jetons de conversation, sur {} d'utilisables.").format(round(besoin, 1), int(ctx), round(utilisable, 1))}
    return {"niveau": "bien", "texte": _t("Tient dans ta carte graphique : environ {} Go avec {} jetons de conversation, sur {} d'utilisables.").format(round(besoin, 1), int(ctx), round(utilisable, 1))}


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
                from .hardware import detecter as d
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


def profil_attendu(delai=25, detecter=None):
    """Comme profil_pret, mais attend la fin de la détection (au plus `delai` secondes) : pour un choix qui en dépend et ne peut pas être refait (quel programme télécharger : CUDA, Vulkan ou processeur).
    Renvoie None si la détection échoue ou dépasse le délai."""
    fin = time.time() + delai
    profil = profil_pret(detecter)
    while profil is None and time.time() < fin:
        time.sleep(0.2)
        profil = profil_pret(detecter)
    return profil


def pour_la_liste(modeles, profil, catalogue):
    """{identifiant: {niveau, texte}} pour la liste de l'onglet Modèles (vide tant que la machine n'est pas détectée). `catalogue` : les modèles complets (mémoire de contexte, taille maximale…)."""
    if profil is None:
        return {}
    connus = {c["id"]: c for c in catalogue}
    return {m["id"]: evaluer(dict(m, **{k: v for k, v in connus.get(m["id"], {}).items() if k in ("kv_mo_1k", "ctx_max", "params_b", "actifs_b")}), profil) for m in modeles}
