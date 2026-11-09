"""Notifications : prévenir l'utilisateur sur son téléphone ou sa messagerie quand une tâche planifiée a fini (Gotify, ntfy, Telegram, ou n'importe quel webhook : Discord, Slack, Mattermost, Home Assistant…).

Un « canal » = un service et ses identifiants, enregistrés sur cette machine (notifications.json). Les secrets (jeton, adresse de webhook) ne sont jamais renvoyés à la page : elle sait seulement qu'ils sont définis.
Lutin n'envoie que ce que tu lui as demandé : le résultat d'une tâche planifiée à laquelle tu as associé un canal, ou le message de test. Aucune redirection n'est suivie ; chaque envoi a un délai court.
Gotify et ntfy tournent souvent chez soi : leurs adresses locales sont donc permises (c'est l'utilisateur de cette machine qui les saisit). Telegram a une adresse fixe.
WhatsApp n'a pas d'API gratuite officielle : passe par un webhook vers un pont que tu héberges (type de canal « Webhook JSON »)."""
import json
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import donnees as _d
from . import moteur as _m
from .i18n import t as _t

MAX_CANAUX = 10
DELAI_S = 10
MESSAGE_MAX = 3500
VERROU = threading.Lock()
RE_TEXTE = re.compile(r"^[^\x00-\x1f]{1,200}$")

# type -> (libellé, champs publics, champs secrets). Un champ : (clé, libellé, obligatoire).
TYPES = {
    "gotify": ("Gotify", [("url", "Adresse du serveur (http://192.168.1.10:8080)", True), ("priorite", "Priorité (0 à 10, 5 par défaut)", False)], [("jeton", "Jeton de l'application", True)]),
    "ntfy": ("ntfy", [("url", "Adresse du serveur (https://ntfy.sh par défaut)", False), ("sujet", "Sujet (le nom de ta « boîte »)", True)], [("jeton", "Jeton d'accès (facultatif)", False)]),
    "telegram": ("Telegram", [("chat_id", "Identifiant du chat (nombre)", True)], [("jeton", "Jeton du bot (donné par @BotFather)", True)]),
    "webhook": ("Webhook", [("format", "Format : discord, slack ou json", False)], [("url", "Adresse du webhook", True)]),
}
FORMATS_WEBHOOK = ("discord", "slack", "json")
RE_CHAT = re.compile(r"^-?\d{1,20}$")
RE_JETON_TELEGRAM = re.compile(r"^\d{3,15}:[A-Za-z0-9_\-]{20,80}$")


def chemin():
    return _m.DONNEES / "notifications.json"


def _lire():
    brut = _d.lire_json(chemin(), {})
    canaux = brut.get("canaux") if isinstance(brut, dict) else []
    return [c for c in (canaux or []) if isinstance(c, dict) and c.get("id") and c.get("type") in TYPES]


def _ecrire(canaux):
    _d.ecrire_atomique(chemin(), json.dumps({"canaux": canaux}, ensure_ascii=False, indent=1))


def types():
    """Pour la page : les services proposés et leurs champs."""
    return [{"id": k, "nom": v[0], "champs": [{"cle": c, "libelle": _t(lib), "obligatoire": ob, "secret": False} for c, lib, ob in v[1]] + [{"cle": c, "libelle": _t(lib), "obligatoire": ob, "secret": True} for c, lib, ob in v[2]]} for k, v in TYPES.items()]


def lister():
    """Les canaux SANS leurs secrets."""
    sortie = []
    for c in _lire():
        pub = {k: str(c.get("params", {}).get(k, "")) for k, _, _ in TYPES[c["type"]][1]}
        sortie.append({"id": c["id"], "nom": c["nom"], "type": c["type"], "type_nom": TYPES[c["type"]][0], "params": pub, "secrets_definis": [k for k, _, _ in TYPES[c["type"]][2] if c.get("params", {}).get(k)]})
    return sortie


def trouver(ident):
    return next((c for c in _lire() if c["id"] == ident), None)


def _adresse(texte, defaut=""):
    texte = str(texte or defaut).strip().rstrip("/")
    p = urllib.parse.urlparse(texte)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or len(texte) > 300 or re.search(r"\s", texte):
        raise ValueError(_t("Adresse invalide (exemple : http://192.168.1.10:8080)."))
    return texte


def _verifier(type_, params):
    """Les paramètres nettoyés d'un canal, ou ValueError avec ce qu'il faut corriger."""
    libelle, publics, secrets_ = TYPES[type_]
    out = {}
    for cle, lib, obligatoire in publics + secrets_:
        v = str(params.get(cle) or "").strip()
        if obligatoire and not v:
            raise ValueError(_t("Il manque : {}.").format(_t(lib)))
        out[cle] = v
    if type_ == "gotify":
        out["url"] = _adresse(out["url"])
        try:
            out["priorite"] = str(max(0, min(10, int(out["priorite"] or 5))))
        except ValueError:
            raise ValueError(_t("La priorité est un nombre de 0 à 10.")) from None
    elif type_ == "ntfy":
        out["url"] = _adresse(out["url"], "https://ntfy.sh")
        if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", out["sujet"]):
            raise ValueError(_t("Le sujet ntfy ne contient que des lettres, chiffres, - et _."))
    elif type_ == "telegram":
        if not RE_CHAT.match(out["chat_id"]):
            raise ValueError(_t("L'identifiant du chat Telegram est un nombre (négatif pour un groupe)."))
        if not RE_JETON_TELEGRAM.match(out["jeton"]):
            raise ValueError(_t("Le jeton du bot Telegram a la forme 123456:ABC… (donné par @BotFather)."))
    elif type_ == "webhook":
        out["url"] = _adresse(out["url"])
        out["format"] = (out["format"] or "json").lower()
        if out["format"] not in FORMATS_WEBHOOK:
            raise ValueError(_t("Format de webhook inconnu : discord, slack ou json."))
    return out


def ajouter(nom, type_, params):
    nom = " ".join(str(nom or "").split())[:40]
    if type_ not in TYPES:
        raise ValueError(_t("Ce service n'est pas pris en charge."))
    if not nom:
        raise ValueError(_t("Donne un nom à ce canal (par exemple « Mon téléphone »)."))
    propres = _verifier(type_, params if isinstance(params, dict) else {})
    with VERROU:
        canaux = _lire()
        if len(canaux) >= MAX_CANAUX:
            raise ValueError(_t("Déjà {} canaux : supprime-en un d'abord.").format(MAX_CANAUX))
        if any(c["nom"].lower() == nom.lower() for c in canaux):
            raise ValueError(_t("Un canal porte déjà ce nom."))
        canal = {"id": secrets.token_hex(4), "nom": nom, "type": type_, "params": propres}
        canaux.append(canal)
        _ecrire(canaux)
    _m.journaliser("Notification : canal « {} » ({}) ajouté.".format(nom, TYPES[type_][0]))
    return lister()


def supprimer(ident):
    with VERROU:
        canaux = _lire()
        reste = [c for c in canaux if c["id"] != ident]
        if len(reste) == len(canaux):
            raise ValueError(_t("Ce canal n'existe plus."))
        _ecrire(reste)
    return lister()


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _poster(adresse, corps, en_tetes=None, ouvrir=None):
    req = urllib.request.Request(adresse, data=json.dumps(corps, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers=dict({"Content-Type": "application/json; charset=utf-8", "User-Agent": "Lutin"}, **(en_tetes or {})))
    ouvrir = ouvrir or urllib.request.build_opener(_SansRedirection).open
    with ouvrir(req, timeout=DELAI_S) as r:
        r.read(4096)
    return True


def _requete(canal, titre, message):
    """(adresse, corps JSON, en-têtes) pour ce service."""
    p, t = canal.get("params", {}), canal["type"]
    titre, message = str(titre or "Lutin")[:120], str(message or "")[:MESSAGE_MAX]
    if t == "gotify":
        return p["url"] + "/message", {"title": titre, "message": message or "—", "priority": int(p.get("priorite") or 5)}, {"X-Gotify-Key": p["jeton"]}
    if t == "ntfy":
        return p["url"], {"topic": p["sujet"], "title": titre, "message": message or "—"}, ({"Authorization": "Bearer " + p["jeton"]} if p.get("jeton") else {})
    if t == "telegram":
        return "https://api.telegram.org/bot{}/sendMessage".format(p["jeton"]), {"chat_id": p["chat_id"], "text": (titre + "\n\n" + message)[:4000]}, {}
    texte = (titre + "\n" + message)[:1900]
    corps = {"content": texte} if p.get("format") == "discord" else ({"text": texte} if p.get("format") == "slack" else {"title": titre, "message": message})
    return p["url"], corps, {}


def envoyer(ident, titre, message, ouvrir=None):
    """Envoie une notification par ce canal. ValueError (sans jamais montrer le secret) si ça échoue."""
    canal = trouver(ident)
    if canal is None:
        raise ValueError(_t("Ce canal n'existe plus."))
    adresse, corps, en_tetes = _requete(canal, titre, message)
    try:
        _poster(adresse, corps, en_tetes, ouvrir)
    except urllib.error.HTTPError as e:
        raise ValueError(_t("« {} » a refusé le message (erreur {}) : vérifie l'adresse et le jeton.").format(canal["nom"], e.code)) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raison = getattr(e, "reason", e)
        raise ValueError(_t("« {} » n'a pas répondu : {}").format(canal["nom"], str(raison)[:120])) from None
    return True


def tester(ident, ouvrir=None):
    envoyer(ident, "Lutin", _t("Ceci est un message de test : les notifications fonctionnent."), ouvrir)
    return {"ok": True}
