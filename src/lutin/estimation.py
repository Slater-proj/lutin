"""Estimer AVANT de charger : ce qu'un modèle prendra comme mémoire (poids + conversation + marge), où (carte graphique, mémoire vive), et si ça va saturer la machine.

Les chiffres viennent du catalogue (taille du fichier, mémoire de conversation par millier de jetons) et de selection.py ; ils sont des ESTIMATIONS. Le banc des moteurs (bench_moteurs.py) mesure la mémoire réellement
prise : `ecart()` compare les deux, et l'écart est affiché avec la mesure pour que l'estimation ne soit jamais crue sur parole.

Quatre niveaux, du meilleur au pire :
- `tient`      : tout tient sur la carte graphique (ou, sans carte, dans la mémoire vive avec de la marge) ;
- `partiel`    : une partie sur la carte, le reste en mémoire vive (utilisable, plus lent) ;
- `sature`     : ça tient à peine, il ne reste presque rien pour le système : risque de ralentir tout le PC ;
- `trop_gros`  : ça ne tient pas : à ne pas charger.

Modèles « à experts » (peu de paramètres actifs par mot) : `preset_experts()` calcule la part des experts à laisser sur le processeur (--n-cpu-moe de llama.cpp) pour que le reste tienne sur la carte.
Mode prudent : `mode_prudent()` dit si la machine est modeste et quels réglages la ménagent (petite conversation, un seul modèle chargé)."""
import math

from . import selection
from .i18n import t as _t

MARGE_SATURATION_GO = 2.0          # mémoire vive qu'on veut garder libre pour le système
CTX_PRUDENT = 8192
COUCHES_EXPERTS_DEFAUT = 48          # nombre courant de couches des modèles à experts de 30 milliards (estimation : la vraie valeur est dans le fichier GGUF)
KV = {"f16": 1.0, "q8_0": 0.5, "q4_0": 0.25}          # part de la mémoire de conversation selon le type de cache KV


def _kv_go(modele, ctx, cache="q8_0"):
    return modele["kv_mo_1k"] * (ctx / 1000) / 1024 * KV.get(cache, 0.5)


def estimer(modele, ctx, profil, cache="q8_0", experts_cpu=0.0):
    """{poids_go, kv_go, total_go, sur_carte_go, sur_ram_go, niveau, texte, conseils} pour ce modèle du catalogue avec cette conversation sur cette machine. `experts_cpu` : part (0 à 1) des experts laissés sur le processeur."""
    poids = float(modele["go"])
    kv = _kv_go(modele, ctx, cache)
    total = poids + kv + selection.MARGE_GO
    experts_go = 0.0
    if experts_cpu and modele.get("actifs_b") and modele.get("params_b") and modele["params_b"] > modele["actifs_b"]:
        experts_go = poids * (1 - modele["actifs_b"] / modele["params_b"]) * min(1.0, max(0.0, experts_cpu))
    sortie = {"poids_go": round(poids, 1), "kv_go": round(kv, 1), "total_go": round(total, 1), "cache": cache, "ctx": ctx, "conseils": []}
    ram_libre = (profil.ram_libre_go or profil.ram_go * 0.5) if profil is not None else 0.0
    if profil is None:
        sortie.update(sur_carte_go=None, sur_ram_go=None, niveau="inconnu", texte=_t("Machine pas encore détectée : je ne peux pas estimer."))
        return sortie
    budget = profil.budget_go()
    if profil.sans_gpu():
        sur_carte, sur_ram = 0.0, total
    else:
        sur_carte = min(total - experts_go, budget)
        sur_ram = total - sur_carte
    sortie.update(sur_carte_go=round(sur_carte, 1), sur_ram_go=round(sur_ram, 1))
    if sur_ram > ram_libre:
        niveau = "trop_gros"
        texte = _t("Ne tient pas : il demande environ {} Go ({} sur la carte, {} en mémoire vive) et la mémoire vive libre est de {} Go.").format(round(total, 1), round(sur_carte, 1), round(sur_ram, 1), round(ram_libre, 1))
    elif sur_ram > max(0.0, ram_libre - MARGE_SATURATION_GO):
        niveau = "sature"
        texte = _t("Tient à peine : il demande environ {} Go et ne laisse presque rien de libre en mémoire vive ({} Go). Le PC peut ralentir.").format(round(total, 1), round(ram_libre - sur_ram, 1))
    elif sur_ram > 0.5 and not profil.sans_gpu():
        niveau = "partiel"
        texte = _t("Tient en partie sur la carte ({} Go) ; {} Go passent en mémoire vive : utilisable mais plus lent.").format(round(sur_carte, 1), round(sur_ram, 1))
    else:
        niveau = "tient"
        texte = _t("Tient : environ {} Go ({} Go de modèle + {} Go de conversation).").format(round(total, 1), round(poids, 1), round(kv, 1))
    sortie.update(niveau=niveau, texte=texte)
    if niveau in ("trop_gros", "sature", "partiel"):
        sortie["conseils"] = conseils(modele, ctx, profil, cache)
    return sortie


def conseils(modele, ctx, profil, cache="q8_0"):
    """Ce qui ferait tenir le modèle : une conversation plus courte, un cache plus léger, et pour un modèle à experts le préréglage processeur."""
    liste = []
    place = selection.meilleur_contexte(modele, profil.budget_go(), profil.ram_libre_go or profil.ram_go * 0.5, experts_en_ram=not profil.sans_gpu())
    if place is not None and place[0] < ctx:
        liste.append(_t("Baisse la fenêtre de conversation à {} jetons : le modèle tiendra mieux.").format(place[0]))
    if cache != "q4_0" and _kv_go(modele, ctx, cache) > 1.0:
        liste.append(_t("Un cache de conversation plus léger (q4_0) économise environ {} Go, au prix d'une légère perte de précision.").format(round(_kv_go(modele, ctx, cache) - _kv_go(modele, ctx, "q4_0"), 1)))
    preset = preset_experts(modele, profil, ctx, cache)
    if preset:
        liste.append(preset["texte"])
    return liste


def preset_experts(modele, profil, ctx=CTX_PRUDENT, cache="q8_0"):
    """Pour un modèle à experts trop gros pour la carte : {part, n_cpu_moe, couches, texte} — la part des experts à laisser sur le processeur (--n-cpu-moe de llama.cpp) pour que le reste tienne sur la carte. None si ce n'est pas utile."""
    if profil is None or profil.sans_gpu() or not modele.get("actifs_b") or not modele.get("params_b") or modele["params_b"] <= modele["actifs_b"] * 1.5:
        return None
    total = modele["go"] + _kv_go(modele, ctx, cache) + selection.MARGE_GO
    budget = profil.budget_go()
    if total <= budget:
        return None
    experts_go = modele["go"] * (1 - modele["actifs_b"] / modele["params_b"])
    ram_libre = profil.ram_libre_go or profil.ram_go * 0.5
    a_deplacer = total - budget
    if a_deplacer > experts_go or a_deplacer > ram_libre:
        return None          # même tous les experts sur le processeur, ou la mémoire vive libre, ne suffisent pas
    part = a_deplacer / experts_go
    couches = COUCHES_EXPERTS_DEFAUT
    n = max(1, min(couches, math.ceil(part * couches)))
    return {"part": round(part, 2), "n_cpu_moe": n, "couches": couches,
            "texte": _t("Modèle à experts : laisse les experts de {} couches sur le processeur (--n-cpu-moe {}, estimation sur {} couches), le reste tient sur la carte. Réglages > Moteurs > llama.cpp > Réglages avancés.").format(n, n, couches)}


def mode_prudent(profil):
    """{actif, reglages, texte} : la machine est-elle modeste (peu de mémoire utilisable) et quels réglages la ménagent ? Jamais appliqué sans clic."""
    if profil is None:
        return {"actif": False, "reglages": {}, "texte": ""}
    modeste = profil.budget_go() < 8 or (profil.sans_gpu() and profil.ram_go < 16)
    if not modeste:
        return {"actif": False, "reglages": {}, "texte": ""}
    return {"actif": True, "reglages": {"num_ctx": CTX_PRUDENT, "modeles_max": 1},
            "texte": _t("Machine modeste ({} Go utilisables) : conversation limitée à {} jetons et un seul modèle chargé à la fois ménagent la mémoire.").format(round(profil.budget_go(), 1), CTX_PRUDENT)}


def ecart(estime_go, mesure_go):
    """Écart relatif entre l'estimation et la mesure du banc, en % de la mesure (positif : on a surestimé). None si une des deux manque."""
    if not estime_go or not mesure_go:
        return None
    return round(100 * (estime_go - mesure_go) / mesure_go, 1)
