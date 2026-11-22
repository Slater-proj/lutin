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

from . import storage as _d
from . import core as _m
from . import turn_runner as _turns
from . import workspaces as _trav
from .i18n import t as _t

MAX_MISSIONS = 5
DURATION_DEFAULT_H = 8
DURATION_MAX_H = 72
MAX_TURNS = 400                     # tours automatiques au plus par mission
MAX_CONSECUTIVE_ERRORS = 3
MAX_IDLE_TURNS = 3                 # réponses de suite sans aucun appel d'outil avant de demander de l'aide
PERIOD = 5
MAX_NOTEBOOK = 12000
RE_ID = re.compile(r"^[a-f0-9]{8}$")
ACTIVE_STATES = ("en_cours",)
LOCK = threading.Lock()
ALIVE = {"fil": None, "stop": threading.Event(), "arrets": {}}


# --------------------------------------------------------------------------- stockage
def path():
    return _m.DONNEES / "missions.json"


def read():
    liste = _d.read_json(path(), [])
    return [m for m in liste if isinstance(m, dict) and RE_ID.match(str(m.get("id", "")))] if isinstance(liste, list) else []


def _write(liste):
    _d.write_atomic(path(), json.dumps(liste, ensure_ascii=False, indent=1))


def find(ident):
    return next((m for m in read() if m["id"] == ident), None)


def modify(ident, **champs):
    with LOCK:
        liste = read()
        for m in liste:
            if m["id"] == ident:
                m.update(champs)
                _write(liste)
                return m
    raise ValueError(_t("Cette mission n'existe plus."))


def create(nom, cahier, travail, duree_h=DURATION_DEFAULT_H, autonome=True, conv_id=""):
    nom, cahier = " ".join(str(nom or "").split())[:60], str(cahier or "").strip()
    if not nom or not cahier:
        raise ValueError(_t("Donne un nom et le cahier des charges."))
    if len(cahier) > MAX_NOTEBOOK:
        raise ValueError(_t("Le cahier des charges est trop long ({} caractères au plus) : mets-le dans un fichier du dossier de travail et écris « lis ce fichier et réalise-le ».").format(MAX_NOTEBOOK))
    try:
        duree_h = max(1, min(DURATION_MAX_H, int(duree_h)))
    except (TypeError, ValueError):
        duree_h = DURATION_DEFAULT_H
    t = _trav.by_id(_m.config_lue(), str(travail or ""))
    if t is None:
        raise ValueError(_t("Choisis un de tes dossiers de travail (onglet Dossiers de travail)."))
    with LOCK:
        liste = read()
        if sum(1 for m in liste if m["etat"] in ("en_cours", "pause", "bloquee")) >= MAX_MISSIONS:
            raise ValueError(_t("{} missions non terminées au plus : termine ou supprime-en une.").format(MAX_MISSIONS))
        m = {"id": secrets.token_hex(4), "nom": nom, "cahier": cahier, "travail": t["id"], "dossier": t["chemin"], "duree_h": duree_h, "autonome": bool(autonome), "etat": "en_cours",
             "conv": str(conv_id or ""), "lie": bool(conv_id), "tours": 0, "debut": int(time.time()), "fin": 0, "bilan": "", "question": "", "note": "", "message": "", "erreurs": 0, "sans_action": 0, "actions": 0}
        liste.append(m)
        _write(liste)
    return m


def find_for_conversation(conv_id):
    """La dernière mission menée dans cette conversation, ou None."""
    liste = [m for m in read() if m.get("lie") and m.get("conv") == conv_id]
    return liste[-1] if liste else None


def by_conversation():
    """{conversation: résumé de sa mission} : de quoi montrer l'avancement dans la conversation elle-même."""
    sortie = {}
    for m in read():
        if m.get("lie") and m.get("conv"):
            sortie[m["conv"]] = summary(m)
    return sortie


def forget_conversation(conv_id):
    """La conversation est supprimée : sa mission aussi."""
    for m in read():
        if m.get("lie") and m.get("conv") == conv_id:
            if m["id"] in ALIVE["arrets"]:
                ALIVE["arrets"][m["id"]].set()
            with LOCK:
                _write([x for x in read() if x["id"] != m["id"]])


def notify(m, texte):
    """Le propriétaire est prévenu par Telegram (si l'addon est activé) : une mission de nuit se finit ou se bloque sans personne devant l'écran."""
    try:
        from . import addons
        if addons.actif("telegram"):
            from . import addons_telegram
            addons_telegram.notify_owners("🎯 " + m["nom"] + " — " + texte)
    except Exception as erreur:  # noqa: BLE001  (une notification ratée ne doit jamais gêner la mission)
        _m.journaliser("Mission « {} » : notification impossible ({!r}).".format(m.get("nom", "?"), erreur))


def summary(m):
    """Ce que la page voit (sans le cahier complet)."""
    return {k: m.get(k) for k in ("id", "nom", "dossier", "duree_h", "autonome", "etat", "conv", "lie", "tours", "debut", "fin", "bilan", "question", "message", "actions", "journal")} | {"cahier": (m.get("cahier") or "")[:300]}


def state():
    return {"liste": [summary(m) for m in read()]}


# --------------------------------------------------------------------------- les outils du modèle
def report(ident, nouvel_etat, texte):
    """Appelé par les outils mission_terminer / mission_bloquee."""
    if nouvel_etat == "terminee":
        m = modify(ident, etat="terminee", bilan=str(texte)[:4000], fin=int(time.time()), message="")
        notify(m, _t("terminée. {}").format(str(texte)[:300]))
    else:
        m = modify(ident, etat="bloquee", question=str(texte)[:2000], message="")
        notify(m, _t("a besoin de toi : {}").format(str(texte)[:300]))
    return _t("Noté. La mission est « {} ».").format(_t("terminée") if nouvel_etat == "terminee" else _t("en attente de ta réponse"))


INSTRUCTION = ("# MISSION LONGUE\n"
            "Tu mènes une mission de plusieurs heures, seul : l'utilisateur ne répond pas pendant que tu travailles. Procède par étapes : écris d'abord un plan dans la fiche de suivi (outil suivi), puis exécute-le étape par étape "
            "avec tes outils (écrire les fichiers, lancer les tests et les commandes, versionner avec git si le dossier est un dépôt). Vérifie ce que tu fais (relance les tests, relis le résultat) avant de passer à la suite, "
            "et mets la fiche à jour à chaque étape. Ne demande jamais de confirmation pour ce que ta mission couvre : fais-le. Reste dans le dossier de travail. "
            "Si une décision t'appartient à l'utilisateur et que tu ne peux vraiment pas la prendre à sa place, appelle mission_bloquee avec UNE question précise. "
            "Quand tout est fait ET vérifié, appelle mission_terminer avec un bilan (ce qui a été fait, comment le lancer, ce qui reste imparfait).")


def instruction_system():
    return "\n\n"  + _t(INSTRUCTION)


def turn_prompt(m):
    point = "\n\n" + _t("Termine ce tour par un court point d'avancement dans ta réponse (1 à 3 phrases : ce qui est fait, ce qui reste) : l'utilisateur te suit dans cette conversation.")
    if m["tours"] == 0:
        return _t("MISSION « {} »\n\nCahier des charges :\n{}\n\nCommence par le plan dans la fiche de suivi, puis exécute la première étape.").format(m["nom"], m["cahier"]) + point
    note = ("\n\n" + _t("Message de l'utilisateur (réponse à ta question ou nouvelle consigne) : {}").format(m["note"])) if m.get("note") else ""
    return _t("Continue la mission : relis la fiche de suivi et exécute l'étape suivante avec tes outils. Si tout est fait et vérifié, appelle mission_terminer.") + note + point


MAX_LOG = 8                     # dernières actions gardées pour la page
MESSAGE_TIMEOUT = 3.0                 # secondes entre deux mises à jour du « le modèle réfléchit… » (le fichier des missions n'est pas réécrit à chaque jeton)


def follow_turn(ident, maintenant=time.time):
    """La fonction d'émission d'un tour de mission : elle ne montre rien dans la page (personne n'y est connecté), mais tient à jour l'avancement de la mission — ce que fait le modèle EN CE MOMENT
    (il réfléchit, il écrit, il lance tel outil) et les dernières actions — pour que la bannière ne reste pas sur « tour 1 en cours… » pendant des minutes, sans qu'on sache si quelque chose se passe."""
    compte = {"pensee": 0, "texte": 0, "dernier": 0.0}

    def noter(ligne):
        try:
            actuel = find(ident)
            if actuel is None:
                return
            journal = (list(actuel.get("journal") or []) + [ligne])[-MAX_LOG:]
            modify(ident, message=ligne, journal=journal)
        except ValueError:
            pass

    def emettre(e):
        genre = e.get("type")
        if genre == "pensee":
            compte["pensee"] += len(e.get("texte") or "")
        elif genre == "texte":
            compte["texte"] += len(e.get("texte") or "")
        elif genre == "outil":
            args = ", ".join("{}={}".format(k, str(v)[:60]) for k, v in list((e.get("args") or {}).items())[:2])
            noter("⚙ {} {}".format(e.get("nom", ""), args).strip())
            compte["pensee"] = compte["texte"] = 0
            return
        elif genre == "resultat":
            noter("↳ {} : {}".format(e.get("nom", ""), " ".join(str(e.get("texte") or "").split())[:90]))
            return
        elif genre in ("info", "erreur", "etat"):
            noter(" ".join(str(e.get("texte") or "").split())[:160])
            return
        else:
            return
        t = maintenant()
        if t - compte["dernier"] >= MESSAGE_TIMEOUT:
            compte["dernier"] = t
            try:
                modify(ident, message=(_t("le modèle réfléchit… ({} caractères)").format(compte["pensee"]) if compte["pensee"] and not compte["texte"]
                                         else _t("le modèle écrit sa réponse… ({} caractères)").format(compte["texte"])))
            except ValueError:
                pass
    return emettre


# --------------------------------------------------------------------------- le fil
def _turn(m):
    """Un tour de la mission. Renvoie False sans rien faire si aucune place n'est libre ou si le dossier de travail est occupé par un autre, True si un tour a eu lieu."""
    if _turns.full():
        return False
    conv = _m.conv_read(m["conv"]) if m.get("conv") and _d.conv_exists(m["conv"]) else None
    nouvelle = conv is None
    if nouvelle:
        conv = _m.conv_new()
        conv["titre"] = "🎯 " + m["nom"]
        conv["travail"] = m["travail"]
    try:
        siege = _turns.reserve(conv, work=m["travail"], also=lambda stop: ALIVE["arrets"].__setitem__(m["id"], stop))          # une conversation où quelqu'un écrit attend (ADR 0015)
    except _turns.TurnRefused as refus:
        if nouvelle:
            _d.conv_delete(conv["id"])
        if refus.code == _turns.WORKSPACE_CONFLICT:
            modify(m["id"], message=refus.message[:200])
        return False
    stop = siege.stop
    autonome = bool(m["autonome"])
    base = _m.reglages()
    if m.get("lie"):                                                       # mission menée dans une conversation : ses options font foi (autonome = Fichiers auto ET Commandes auto cochés, relu à chaque tour)
        o = _d.options_read(m["conv"])
        autonome = bool(o.get("auto_ecriture") and o.get("auto_commandes"))
        base = _d.apply_options(base, m["conv"])
        if autonome != bool(m["autonome"]):
            modify(m["id"], autonome=autonome)
    r = dict(base, mode="technique", memoire_longue="fichier", fiche_scribe=True, auto_ecriture=autonome, auto_commandes=autonome, _mission=m["id"])
    avant = sum(1 for x in conv["messages"] if x.get("role") == "tool")
    modify(m["id"], conv=conv["id"], message=_t("tour {} en cours…").format(m["tours"] + 1))
    echec = None
    try:
        siege.run(turn_prompt(m), follow_turn(m["id"]), r, identite="mission", lecture_seule=not autonome)
    except Exception as erreur:  # noqa: BLE001
        echec = erreur
        _m.journaliser("Mission « {} » : tour en erreur : {!r}".format(m["nom"], erreur))
    finally:
        siege.release()
        ALIVE["arrets"].pop(m["id"], None)
    actuel = find(m["id"])
    if actuel is None:
        return True
    try:
        apres = _m.conv_read(conv["id"])
        faits = sum(1 for x in apres["messages"] if x.get("role") == "tool") - avant
    except (ValueError, OSError):
        faits = 0
    champs = {"tours": actuel["tours"] + 1, "actions": actuel.get("actions", 0) + max(0, faits), "message": ""}
    if actuel.get("note") == m.get("note"):
        champs["note"] = ""                                            # la consigne a été donnée à ce tour ; une consigne arrivée pendant le tour attend le suivant
    if actuel["etat"] == "en_cours" and stop.is_set():                 # l'utilisateur a cliqué sur Arrêter pendant ce tour : la mission se met en pause (écrire « continue » ou cliquer sur Reprendre la relance)
        champs.update(etat="pause", message=_t("Arrêtée par toi. Écris « continue » ou clique sur Reprendre."))
    elif actuel["etat"] == "en_cours":                                 # le modèle n'a pas conclu, l'utilisateur n'a pas mis en pause
        if echec is not None:
            champs["erreurs"] = actuel.get("erreurs", 0) + 1
            champs["message"] = str(echec)[:200]
            if champs["erreurs"] >= MAX_CONSECUTIVE_ERRORS:
                champs.update(etat="pause", message=_t("En pause après {} erreurs de suite : {}").format(MAX_CONSECUTIVE_ERRORS, str(echec)[:160]))
                notify(actuel, _t("en pause après des erreurs : {}").format(str(echec)[:200]))
        else:
            champs["erreurs"] = 0
            champs["sans_action"] = 0 if faits > 0 else actuel.get("sans_action", 0) + 1
            if champs["sans_action"] >= MAX_IDLE_TURNS:
                champs.update(etat="bloquee", question=_t("Je n'avance plus : {} réponses de suite sans aucune action. Que dois-je faire ?").format(MAX_IDLE_TURNS), sans_action=0)
                notify(actuel, _t("n'avance plus et a besoin de toi."))
    modify(m["id"], **champs)
    return True


def one_step():
    """Fait avancer la première mission en cours d'un tour. Renvoie True si un tour a eu lieu."""
    for m in read():
        if m["etat"] != "en_cours":
            continue
        if time.time() - m["debut"] > m["duree_h"] * 3600 or m["tours"] >= MAX_TURNS:
            fini = modify(m["id"], etat="terminee", fin=int(time.time()), bilan=m.get("bilan") or _t("Arrêtée : la durée ou le nombre de tours maximal est atteint. Le travail déjà fait est dans le dossier ; relis la conversation « 🎯 » pour l'état exact."))
            notify(fini, _t("arrêtée : la durée ou le nombre de tours maximal est atteint."))
            continue
        if _turn(m):
            return True
        if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
            return False                                                    # plus de place pour personne : la boucle attend au lieu de tourner à vide
    return False                                                            # (un dossier occupé n'empêche pas d'essayer la mission suivante)


def loop():
    while not ALIVE["stop"].is_set():
        try:
            if not one_step():
                ALIVE["stop"].wait(PERIOD)
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Missions : {!r}".format(erreur))
            ALIVE["stop"].wait(PERIOD)


def start():
    if ALIVE["fil"] and ALIVE["fil"].is_alive():
        return
    ALIVE["stop"].clear()
    ALIVE["fil"] = threading.Thread(target=loop, daemon=True, name="missions")
    ALIVE["fil"].start()


def stop_mission():
    ALIVE["stop"].set()
    for e in list(ALIVE["arrets"].values()):
        e.set()


# --------------------------------------------------------------------------- les actions du panneau
def action(nom, donnees):
    ident = str(donnees.get("id", ""))
    if nom == "creer":
        return summary(create(donnees.get("nom"), donnees.get("cahier"), donnees.get("travail"), donnees.get("duree_h", DURATION_DEFAULT_H), donnees.get("autonome", True)))
    m = find(ident)
    if m is None:
        raise ValueError(_t("Cette mission n'existe plus."))
    if nom == "pause":
        modify(ident, etat="pause", message="")
        if ident in ALIVE["arrets"]:
            ALIVE["arrets"][ident].set()                                # le tour en cours s'arrête ; la mission reprendra à la reprise
    elif nom == "reprendre":
        modify(ident, etat="en_cours", erreurs=0, sans_action=0, message="")
    elif nom == "repondre":                                              # répondre à une question, ou ajouter une consigne en cours de route
        texte = " ".join(str(donnees.get("texte", "")).split())[:2000]
        if not texte:
            raise ValueError(_t("Écris ta réponse ou ta consigne."))
        modify(ident, note=texte, question="", **({"etat": "en_cours"} if m["etat"] in ("bloquee", "pause") else {}))
    elif nom == "arreter":
        modify(ident, etat="terminee", fin=int(time.time()), bilan=m.get("bilan") or _t("Arrêtée par toi."))
        if ident in ALIVE["arrets"]:
            ALIVE["arrets"][ident].set()
    elif nom == "supprimer":
        if ident in ALIVE["arrets"]:
            ALIVE["arrets"][ident].set()
        with LOCK:
            _write([x for x in read() if x["id"] != ident])            # la conversation « 🎯 » reste dans la liste : elle est à toi
    else:
        raise ValueError(_t("Action inconnue."))
    return state()
