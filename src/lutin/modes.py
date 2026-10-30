"""Les modes de Lutin : ce que le réglage « Mode » change, au même endroit.

Un mode décide trois choses : les outils que le modèle reçoit (lire, chercher, modifier, lancer une commande…), la consigne qui lui dit comment se comporter, et si les rappels automatiques
(passages de tes documents et de tes anciennes conversations ajoutés au prompt) sont proposés par défaut. Les accords restent les mêmes dans tous les modes : toute modification de fichier ou toute
commande demande ton accord, sauf si tu as coché l'accord automatique."""
from .i18n import t as _t

DEFAUT = "polyvalent"

LECTURE = {"lister", "lire", "chercher", "symboles", "lire_plusieurs", "rappeler", "web_chercher", "web_lire", "taches", "memoriser", "suivi", "comfy_modeles"}
IMAGES = {"etat_outil", "installer_module"}          # l'extension facultative d'images

# identifiant -> ce qui change : `exclus` (outils retirés), `seulement` (seuls ces outils restent), `aucun` (aucun outil), `rappels` (rappels automatiques proposés par défaut)
MODES = {
    "polyvalent": {"exclus": {"symboles"} | IMAGES, "rappels": False},
    "technique": {"exclus": set(), "rappels": False},
    "scenario": {"exclus": {"executer", "symboles"} | IMAGES, "rappels": True},
    "recherche": {"seulement": LECTURE, "rappels": True},
    "discussion": {"aucun": True, "rappels": False},
}


def ids():
    return tuple(MODES)


def valide(mode):
    return mode in MODES


def outils_exclus(mode, tous):
    """Les noms d'outils à retirer pour ce mode, parmi `tous` (les noms de tous les outils)."""
    m = MODES.get(mode) or MODES[DEFAUT]
    if m.get("aucun"):
        return set(tous)
    if "seulement" in m:
        return set(tous) - m["seulement"]
    return set(m["exclus"])


def rappels_par_defaut(mode):
    """Vrai si les rappels automatiques sont proposés dans ce mode quand le réglage dit « modes d'écriture et de recherche »."""
    return bool((MODES.get(mode) or {}).get("rappels"))


def consigne(mode):
    """Le paragraphe du prompt qui dit au modèle dans quel mode il travaille."""
    if mode == "technique":
        return _t("Mode TRAVAIL : tu aides à comprendre, modifier et tester les fichiers du dossier de travail. Lis avant de modifier, fais de petits changements, lance les tests après s'il y en a, et dis clairement ce qui est vérifié ou non.")
    if mode == "scenario":
        return _t("Mode ÉCRITURE : tu aides à rédiger, à reformuler et à chercher dans les documents du dossier de travail. Tu ne lances pas de commandes. Sois inventif et précis, fidèle aux documents de l'utilisateur.")
    if mode == "recherche":
        return _t("Mode RECHERCHE (lecture seule) : tu lis, cherches et recoupes les fichiers, les documents (PDF, Word…), les notes et les anciennes conversations, puis tu réponds en citant tes sources (fichier, page). Tu ne modifies aucun fichier et tu ne lances aucune commande : si une modification serait utile, propose-la sans la faire.")
    if mode == "discussion":
        return _t("Mode DISCUSSION : tu converses sans outils. Réponds directement et simplement ; si l'utilisateur veut que tu lises ou modifies des fichiers, dis-lui de passer dans un autre mode.")
    return _t("Mode POLYVALENT : tu es un assistant généraliste. Tu réponds aux questions, tu aides à rédiger, à analyser, à programmer et à organiser. Quand une question touche aux fichiers du dossier de travail, lis-les avant de répondre ; ne modifie rien sans nécessité, et dis clairement ce qui est vérifié ou non.")
