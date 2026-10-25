"""Choix des modèles selon la machine. Fonctions pures : mêmes entrées, mêmes sorties, testables sans matériel.

Principe : pour chaque rôle, le modèle le mieux noté qui TIENT dans la mémoire disponible (poids + mémoire de contexte). Un modèle « à experts » (peu de
paramètres actifs) peut déborder en RAM et reste utilisable, plus lentement : on le signale.
"""
from dataclasses import dataclass

from .catalogue import ROLES

CTX_PLAFOND, CTX_PLANCHER = 32768, 8192
MARGE_GO = 0.5                       # tampon de calcul d'Ollama
SEUIL_NOTE = 5                       # en dessous, un modèle n'est pas proposé pour ce rôle
PETIT_GO = 5.0                       # « Rapide » est coché par défaut seulement s'il pèse peu


@dataclass
class Choix:
    modele: dict
    num_ctx: int
    memoire_go: float
    tient: str                       # gpu | partiel | cpu
    role: str

    @property
    def id(self):
        return self.modele["id"]


def memoire_necessaire_go(modele, num_ctx, cache_compresse=True):
    """Poids + mémoire de contexte (divisée par 2 si le cache est compressé en q8, réglage par défaut de Lutin) + marge."""
    contexte = modele["kv_mo_1k"] * (num_ctx / 1000) / 1024 * (0.5 if cache_compresse else 1.0)
    return modele["go"] + contexte + MARGE_GO


def meilleur_contexte(modele, budget_go, ram_libre_go=0.0, experts_en_ram=True):
    """(num_ctx, mémoire nécessaire, 'gpu'|'partiel') du plus grand contexte qui tient, ou None."""
    plafond = min(CTX_PLAFOND, modele["ctx_max"])
    ctx = plafond
    while ctx >= min(CTX_PLANCHER, plafond):
        besoin = memoire_necessaire_go(modele, ctx)
        if besoin <= budget_go:
            return ctx, besoin, "gpu"
        ctx //= 2
    # Modèle à experts : le surplus passe en RAM (plus lent mais utilisable).
    if experts_en_ram and modele["actifs_b"] * 3 <= modele["params_b"]:
        besoin = memoire_necessaire_go(modele, min(CTX_PLANCHER, plafond))
        if besoin <= budget_go + ram_libre_go * 0.5:
            return min(CTX_PLANCHER, plafond), besoin, "partiel"
    return None


def _score(modele, role, tient, budget_go):
    note = modele["notes"].get(role, 0)
    s = note * 10
    taille = modele["go"]
    s += -taille * 0.2 if role == "rapide" else taille * 0.1          # rapide : le plus léger à note égale ; les autres : le plus gros qui tient
    if tient == "partiel":
        s -= 15
    if role == "rapide" and modele["actifs_b"] < modele["params_b"] / 3:
        s += 3                                                      # un modèle à experts répond vite
    return s


def choisir(profil, catalogue):
    """{rôle: Choix ou None}. Les modèles marqués « avancés » (sans filtre) ne sont JAMAIS choisis automatiquement : ils se choisissent à la main (voir `lister`)."""
    budget = profil.budget_go()
    cpu = profil.sans_gpu()
    ram_libre = profil.ram_libre_go or profil.ram_go * 0.5
    resultat = {}
    for role in ROLES:
        meilleur, meilleur_score = None, None
        for m in catalogue["modeles"]:
            if m.get("avance"):
                continue
            if "outils" not in m["capacites"] or m["notes"].get(role, 0) < SEUIL_NOTE:
                continue
            if role == "vision" and "vision" not in m["capacites"]:
                continue
            place = meilleur_contexte(m, budget, ram_libre, experts_en_ram=not cpu)
            if place is None:
                continue
            ctx, besoin, tient = place
            if cpu:
                tient = "cpu"
            sc = _score(m, role, tient, budget)
            if meilleur_score is None or sc > meilleur_score:
                meilleur, meilleur_score = Choix(m, ctx, round(besoin, 1), tient, role), sc
        resultat[role] = meilleur
    return resultat


def par_defaut(choix):
    """Rôles cochés au départ : Polyvalent, plus Rapide s'il est différent et léger. Les autres se choisissent à la main (un modèle = plusieurs Go)."""
    coches = []
    if choix.get("polyvalent"):
        coches.append("polyvalent")
    r = choix.get("rapide")
    if r and (not choix.get("polyvalent") or r.id != choix["polyvalent"].id) and r.modele["go"] <= PETIT_GO:
        coches.append("rapide")
    return coches


def a_telecharger(choix, roles, deja_installes=()):
    """(liste de modèles distincts, total en Go) pour les rôles demandés, sans recompter ce qui est déjà là."""
    vus, liste, total = set(), [], 0.0
    for role in roles:
        c = choix.get(role)
        if c and c.id not in vus and c.id not in deja_installes:
            vus.add(c.id)
            liste.append(c)
            total += c.modele["go"]
    return liste, round(total, 1)


def lister(profil, catalogue, avance=False):
    """Tous les modèles du catalogue avec ce qu'il en est pour cette machine (liste « Autres modèles »). Les avancés n'y figurent que si l'utilisateur a ouvert l'option."""
    budget, cpu = profil.budget_go(), profil.sans_gpu()
    ram_libre = profil.ram_libre_go or profil.ram_go * 0.5
    sortie = []
    for m in catalogue["modeles"]:
        if m.get("avance") and not avance:
            continue
        place = meilleur_contexte(m, budget, ram_libre, experts_en_ram=not cpu)
        sortie.append({"modele": m, "tient": None if place is None else ("cpu" if cpu else place[2]), "memoire_go": None if place is None else round(place[1], 1)})
    return sorted(sortie, key=lambda x: (x["tient"] is None, -x["modele"]["go"]))
