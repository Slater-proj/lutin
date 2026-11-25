"""Choix des modèles selon la machine. Fonctions pures : mêmes entrées, mêmes sorties, testables sans matériel.

Principe : pour chaque rôle, le modèle le mieux noté qui TIENT dans la mémoire disponible (poids + mémoire de contexte). Un modèle « à experts » (peu de
paramètres actifs) peut garder une partie de ses experts en mémoire vive, si le moteur sait le faire : ce qui travaille à chaque mot (attention, poids
partagés) et la conversation restent sur la carte, les experts qui n'y tiennent pas attendent en mémoire vive. On le signale (« partiel »).
"""
from dataclasses import dataclass

from .model_catalog import ROLES

CTX_PLAFOND, CTX_PLANCHER = 32768, 8192
COMFORT_CTX = 16384                       # en dessous, une conversation est « juste » (model_fit) : un modèle à experts préfère alors garder des experts en mémoire vive
MARGIN_GB = 0.5                       # tampon de calcul d'Ollama
SCORE_THRESHOLD = 5                       # en dessous, un modèle n'est pas proposé pour ce rôle
SMALL_GB = 5.0                       # « Rapide » est coché par défaut seulement s'il pèse peu
RAM_RESERVE_GB = 2.0                       # mémoire vive libre laissée au système et à Lutin quand des experts y attendent


@dataclass
class Choice:
    modele: dict
    num_ctx: int
    memoire_go: float
    tient: str                       # gpu | partiel | cpu
    role: str

    @property
    def id(self):
        return self.modele["id"]


def required_memory_gb(modele, num_ctx, cache_compresse=True):
    """Poids + mémoire de contexte (divisée par 2 si le cache est compressé en q8, réglage par défaut de Lutin) + marge."""
    contexte = modele["kv_mo_1k"] * (num_ctx / 1000) / 1024 * (0.5 if cache_compresse else 1.0)
    return modele["go"] + contexte + MARGIN_GB


def expert_share(modele):
    """La part des poids d'un modèle « à experts » qui sont des experts (0 pour un modèle dense, ou dont les experts actifs sont plus d'un tiers).
    Estimée par 1 − actifs / total : la part réelle, lue dans les fichiers GGUF de sept modèles du registre d'Ollama, est un peu plus grande
    (0,92 à 0,97, docs/modernization/LARGE_MODELS.md) : l'estimation laisse un peu plus sur la carte qu'il n'en faut, jamais moins."""
    params, actifs = modele.get("params_b") or 0, modele.get("actifs_b") or 0
    if params <= 0 or actifs <= 0 or actifs * 3 > params:
        return 0.0
    return 1 - actifs / params


def ram_for_experts(profil):
    """La mémoire vive libre où des experts peuvent attendre sur cette machine : la mesurée (la moitié de la mémoire si la mesure manque), et aucune quand
    la personne a fixé elle-même la mémoire des modèles : ce chiffre est alors un plafond pour tout le modèle (machine partagée avec d'autres services)."""
    impose = getattr(profil, "budget_impose", None)
    if callable(impose) and impose():
        return 0.0
    return profil.ram_libre_go or profil.ram_go * 0.5


def experts_split(modele, num_ctx, budget_go, ram_libre_go):
    """Pour un modèle à experts qui ne tient pas sur la carte : (mémoire nécessaire, Go sur la carte, Go en mémoire vive) si ça tient, sinon None.
    La carte garde ce qui n'est pas un expert, la conversation et la marge, puis se remplit d'experts jusqu'à son budget ; le reste des experts va en mémoire vive,
    qui doit en garder RAM_RESERVE_GB de libres. `ram_libre_go` : la mémoire vive libre mesurée sur la machine."""
    part = expert_share(modele)
    if not part:
        return None
    besoin = required_memory_gb(modele, num_ctx)
    socle = besoin - modele["go"] * part          # tout sauf les experts : il faut que ce soit sur la carte
    en_ram = max(0.0, besoin - budget_go)
    if socle > budget_go or en_ram > max(0.0, ram_libre_go - RAM_RESERVE_GB):
        return None
    return besoin, besoin - en_ram, en_ram


def best_context(modele, budget_go, ram_libre_go=0.0, experts_en_ram=True):
    """(num_ctx, mémoire nécessaire, 'gpu'|'partiel') du plus grand contexte qui tient, ou None. `experts_en_ram` : le moteur sait garder les experts d'un
    modèle à experts en mémoire vive (aptitude `experts_in_ram`) ; sinon un modèle qui ne tient pas sur la carte ne tient pas."""
    plafond = min(CTX_PLAFOND, modele["ctx_max"])
    sur_la_carte = None
    ctx = plafond
    while ctx >= min(CTX_PLANCHER, plafond):
        besoin = required_memory_gb(modele, ctx)
        if besoin <= budget_go:
            sur_la_carte = ctx, besoin, "gpu"
            break
        ctx //= 2
    if sur_la_carte is not None and (sur_la_carte[0] >= COMFORT_CTX or not experts_en_ram or not expert_share(modele)):
        return sur_la_carte
    if not experts_en_ram:
        return None
    # La conversation prend de la place sur la carte, qui pousse des experts en mémoire vive : la plus longue qui tient encore. Un modèle à experts qui ne
    # tiendrait sur la carte qu'avec une courte conversation y gagne : quelques experts en mémoire vive coûtent peu, une conversation de 8 192 jetons beaucoup.
    plancher = COMFORT_CTX if sur_la_carte is not None else min(CTX_PLANCHER, plafond)
    ctx = plafond
    while ctx >= plancher:
        place = experts_split(modele, ctx, budget_go, ram_libre_go)
        if place is not None:
            return ctx, place[0], "partiel"
        ctx //= 2
    return sur_la_carte


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


def choose(profil, catalogue, experts_en_ram=True):
    """{rôle: Choix ou None}. Les modèles marqués « avancés » (sans filtre) ne sont JAMAIS choisis automatiquement : ils se choisissent à la main (voir `lister`).
    `experts_en_ram` : le moteur sait garder des experts en mémoire vive (voir best_context)."""
    budget = profil.budget_go()
    cpu = profil.sans_gpu()
    ram_libre = ram_for_experts(profil)
    resultat = {}
    for role in ROLES:
        meilleur, meilleur_score = None, None
        for m in catalogue["modeles"]:
            if m.get("avance"):
                continue
            if "outils" not in m["capacites"] or m["notes"].get(role, 0) < SCORE_THRESHOLD:
                continue
            if role == "vision" and "vision" not in m["capacites"]:
                continue
            place = best_context(m, budget, ram_libre, experts_en_ram=experts_en_ram and not cpu)
            if place is None:
                continue
            ctx, besoin, tient = place
            if cpu:
                tient = "cpu"
            sc = _score(m, role, tient, budget)
            if meilleur_score is None or sc > meilleur_score:
                meilleur, meilleur_score = Choice(m, ctx, round(besoin, 1), tient, role), sc
        resultat[role] = meilleur
    return resultat


def default_choice(choix):
    """Rôles cochés au départ : Polyvalent, plus Rapide s'il est différent et léger. Les autres se choisissent à la main (un modèle = plusieurs Go)."""
    coches = []
    if choix.get("polyvalent"):
        coches.append("polyvalent")
    r = choix.get("rapide")
    if r and (not choix.get("polyvalent") or r.id != choix["polyvalent"].id) and r.modele["go"] <= SMALL_GB:
        coches.append("rapide")
    return coches


def to_download(choix, roles, deja_installes=()):
    """(liste de modèles distincts, total en Go) pour les rôles demandés, sans recompter ce qui est déjà là."""
    vus, liste, total = set(), [], 0.0
    for role in roles:
        c = choix.get(role)
        if c and c.id not in vus and c.id not in deja_installes:
            vus.add(c.id)
            liste.append(c)
            total += c.modele["go"]
    return liste, round(total, 1)


def list_models(profil, catalogue, avance=False, experts_en_ram=True):
    """Tous les modèles du catalogue avec ce qu'il en est pour cette machine (liste « Autres modèles »). Les avancés n'y figurent que si l'utilisateur a ouvert l'option."""
    budget, cpu = profil.budget_go(), profil.sans_gpu()
    ram_libre = ram_for_experts(profil)
    sortie = []
    for m in catalogue["modeles"]:
        if m.get("avance") and not avance:
            continue
        place = best_context(m, budget, ram_libre, experts_en_ram=experts_en_ram and not cpu)
        sortie.append({"modele": m, "tient": None if place is None else ("cpu" if cpu else place[2]), "memoire_go": None if place is None else round(place[1], 1)})
    return sorted(sortie, key=lambda x: (x["tient"] is None, -x["modele"]["go"]))
