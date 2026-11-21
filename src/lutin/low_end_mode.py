"""Le mode « petite machine » : des réglages adaptés à une machine sans carte graphique ou à peu de mémoire, proposés d'un clic (jamais imposés).

Sur processeur, relire une grande fenêtre de contexte à chaque réponse prend des minutes, et la réflexion d'un modèle ajoute des centaines de mots avant chaque réponse : les deux réglages par défaut,
pensés pour une carte graphique, rendent une petite machine lente sans que rien ne dise pourquoi. Ce module compare les réglages actuels à ce qui convient à la machine et propose de les changer."""
from .i18n import t as _t

SMALL_MACHINE_CTX = 12288          # jetons : assez pour une conversation de travail, sans que chaque réponse relise des dizaines de milliers de jetons
SMALL_BUDGET_GB = 10                # en dessous, même avec une carte, la place pour le contexte est comptée


def is_small(profil):
    """Vrai pour une machine sans carte graphique utilisable, ou dont la mémoire utilisable est petite."""
    if profil is None:
        return False
    return bool(profil.sans_gpu() or profil.budget_go() <= SMALL_BUDGET_GB)


def advice(profil, reglages):
    """La liste des changements conseillés : [{cle, actuel, conseille, texte}]. Vide si la machine n'est pas « petite » ou si les réglages conviennent déjà."""
    if not is_small(profil):
        return []
    liste = []
    if int(reglages.get("num_ctx") or 0) > SMALL_MACHINE_CTX:
        liste.append({"cle": "num_ctx", "actuel": int(reglages["num_ctx"]), "conseille": SMALL_MACHINE_CTX,
                      "texte": _t("Fenêtre de contexte : {} → {} jetons. Sur cette machine, chaque réponse relit toute la conversation ; une fenêtre plus petite répond bien plus vite.").format(int(reglages["num_ctx"]), SMALL_MACHINE_CTX)})
    if reglages.get("reflexion"):
        liste.append({"cle": "reflexion", "actuel": True, "conseille": False,
                      "texte": _t("Réflexion : activée → coupée par défaut. La réflexion ajoute de longs paragraphes avant chaque réponse ; tu peux la rallumer conversation par conversation.")})
    return liste


def apply(profil, reglages):
    """Les réglages à enregistrer pour suivre les conseils (dictionnaire vide s'il n'y a rien à changer)."""
    return {c["cle"]: c["conseille"] for c in advice(profil, reglages)}
