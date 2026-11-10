"""Tâches planifiées : une demande que Lutin traite tout seul à heure fixe (« chaque matin, résume les changements du dépôt »).

Personne n'est là pour accepter quoi que ce soit : la tâche tourne en lecture seule, comme dans l'essai à blanc (lecture et recherche réelles, tout le reste simulé).
Le résultat est UNE conversation « ⏰ nom » par tâche, à retrouver dans la liste : chaque exécution y ajoute sa demande (datée) et sa réponse. Un problème (moteur absent, mémoire pleine…) y est écrit, jamais passé sous silence.
Un canal de notification (Gotify, ntfy, Telegram, webhook : voir notifications.py) peut être associé à une tâche : le résultat y est envoyé quand elle a fini. Une tâche ne démarre que si aucune réponse n'est en cours (une seule carte graphique).

Une tâche revient chaque semaine aux jours choisis, ou n'a lieu qu'UNE fois à une date donnée (elle se met alors en pause toute seule). On peut la modifier, l'arrêter pendant qu'elle travaille, la supprimer (avec ou sans sa conversation) :
supprimer une tâche en cours l'arrête. Chaque exécution est notée (les dix dernières), y compris celles qui n'ont pas pu démarrer : rien n'échoue en silence."""
import re
import secrets
import threading
import time
from datetime import datetime

from . import donnees as _d
from .i18n import t as _t
from . import moteur as _m

MAX_TACHES = 20
HISTORIQUE_MAX = 10
RE_HEURE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
EN_COURS = {}            # id de tâche -> évènement d'arrêt, tant qu'elle travaille
A_SUPPRIMER = set()      # conversations de tâches supprimées pendant qu'elles travaillaient : effacées quand le tour se termine (sinon il les réécrirait)
VERROU = threading.Lock()
PERIODE = 30            # secondes entre deux regards sur l'horloge


def chemin():
    return _m.DONNEES / "planifie.json"


def lire():
    liste = _d.lire_json(chemin(), [])
    return [t for t in liste if isinstance(t, dict) and t.get("id")] if isinstance(liste, list) else []


def _ecrire(liste):
    import json
    _d.ecrire_atomique(chemin(), json.dumps(liste, ensure_ascii=False, indent=1))


class Impossible(Exception):
    """Une tâche qui ne peut pas démarrer (son dossier de travail a disparu…) : ce n'est pas « la machine est occupée », il ne faut pas réessayer toutes les 30 secondes."""


def _valider(nom, prompt, heure, jours, travail, notifier, date, maintenant=None):
    nom, prompt = " ".join(str(nom or "").split())[:60], str(prompt or "").strip()
    if not nom or not prompt:
        raise ValueError(_t("Donne un nom et la demande à traiter."))
    if len(prompt) > 4000:
        raise ValueError(_t("La demande est trop longue (4 000 caractères au plus)."))
    if not RE_HEURE.match(str(heure or "")):
        raise ValueError(_t("L'heure doit être au format HH:MM (par exemple 08:30)."))
    maintenant = maintenant or datetime.now()
    date = str(date or "").strip()
    if date:
        try:
            jour = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(_t("La date doit être au format AAAA-MM-JJ."))
        h, m = (int(x) for x in heure.split(":"))
        if jour.replace(hour=h, minute=m) <= maintenant:
            raise ValueError(_t("Cette date et cette heure sont déjà passées."))
        jours = [jour.weekday()]
    else:
        try:
            jours = sorted({int(j) for j in (jours or [])})
        except (TypeError, ValueError):
            jours = []
        if not jours or any(j < 0 or j > 6 for j in jours):
            raise ValueError(_t("Choisis au moins un jour de la semaine."))
    notifier = str(notifier or "")
    if notifier:
        from . import notifications
        if notifications.trouver(notifier) is None:
            raise ValueError(_t("Ce canal de notification n'existe plus."))
    return {"nom": nom, "prompt": prompt, "heure": heure, "jours": jours, "date": date, "travail": str(travail or "")[:80], "notifier": notifier}


def ajouter(nom, prompt, heure, jours, travail="", notifier="", date=""):
    champs = _valider(nom, prompt, heure, jours, travail, notifier, date)
    with VERROU:
        liste = lire()
        if len(liste) >= MAX_TACHES:
            raise ValueError(_t("Déjà {} tâches planifiées : supprime-en une d'abord.").format(MAX_TACHES))
        tache = dict(champs, id=secrets.token_hex(4), derniere_notif="", actif=True, cree=datetime.now().isoformat(timespec="seconds"), derniere_exec="", derniere_conv="", derniere_etat="", derniere_erreur="", historique=[])
        liste.append(tache)
        _ecrire(liste)
    return tache


def changer(ident, nom, prompt, heure, jours, travail="", notifier="", date=""):
    """Modifie une tâche (tout ce qu'on peut régler à la création). Si le moment change, la tâche repart de maintenant : elle ne « rattrape » pas une heure qui vient de passer."""
    champs = _valider(nom, prompt, heure, jours, travail, notifier, date)
    with VERROU:
        liste = lire()
        for t in liste:
            if t["id"] == ident:
                moment_change = (t.get("heure"), t.get("jours"), t.get("date", "")) != (champs["heure"], champs["jours"], champs["date"])
                t.update(champs)
                if moment_change:
                    t["cree"] = datetime.now().isoformat(timespec="seconds")
                    t["actif"] = True
                _ecrire(liste)
                return t
    raise ValueError(_t("Cette tâche planifiée n'existe plus."))


def modifier(ident, **champs):
    with VERROU:
        liste = lire()
        for t in liste:
            if t["id"] == ident:
                t.update(champs)
                _ecrire(liste)
                return t
    raise ValueError(_t("Cette tâche planifiée n'existe plus."))


def definir_notification(ident, canal):
    """Associe (ou retire, canal vide) le canal de notification d'une tâche."""
    canal = str(canal or "")
    if canal:
        from . import notifications
        if notifications.trouver(canal) is None:
            raise ValueError(_t("Ce canal de notification n'existe plus."))
    return modifier(ident, notifier=canal, derniere_notif="")


def supprimer(ident, conversation=False):
    """Supprime la tâche pour de bon (elle ne se relancera plus). Si elle travaille en ce moment, elle est arrêtée. `conversation` : efface aussi sa conversation « ⏰ … » (par défaut elle est gardée)."""
    with VERROU:
        liste = lire()
        tache = next((t for t in liste if t["id"] == ident), None)
        if tache is None:
            raise ValueError(_t("Cette tâche planifiée n'existe plus."))
        _ecrire([t for t in liste if t["id"] != ident])
    arret = EN_COURS.get(ident)
    if arret is not None:
        arret.set()
    conv = tache.get("derniere_conv")
    if conversation and conv:
        if arret is not None:
            A_SUPPRIMER.add(conv)
        else:
            _m.conv_supprimer(conv)
    _m.journaliser("Tâche planifiée « {} » supprimée{}.".format(tache.get("nom", ""), " (et sa conversation)" if conversation and conv else ""))
    return {"ok": True}


def arreter(ident):
    """Arrête la tâche pendant qu'elle travaille (elle reste planifiée pour la prochaine fois)."""
    arret = EN_COURS.get(ident)
    if arret is None:
        raise ValueError(_t("Cette tâche ne travaille pas en ce moment."))
    arret.set()
    return {"ok": True}


def echeance(tache, maintenant):
    """Date de la dernière occurrence prévue (aujourd'hui à l'heure dite) si elle est passée et pas encore traitée, sinon None.
    Une tâche créée après l'heure du jour attend le lendemain ; un PC éteint à l'heure dite la rattrape au démarrage, le jour même seulement."""
    if not tache.get("actif"):
        return None
    if tache.get("date"):
        if maintenant.date().isoformat() != tache["date"]:
            return None
    elif maintenant.weekday() not in tache.get("jours", []):
        return None
    h, m = (int(x) for x in tache["heure"].split(":"))
    prevue = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    if maintenant < prevue:
        return None
    for date in (tache.get("cree"), tache.get("derniere_exec")):
        if date and datetime.fromisoformat(date) >= prevue:
            return None
    return prevue


def prochaine(tache, maintenant):
    """Texte ISO de la prochaine exécution prévue, pour l'affichage."""
    if not tache.get("actif"):
        return ""
    from datetime import timedelta
    h, m = (int(x) for x in tache["heure"].split(":"))
    if tache.get("date"):
        jour = datetime.strptime(tache["date"], "%Y-%m-%d").replace(hour=h, minute=m)
        return jour.isoformat(timespec="minutes") if jour > maintenant or echeance(tache, maintenant) else ""
    for plus in range(0, 8):
        jour = (maintenant + timedelta(days=plus)).replace(hour=h, minute=m, second=0, microsecond=0)
        if jour.weekday() in tache["jours"] and (jour > maintenant or (plus == 0 and echeance(tache, maintenant))):
            return jour.isoformat(timespec="minutes")
    return ""


def etat():
    maintenant = datetime.now()
    taches = []
    for t in lire():
        etat_t = t.get("derniere_etat", "")
        if etat_t == "en_cours" and t["id"] not in EN_COURS:
            etat_t = "interrompue"          # Lutin s'est arrêté pendant qu'elle travaillait
        taches.append(dict(t, derniere_etat=etat_t, prochaine=prochaine(t, maintenant), en_cours=t["id"] in EN_COURS))
    return {"taches": taches}


def _conversation(tache):
    """(conversation, neuve) : toujours la MÊME conversation pour une tâche (créée à la première exécution), au lieu d'en ouvrir une nouvelle à chaque fois."""
    if tache.get("derniere_conv"):
        try:
            return _m.conv_lire(tache["derniere_conv"]), False
        except (OSError, ValueError):
            pass
    conv = _m.conv_nouvelle()
    conv["titre"] = "⏰ " + tache["nom"]
    return conv, True


def _derniere_reponse(conv):
    for m in reversed(conv.get("messages", [])):
        if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip():
            return m["content"].strip()
        if m.get("role") == "user":
            break
    return ""


def _noter(ident, **champs):
    """Met à jour une tâche sans jamais échouer si elle a été supprimée entre-temps. Vrai si elle existe encore."""
    try:
        modifier(ident, **champs)
        return True
    except ValueError:
        return False


def _historiser(ident, etat_final, debut, erreur=""):
    """Ajoute cette exécution aux dix dernières (date, résultat, durée, erreur) de la tâche."""
    with VERROU:
        liste = lire()
        for t in liste:
            if t["id"] == ident:
                entree = {"date": debut.isoformat(timespec="seconds"), "etat": etat_final, "duree_s": int((datetime.now() - debut).total_seconds()), "erreur": str(erreur)[:300]}
                t["historique"] = ([entree] + list(t.get("historique") or []))[:HISTORIQUE_MAX]
                _ecrire(liste)
                return


def _echec_demarrage(tache, texte):
    """La tâche n'a pas pu démarrer (dossier de travail disparu…) : c'est écrit sur la tâche, dans le journal et dans la notification, et elle n'est pas relancée toutes les 30 secondes."""
    debut = datetime.now()
    _m.journaliser("Tâche planifiée « {} » : impossible de démarrer ({}).".format(tache["nom"], texte[:200]))
    if _noter(tache["id"], derniere_exec=debut.isoformat(timespec="seconds"), derniere_etat="erreur", derniere_erreur=texte[:300]):
        _historiser(tache["id"], "erreur", debut, texte)
        _notifier(tache, "erreur", "⚠ " + texte)


def executer(ident):
    """Traite une tâche maintenant. Renvoie l'identifiant de SA conversation (la même à chaque exécution), ou lève ValueError si la machine est déjà occupée ou si la tâche travaille déjà.
    Une tâche qui ne peut pas démarrer (dossier de travail disparu) l'écrit sur elle-même et renvoie ''."""
    tache = next((t for t in lire() if t["id"] == ident), None)
    if tache is None:
        raise ValueError(_t("Cette tâche planifiée n'existe plus."))
    stop = threading.Event()
    try:
        with _m.VERROU_TOURS:
            if ident in EN_COURS:
                raise ValueError(_t("Cette tâche travaille déjà."))
            if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
                raise ValueError(_t("Une réponse est déjà en cours : la tâche attend."))
            conv, neuve = _conversation(tache)
            if neuve:
                try:
                    _m.activer_travail(conv, tache.get("travail", ""))
                except ValueError as erreur:
                    _d.conv_chemin(conv["id"]).unlink(missing_ok=True)
                    raise Impossible(str(erreur))
            _m.RACINE_TOURS[conv["id"]] = str(_m.RACINE)
            _m.TOURS_ACTIFS[conv["id"]] = stop
            EN_COURS[ident] = stop
    except Impossible as erreur:
        _echec_demarrage(tache, str(erreur))
        return ""
    debut = datetime.now()
    _noter(ident, derniere_exec=debut.isoformat(timespec="seconds"), derniere_conv=conv["id"], derniere_etat="en_cours", derniere_erreur="")
    etat_final, problemes = "ok", []

    def recueillir(evenement):                           # les erreurs du tour arrivent comme des événements : on les garde pour les écrire dans la conversation
        if evenement.get("type") == "erreur":
            problemes.append(str(evenement.get("texte", "")))
    demande = _t("(Tâche planifiée « {} » lancée le {} à {}.)").format(tache["nom"], debut.strftime("%d/%m/%Y"), debut.strftime("%H:%M")) + " " + tache["prompt"]
    try:
        _m.journaliser("Tâche planifiée « {} » : démarrage (conversation {}).".format(tache["nom"], conv["id"]))
        _m.tour(conv, demande, recueillir, _m.reglages(), stop, None, identite="planifié", lecture_seule=True)
    except Exception as erreur:  # noqa: BLE001
        etat_final = "erreur"
        problemes.append(_t("Erreur inattendue : {}").format(str(erreur)[:300]))
        _m.journaliser("Tâche planifiée « {} » en erreur : {!r}".format(tache["nom"], erreur))
    finally:
        with _m.VERROU_TOURS:
            _m.TOURS_ACTIFS.pop(conv["id"], None)
            _m.RACINE_TOURS.pop(conv["id"], None)
            EN_COURS.pop(ident, None)
    arretee = stop.is_set()
    resultat = ""
    try:
        finale = _m.conv_lire(conv["id"])
        resultat = _derniere_reponse(finale)
        if (problemes or not resultat) and not arretee:  # une tâche qui n'a rien produit le dit dans sa conversation : jamais « rien fait » sans explication
            etat_final = "erreur"
            texte = problemes[-1] if problemes else _t("Aucune réponse n'a été écrite : le moteur n'a rien répondu. Vérifie qu'un moteur est démarré (Réglages > Moteur) puis lance la tâche de nouveau.")
            if not resultat or problemes:
                finale["messages"].append({"role": "assistant", "content": "⚠ " + texte, "ts": datetime.now().isoformat(timespec="seconds")})
                _m.conv_ecrire(finale)
            resultat = resultat if (resultat and not problemes) else "⚠ " + texte
            _m.journaliser("Tâche planifiée « {} » sans résultat : {}".format(tache["nom"], texte[:200]))
    except (OSError, ValueError):
        pass
    if conv["id"] in A_SUPPRIMER:                        # sa tâche a été supprimée avec sa conversation pendant qu'elle travaillait : l'écriture de fin de tour est défaite
        A_SUPPRIMER.discard(conv["id"])
        try:
            _m.conv_supprimer(conv["id"])
        except (OSError, ValueError):
            pass
    if arretee:
        etat_final = "arretee"
    erreur_texte = "" if etat_final == "ok" else (resultat if etat_final == "erreur" else "")
    existe = _noter(ident, derniere_etat=etat_final, derniere_erreur=erreur_texte[:300], **({"actif": False} if tache.get("date") and etat_final != "arretee" else {}))
    if not existe:
        return conv["id"]                                 # supprimée pendant son exécution : rien à noter, personne à prévenir
    _historiser(ident, etat_final, debut, erreur_texte)
    if etat_final != "arretee":
        _notifier(tache, etat_final, resultat)
    return conv["id"]


def _notifier(tache, etat_final, resultat):
    """Envoie le résultat par le canal associé à la tâche (s'il y en a un) ; le résultat de l'envoi est gardé pour la page."""
    if not tache.get("notifier"):
        return
    from . import notifications
    titre = "⏰ " + tache["nom"] + ("" if etat_final == "ok" else " — " + _t("problème"))
    try:
        notifications.envoyer(tache["notifier"], titre, resultat or _t("(pas de réponse)"))
        bilan = "ok"
    except ValueError as erreur:
        bilan = str(erreur)[:200]
        _m.journaliser("Tâche planifiée « {} » : notification impossible ({}).".format(tache["nom"], bilan))
    try:
        modifier(tache["id"], derniere_notif=bilan)
    except ValueError:
        pass


def un_regard(maintenant=None):
    """Lance la première tâche échue si la machine est libre. Renvoie son identifiant (ou None)."""
    maintenant = maintenant or datetime.now()
    for tache in lire():
        if echeance(tache, maintenant) and not _m.TOURS_ACTIFS and tache["id"] not in EN_COURS:
            try:
                executer(tache["id"])
            except ValueError:
                return None
            return tache["id"]
    return None


def boucle():
    while True:
        try:
            un_regard()
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Planification : {!r}".format(erreur))
        time.sleep(PERIODE)


def demarrer():
    for t in lire():
        if t.get("derniere_etat") == "en_cours":
            _noter(t["id"], derniere_etat="interrompue", derniere_erreur=_t("Lutin s'est arrêté pendant que la tâche travaillait."))
    threading.Thread(target=boucle, daemon=True, name="planification").start()
