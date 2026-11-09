"""Tâches planifiées : une demande que Lutin traite tout seul à heure fixe (« chaque matin, résume les changements du dépôt »).

Personne n'est là pour accepter quoi que ce soit : la tâche tourne en lecture seule, comme dans l'essai à blanc (lecture et recherche réelles, tout le reste simulé).
Le résultat est UNE conversation « ⏰ nom » par tâche, à retrouver dans la liste : chaque exécution y ajoute sa demande (datée) et sa réponse. Un problème (moteur absent, mémoire pleine…) y est écrit, jamais passé sous silence.
Un canal de notification (Gotify, ntfy, Telegram, webhook : voir notifications.py) peut être associé à une tâche : le résultat y est envoyé quand elle a fini. Une tâche ne démarre que si aucune réponse n'est en cours (une seule carte graphique)."""
import re
import secrets
import threading
import time
from datetime import datetime

from . import donnees as _d
from .i18n import t as _t
from . import moteur as _m

MAX_TACHES = 20
RE_HEURE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
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


def ajouter(nom, prompt, heure, jours, travail="", notifier=""):
    nom, prompt = " ".join(str(nom or "").split())[:60], str(prompt or "").strip()
    if not nom or not prompt:
        raise ValueError(_t("Donne un nom et la demande à traiter."))
    if len(prompt) > 4000:
        raise ValueError(_t("La demande est trop longue (4 000 caractères au plus)."))
    if not RE_HEURE.match(str(heure or "")):
        raise ValueError(_t("L'heure doit être au format HH:MM (par exemple 08:30)."))
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
    with VERROU:
        liste = lire()
        if len(liste) >= MAX_TACHES:
            raise ValueError(_t("Déjà {} tâches planifiées : supprime-en une d'abord.").format(MAX_TACHES))
        tache = {"id": secrets.token_hex(4), "nom": nom, "prompt": prompt, "heure": heure, "jours": jours, "travail": str(travail or "")[:80], "notifier": notifier, "derniere_notif": "", "actif": True,
                 "cree": datetime.now().isoformat(timespec="seconds"), "derniere_exec": "", "derniere_conv": "", "derniere_etat": ""}
        liste.append(tache)
        _ecrire(liste)
    return tache


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


def supprimer(ident):
    with VERROU:
        liste = lire()
        reste = [t for t in liste if t["id"] != ident]
        if len(reste) == len(liste):
            raise ValueError(_t("Cette tâche planifiée n'existe plus."))
        _ecrire(reste)
    return {"ok": True}


def echeance(tache, maintenant):
    """Date de la dernière occurrence prévue (aujourd'hui à l'heure dite) si elle est passée et pas encore traitée, sinon None.
    Une tâche créée après l'heure du jour attend le lendemain ; un PC éteint à l'heure dite la rattrape au démarrage, le jour même seulement."""
    if not tache.get("actif") or maintenant.weekday() not in tache.get("jours", []):
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
    for plus in range(0, 8):
        jour = (maintenant + timedelta(days=plus)).replace(hour=h, minute=m, second=0, microsecond=0)
        if jour.weekday() in tache["jours"] and (jour > maintenant or (plus == 0 and echeance(tache, maintenant))):
            return jour.isoformat(timespec="minutes")
    return ""


def etat():
    maintenant = datetime.now()
    return {"taches": [dict(t, prochaine=prochaine(t, maintenant)) for t in lire()]}


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


def executer(ident):
    """Traite une tâche maintenant. Renvoie l'identifiant de SA conversation (la même à chaque exécution), ou lève ValueError si la machine est déjà occupée."""
    tache = next((t for t in lire() if t["id"] == ident), None)
    if tache is None:
        raise ValueError(_t("Cette tâche planifiée n'existe plus."))
    stop = threading.Event()
    with _m.VERROU_TOURS:
        if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
            raise ValueError(_t("Une réponse est déjà en cours : la tâche attend."))
        conv, neuve = _conversation(tache)
        if neuve:
            try:
                _m.activer_travail(conv, tache.get("travail", ""))
            except ValueError:
                _d.conv_chemin(conv["id"]).unlink(missing_ok=True)
                raise
        _m.RACINE_TOURS[conv["id"]] = str(_m.RACINE)
        _m.TOURS_ACTIFS[conv["id"]] = stop
    modifier(ident, derniere_exec=datetime.now().isoformat(timespec="seconds"), derniere_conv=conv["id"], derniere_etat="en_cours")
    etat_final, problemes = "ok", []

    def recueillir(evenement):                           # les erreurs du tour arrivent comme des événements : on les garde pour les écrire dans la conversation
        if evenement.get("type") == "erreur":
            problemes.append(str(evenement.get("texte", "")))
    maintenant = datetime.now()
    demande = _t("(Tâche planifiée « {} » lancée le {} à {}.)").format(tache["nom"], maintenant.strftime("%d/%m/%Y"), maintenant.strftime("%H:%M")) + " " + tache["prompt"]
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
    resultat = ""
    try:
        finale = _m.conv_lire(conv["id"])
        resultat = _derniere_reponse(finale)
        if problemes or not resultat:                    # une tâche qui n'a rien produit le dit dans sa conversation : jamais « rien fait » sans explication
            etat_final = "erreur"
            texte = problemes[-1] if problemes else _t("Aucune réponse n'a été écrite : le moteur n'a rien répondu. Vérifie qu'un moteur est démarré (Réglages > Moteur) puis lance la tâche de nouveau.")
            if not resultat or problemes:
                finale["messages"].append({"role": "assistant", "content": "⚠ " + texte})
                _m.conv_ecrire(finale)
            resultat = resultat if (resultat and not problemes) else "⚠ " + texte
            _m.journaliser("Tâche planifiée « {} » sans résultat : {}".format(tache["nom"], texte[:200]))
    except (OSError, ValueError):
        pass
    try:
        modifier(ident, derniere_etat=etat_final)
    except ValueError:
        pass                                              # supprimée pendant son exécution
        return conv["id"]
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
        if echeance(tache, maintenant) and not _m.TOURS_ACTIFS:
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
    threading.Thread(target=boucle, daemon=True, name="planification").start()
