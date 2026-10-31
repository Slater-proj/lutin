"""Missions longues : un grand travail confié à Lutin pour des heures (« crée-moi un jeu vidéo complet à partir de ce cahier des charges : code, tests, dépôt »), sans qu'il revienne vers toi.

Ce n'est ni une tâche planifiée (une demande à heure fixe, en lecture seule) ni le traitement de documents en série : c'est une vraie conversation de travail que Lutin poursuit tout seul, tour après tour, avec TOUS ses
outils (lire, écrire, lancer des commandes, tests, git), jusqu'à ce que le modèle déclare la mission terminée ou qu'une limite l'arrête. Le cahier des charges est ta demande, rien de plus : la mission dépend de ce que tu écris.

Pour tenir des heures sans perdre le fil : la fiche de suivi est forcée (objectif, plan, étape en cours, fait), le scribe la tient à jour, le début de la conversation est archivé et retrouvable, le détecteur de boucle veille.

Règles de solidité :
- tu choisis l'autonomie à la création : « autonome » (écritures et commandes acceptées sans te demander, dans le dossier de travail choisi et avec les garde-fous habituels : sauvegarde des fichiers modifiés, commandes
  bornées) ou « à blanc » (rien n'est écrit ni lancé, le modèle montre ce qu'il ferait) ;
- limites : durée maximale (8 h par défaut), nombre de tours, arrêt après des erreurs de suite ou trois réponses de suite sans aucune action ;
- le modèle peut s'arrêter lui-même : `mission_terminer` (bilan) ou `mission_bloquee` (une question pour toi : la mission attend ta réponse) ;
- reprise : l'état est écrit après chaque tour ; si Lutin ou le PC s'arrête, la mission reprend là où elle en était ;
- tu gardes la main : pause, reprise, arrêt, consigne ajoutée en cours de route ; la conversation « 🎯 nom » se lit et se continue comme les autres ;
- une mission ne démarre un tour que si une place de réponse est libre (tu peux continuer à discuter) et dans SON dossier de travail."""
import json
import re
import secrets
import threading
import time

from . import donnees as _d
from . import moteur as _m
from . import travaux as _trav
from .i18n import t as _t

MAX_MISSIONS = 5
DUREE_DEFAUT_H = 8
DUREE_MAX_H = 72
TOURS_MAX = 400                     # tours automatiques au plus par mission
ERREURS_DE_SUITE = 3
SANS_ACTION_MAX = 3                 # réponses de suite sans aucun appel d'outil avant de demander de l'aide
PERIODE = 5
CAHIER_MAX = 12000
RE_ID = re.compile(r"^[a-f0-9]{8}$")
ETATS_ACTIFS = ("en_cours",)
VERROU = threading.Lock()
VIVANT = {"fil": None, "stop": threading.Event(), "arrets": {}}


# --------------------------------------------------------------------------- stockage
def chemin():
    return _m.DONNEES / "missions.json"


def lire():
    liste = _d.lire_json(chemin(), [])
    return [m for m in liste if isinstance(m, dict) and RE_ID.match(str(m.get("id", "")))] if isinstance(liste, list) else []


def _ecrire(liste):
    _d.ecrire_atomique(chemin(), json.dumps(liste, ensure_ascii=False, indent=1))


def trouver(ident):
    return next((m for m in lire() if m["id"] == ident), None)


def modifier(ident, **champs):
    with VERROU:
        liste = lire()
        for m in liste:
            if m["id"] == ident:
                m.update(champs)
                _ecrire(liste)
                return m
    raise ValueError(_t("Cette mission n'existe plus."))


def creer(nom, cahier, travail, duree_h=DUREE_DEFAUT_H, autonome=True):
    nom, cahier = " ".join(str(nom or "").split())[:60], str(cahier or "").strip()
    if not nom or not cahier:
        raise ValueError(_t("Donne un nom et le cahier des charges."))
    if len(cahier) > CAHIER_MAX:
        raise ValueError(_t("Le cahier des charges est trop long ({} caractères au plus) : mets-le dans un fichier du dossier de travail et écris « lis ce fichier et réalise-le ».").format(CAHIER_MAX))
    try:
        duree_h = max(1, min(DUREE_MAX_H, int(duree_h)))
    except (TypeError, ValueError):
        duree_h = DUREE_DEFAUT_H
    t = _trav.par_id(_m.config_lue(), str(travail or ""))
    if t is None:
        raise ValueError(_t("Choisis un de tes dossiers de travail (onglet Dossiers de travail)."))
    with VERROU:
        liste = lire()
        if sum(1 for m in liste if m["etat"] in ("en_cours", "pause", "bloquee")) >= MAX_MISSIONS:
            raise ValueError(_t("{} missions non terminées au plus : termine ou supprime-en une.").format(MAX_MISSIONS))
        m = {"id": secrets.token_hex(4), "nom": nom, "cahier": cahier, "travail": t["id"], "dossier": t["chemin"], "duree_h": duree_h, "autonome": bool(autonome), "etat": "en_cours",
             "conv": "", "tours": 0, "debut": int(time.time()), "fin": 0, "bilan": "", "question": "", "note": "", "message": "", "erreurs": 0, "sans_action": 0, "actions": 0}
        liste.append(m)
        _ecrire(liste)
    return m


def resume(m):
    """Ce que la page voit (sans le cahier complet)."""
    return {k: m.get(k) for k in ("id", "nom", "dossier", "duree_h", "autonome", "etat", "conv", "tours", "debut", "fin", "bilan", "question", "message", "actions")} | {"cahier": (m.get("cahier") or "")[:300]}


def etat():
    return {"liste": [resume(m) for m in lire()]}


# --------------------------------------------------------------------------- les outils du modèle
def signaler(ident, nouvel_etat, texte):
    """Appelé par les outils mission_terminer / mission_bloquee."""
    if nouvel_etat == "terminee":
        modifier(ident, etat="terminee", bilan=str(texte)[:4000], fin=int(time.time()), message="")
    else:
        modifier(ident, etat="bloquee", question=str(texte)[:2000], message="")
    return _t("Noté. La mission est « {} ».").format(_t("terminée") if nouvel_etat == "terminee" else _t("en attente de ta réponse"))


CONSIGNE = ("# MISSION LONGUE\n"
            "Tu mènes une mission de plusieurs heures, seul : l'utilisateur ne répond pas pendant que tu travailles. Procède par étapes : écris d'abord un plan dans la fiche de suivi (outil suivi), puis exécute-le étape par étape "
            "avec tes outils (écrire les fichiers, lancer les tests et les commandes, versionner avec git si le dossier est un dépôt). Vérifie ce que tu fais (relance les tests, relis le résultat) avant de passer à la suite, "
            "et mets la fiche à jour à chaque étape. Ne demande jamais de confirmation pour ce que ta mission couvre : fais-le. Reste dans le dossier de travail. "
            "Si une décision t'appartient à l'utilisateur et que tu ne peux vraiment pas la prendre à sa place, appelle mission_bloquee avec UNE question précise. "
            "Quand tout est fait ET vérifié, appelle mission_terminer avec un bilan (ce qui a été fait, comment le lancer, ce qui reste imparfait).")


def consigne_systeme():
    return "\n\n"  + _t(CONSIGNE)


def prompt_du_tour(m):
    if m["tours"] == 0:
        return _t("MISSION « {} »\n\nCahier des charges :\n{}\n\nCommence par le plan dans la fiche de suivi, puis exécute la première étape.").format(m["nom"], m["cahier"])
    note = ("\n\n" + _t("Message de l'utilisateur (réponse à ta question ou nouvelle consigne) : {}").format(m["note"])) if m.get("note") else ""
    return _t("Continue la mission : relis la fiche de suivi et exécute l'étape suivante avec tes outils. Si tout est fait et vérifié, appelle mission_terminer.") + note


# --------------------------------------------------------------------------- le fil
def _tour(m):
    """Un tour de la mission. Renvoie sans rien faire si aucune place n'est libre ou si le dossier de travail est occupé par un autre."""
    stop = threading.Event()
    with _m.VERROU_TOURS:
        if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
            return
        conv = _m.conv_lire(m["conv"]) if m.get("conv") and _d.conv_chemin(m["conv"]).exists() else None
        nouvelle = conv is None
        if nouvelle:
            conv = _m.conv_nouvelle()
            conv["titre"] = "🎯 " + m["nom"]
            conv["travail"] = m["travail"]
        try:
            _m.activer_travail(conv, m["travail"])
        except ValueError as erreur:
            if nouvelle:
                _d.conv_chemin(conv["id"]).unlink(missing_ok=True)
            modifier(m["id"], message=str(erreur)[:200])
            return
        _m.RACINE_TOURS[conv["id"]] = str(_m.RACINE)
        _m.TOURS_ACTIFS[conv["id"]] = stop
        VIVANT["arrets"][m["id"]] = stop
    r = dict(_m.reglages(), mode="technique", memoire_longue="fichier", fiche_scribe=True, auto_ecriture=bool(m["autonome"]), auto_commandes=bool(m["autonome"]), _mission=m["id"])
    avant = sum(1 for x in conv["messages"] if x.get("role") == "tool")
    modifier(m["id"], conv=conv["id"], message=_t("tour {} en cours…").format(m["tours"] + 1))
    echec = None
    try:
        _m.tour(conv, prompt_du_tour(m), lambda evenement: None, r, stop, None, identite="mission", lecture_seule=not m["autonome"])
    except Exception as erreur:  # noqa: BLE001
        echec = erreur
        _m.journaliser("Mission « {} » : tour en erreur : {!r}".format(m["nom"], erreur))
    finally:
        with _m.VERROU_TOURS:
            _m.TOURS_ACTIFS.pop(conv["id"], None)
            _m.RACINE_TOURS.pop(conv["id"], None)
        VIVANT["arrets"].pop(m["id"], None)
    actuel = trouver(m["id"])
    if actuel is None:
        return
    try:
        apres = _m.conv_lire(conv["id"])
        faits = sum(1 for x in apres["messages"] if x.get("role") == "tool") - avant
    except (ValueError, OSError):
        faits = 0
    champs = {"tours": actuel["tours"] + 1, "actions": actuel.get("actions", 0) + max(0, faits), "message": ""}
    if actuel.get("note") == m.get("note"):
        champs["note"] = ""                                            # la consigne a été donnée à ce tour ; une consigne arrivée pendant le tour attend le suivant
    if actuel["etat"] == "en_cours":                                   # le modèle n'a pas conclu, l'utilisateur n'a pas mis en pause
        if echec is not None:
            champs["erreurs"] = actuel.get("erreurs", 0) + 1
            champs["message"] = str(echec)[:200]
            if champs["erreurs"] >= ERREURS_DE_SUITE:
                champs.update(etat="pause", message=_t("En pause après {} erreurs de suite : {}").format(ERREURS_DE_SUITE, str(echec)[:160]))
        else:
            champs["erreurs"] = 0
            champs["sans_action"] = 0 if faits > 0 else actuel.get("sans_action", 0) + 1
            if champs["sans_action"] >= SANS_ACTION_MAX:
                champs.update(etat="bloquee", question=_t("Je n'avance plus : {} réponses de suite sans aucune action. Que dois-je faire ?").format(SANS_ACTION_MAX), sans_action=0)
    modifier(m["id"], **champs)


def un_pas():
    """Fait avancer la première mission en cours d'un tour. Renvoie True si un tour a eu lieu."""
    for m in lire():
        if m["etat"] != "en_cours":
            continue
        if time.time() - m["debut"] > m["duree_h"] * 3600 or m["tours"] >= TOURS_MAX:
            modifier(m["id"], etat="terminee", fin=int(time.time()), bilan=m.get("bilan") or _t("Arrêtée : la durée ou le nombre de tours maximal est atteint. Le travail déjà fait est dans le dossier ; relis la conversation « 🎯 » pour l'état exact."))
            continue
        _tour(m)
        return True
    return False


def boucle():
    while not VIVANT["stop"].is_set():
        try:
            if not un_pas():
                VIVANT["stop"].wait(PERIODE)
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Missions : {!r}".format(erreur))
            VIVANT["stop"].wait(PERIODE)


def demarrer():
    if VIVANT["fil"] and VIVANT["fil"].is_alive():
        return
    VIVANT["stop"].clear()
    VIVANT["fil"] = threading.Thread(target=boucle, daemon=True, name="missions")
    VIVANT["fil"].start()


def arreter():
    VIVANT["stop"].set()
    for e in list(VIVANT["arrets"].values()):
        e.set()


# --------------------------------------------------------------------------- les actions du panneau
def action(nom, donnees):
    ident = str(donnees.get("id", ""))
    if nom == "creer":
        return resume(creer(donnees.get("nom"), donnees.get("cahier"), donnees.get("travail"), donnees.get("duree_h", DUREE_DEFAUT_H), donnees.get("autonome", True)))
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Cette mission n'existe plus."))
    if nom == "pause":
        modifier(ident, etat="pause", message="")
        if ident in VIVANT["arrets"]:
            VIVANT["arrets"][ident].set()                                # le tour en cours s'arrête ; la mission reprendra à la reprise
    elif nom == "reprendre":
        modifier(ident, etat="en_cours", erreurs=0, sans_action=0, message="")
    elif nom == "repondre":                                              # répondre à une question, ou ajouter une consigne en cours de route
        texte = " ".join(str(donnees.get("texte", "")).split())[:2000]
        if not texte:
            raise ValueError(_t("Écris ta réponse ou ta consigne."))
        modifier(ident, note=texte, question="", **({"etat": "en_cours"} if m["etat"] in ("bloquee", "pause") else {}))
    elif nom == "arreter":
        modifier(ident, etat="terminee", fin=int(time.time()), bilan=m.get("bilan") or _t("Arrêtée par toi."))
        if ident in VIVANT["arrets"]:
            VIVANT["arrets"][ident].set()
    elif nom == "supprimer":
        if ident in VIVANT["arrets"]:
            VIVANT["arrets"][ident].set()
        with VERROU:
            _ecrire([x for x in lire() if x["id"] != ident])            # la conversation « 🎯 » reste dans la liste : elle est à toi
    else:
        raise ValueError(_t("Action inconnue."))
    return etat()
