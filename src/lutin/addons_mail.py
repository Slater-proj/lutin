"""Partie vivante de l'addon Courriel : lit ta boîte de réception (IMAP) et prépare des réponses (SMTP) selon tes règles, jamais sans toi par défaut.

Un courriel n'est JAMAIS un ordre : n'importe qui peut écrire n'importe quel nom d'expéditeur. Le modèle n'a donc aucun outil pour répondre (voir repondeur.py) et, par défaut, chaque réponse est un BROUILLON que tu valides sur la page.

Solidité :
- à la première activation, les courriels déjà présents sont ignorés (on ne répond pas à l'arriéré) : seuls les nouveaux comptent, repérés par leur UID ; la boîte n'est pas modifiée (lecture sans marquer « lu ») ;
- jamais de réponse à un message automatique (noreply, listes de diffusion, accusés, absence), à soi-même, ni deux fois au même message ; au plus 20 réponses automatiques par jour ;
- les règles (voir regles.py) disent quoi faire de chaque message ; sans règle qui correspond, il est ignoré ;
- les serveurs sont joints en connexion chiffrée ; une adresse de ton réseau local n'est permise que si tu le dis ;
- le mot de passe est rangé à part (utilise un mot de passe d'application, pas celui de ton compte), jamais renvoyé à la page ni écrit dans le journal ;
- une panne est attendue avec un délai croissant."""
import email
import email.policy
import imaplib
import json
import re
import secrets
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import parseaddr

from . import addons, regles, repondeur
from . import moteur as _m
from .i18n import t as _t

IDENT = "mail"
IMAP = imaplib.IMAP4_SSL                 # remplaçables dans les tests
SMTP_SSL = smtplib.SMTP_SSL
SMTP = smtplib.SMTP
TAILLE_MAX = 800_000                     # octets : un courriel plus gros est ignoré
AUTO_PAR_JOUR = 20
VIVANT = {"fil": None, "stop": threading.Event(), "erreur": "", "derniere": 0}
VERROU = threading.Lock()
RE_AUTOMATIQUE = re.compile(r"(^|[._-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notification|notifications)([._-]|@)", re.I)


# --------------------------------------------------------------------------- état
def chemin():
    return addons.dossier_donnees() / IDENT / "etat.json"


def lire():
    e = _m.lire_json(chemin(), {})
    for cle, defaut in (("uid", {}), ("brouillons", []), ("vus", []), ("auto", {})):
        e.setdefault(cle, defaut)
    return e


def ecrire(e):
    chemin().parent.mkdir(parents=True, exist_ok=True)
    _m.ecrire_atomique(chemin(), json.dumps(e, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------- connexions
def verifier_serveur(hote, reseau_local):
    """Refuse un serveur du réseau local sauf si l'utilisateur l'a permis (un réglage modifié ne doit pas faire lire autre chose que le courrier)."""
    if reseau_local == "oui":
        return
    from . import web
    import os
    if os.environ.get("LUTIN_WEB_LOCAL") == "1":
        return
    web.verifier_hote_web("https://" + hote)


def reglages_mail():
    v = addons.reglages(IDENT)
    for cle, defaut in (("port_imap", "993"), ("port_smtp", "465"), ("dossier", "INBOX"), ("intervalle", "5"), ("reseau_local", "non")):
        v[cle] = str(v.get(cle) or defaut)
    return v


def connexion_imap(v):
    verifier_serveur(v["serveur_imap"], v["reseau_local"])
    imap = IMAP(v["serveur_imap"], int(v["port_imap"]), timeout=30)
    imap.login(v["adresse"], v["motdepasse"])
    return imap


def connexion_smtp(v):
    verifier_serveur(v["serveur_smtp"], v["reseau_local"])
    port = int(v["port_smtp"])
    smtp = SMTP_SSL(v["serveur_smtp"], port, timeout=30) if port == 465 else SMTP(v["serveur_smtp"], port, timeout=30)
    if port != 465:
        smtp.starttls()
    smtp.login(v["adresse"], v["motdepasse"])
    return smtp


def verifier():
    """La vérification de l'addon (appelée par addons.verifier) : règles lisibles, boîte de réception joignable, envoi possible. Renvoie des étapes {appel, ok, message}."""
    v = reglages_mail()
    etapes = []
    try:
        n = len(regles.analyser(v.get("regles", "")))
        etapes.append({"appel": "regles", "ok": True, "message": _t("{} règle(s)").format(n)})
    except regles.ErreurRegle as e:
        return [{"appel": "regles", "ok": False, "message": str(e)}]
    try:
        imap = connexion_imap(v)
        try:
            typ, _ = imap.select(v["dossier"], readonly=True)
            if typ != "OK":
                raise imaplib.IMAP4.error(_t("dossier « {} » introuvable").format(v["dossier"]))
        finally:
            try:
                imap.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
        etapes.append({"appel": "reception", "ok": True, "message": _t("boîte « {} » lisible").format(v["dossier"])})
    except Exception as e:  # noqa: BLE001
        return etapes + [{"appel": "reception", "ok": False, "message": addons.masquer(_t("Réception impossible : {}").format(e), v)}]
    try:
        smtp = connexion_smtp(v)
        smtp.quit()
        etapes.append({"appel": "envoi", "ok": True, "message": _t("envoi possible")})
    except Exception as e:  # noqa: BLE001
        etapes.append({"appel": "envoi", "ok": False, "message": addons.masquer(_t("Envoi impossible : {}").format(e), v)})
    return etapes


# --------------------------------------------------------------------------- lecture et tri
def texte_du_message(msg):
    corps = msg.get_body(preferencelist=("plain", "html"))
    if corps is None:
        return ""
    texte = corps.get_content()
    if corps.get_content_type() == "text/html":
        texte = re.sub(r"<(script|style).*?</\1>", " ", texte, flags=re.S | re.I)
        texte = re.sub(r"<[^>]+>", " ", texte)
    return " ".join(str(texte).split())[:4000]


def automatique(msg, adresse):
    """Un message qu'on ne doit jamais auto-répondre : automatique, liste de diffusion, accusé, ou venant de soi-même."""
    expediteur = parseaddr(str(msg.get("From", "")))[1].lower()
    if not expediteur or expediteur == adresse.lower() or RE_AUTOMATIQUE.search(expediteur):
        return True
    if str(msg.get("Auto-Submitted", "no")).strip().lower() not in ("", "no"):
        return True
    if str(msg.get("Precedence", "")).strip().lower() in ("bulk", "list", "junk", "auto_reply"):
        return True
    return any(msg.get(h) for h in ("List-Id", "List-Unsubscribe", "X-Autoreply", "X-Auto-Response-Suppress"))


def traiter(msg, v, regles_liste):
    """Un nouveau courriel : le tri décide (ignorer, brouillon, réponse seule)."""
    identifiant = str(msg.get("Message-ID", "")).strip() or secrets.token_hex(6)
    with VERROU:
        e = lire()
        if identifiant in e["vus"]:
            return
        e["vus"] = (e["vus"] + [identifiant])[-500:]
        ecrire(e)
    if automatique(msg, v["adresse"]):
        return
    nom, adresse = parseaddr(str(msg.get("From", "")))
    sujet = " ".join(str(msg.get("Subject", "")).split())[:200]
    message = {"de": str(msg.get("From", "")), "sujet": sujet, "texte": texte_du_message(msg)}
    regle = regles.choisir(regles_liste, message, repondeur.juger_ton if regles.besoin_du_ton(regles_liste) else None)
    if regle is None or regle["action"] == "ignorer":
        return
    reponse = repondeur.reponse(IDENT, _t("Courriel"), adresse.lower(), nom or adresse, _t("Objet : {}\n\n{}").format(sujet, message["texte"]), regle["consigne"], VIVANT["stop"])
    if not reponse:
        return
    brouillon = {"id": secrets.token_hex(4), "de": nom or adresse, "adresse": adresse, "sujet": sujet, "extrait": message["texte"][:500], "texte": reponse, "message_id": identifiant,
                 "references": " ".join(str(msg.get("References", "")).split() + [identifiant])[-900:], "date": int(time.time())}
    if regle["action"] == "auto":
        brouillon["auto"] = True
        jour = time.strftime("%Y-%m-%d")
        with VERROU:
            e = lire()
            n = e["auto"].get(jour, 0)
            if n < AUTO_PAR_JOUR:
                e["auto"] = {jour: n + 1}
                ecrire(e)
                envoyer(brouillon, reponse, v)
                return
    with VERROU:
        e = lire()
        e["brouillons"] = (e["brouillons"] + [brouillon])[-50:]
        ecrire(e)


def envoyer(brouillon, texte, v=None):
    v = v or reglages_mail()
    reponse = EmailMessage()
    reponse["From"] = v["adresse"]
    reponse["To"] = brouillon["adresse"]
    sujet = brouillon["sujet"]
    reponse["Subject"] = sujet if sujet.lower().startswith("re:") else "Re: " + sujet
    reponse["In-Reply-To"] = brouillon["message_id"]
    reponse["References"] = brouillon["references"]
    reponse["Auto-Submitted"] = "auto-replied" if brouillon.get("auto") else "no"
    reponse.set_content(texte)
    smtp = connexion_smtp(v)
    try:
        smtp.send_message(reponse)
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass


def une_lecture():
    """Lit les nouveaux courriels et les traite. Renvoie leur nombre, ou -1 si le serveur ne répond pas."""
    v = reglages_mail()
    if not (v.get("serveur_imap") and v.get("adresse") and v.get("motdepasse")):
        VIVANT["erreur"] = _t("À configurer d'abord.")
        return -1
    try:
        regles_liste = regles.analyser(v.get("regles", ""))
    except regles.ErreurRegle as e:
        VIVANT["erreur"] = str(e)
        return -1
    try:
        imap = connexion_imap(v)
    except Exception as e:  # noqa: BLE001
        VIVANT["erreur"] = addons.masquer(str(e), v)
        return -1
    n = 0
    try:
        typ, _ = imap.select(v["dossier"], readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(_t("dossier « {} » introuvable").format(v["dossier"]))
        validite = ""
        try:
            validite = " ".join(str(x) for x in (imap.response("UIDVALIDITY")[1] or [])).replace("b'", "").replace("'", "")
        except (imaplib.IMAP4.error, TypeError):
            pass
        cle = v["dossier"] + "|" + validite
        e = lire()
        dernier = e["uid"].get(cle)
        typ, donnees = imap.uid("search", None, "ALL")
        uids = sorted(int(x) for x in (donnees[0] or b"").split())
        if dernier is None:
            e["uid"] = {cle: uids[-1] if uids else 0}                          # première fois : l'arriéré est ignoré
            ecrire(e)
            VIVANT["erreur"] = ""
            return 0
        for uid in [u for u in uids if u > dernier][:30]:
            typ, morceaux = imap.uid("fetch", str(uid), "(RFC822.SIZE BODY.PEEK[])")
            brut = next((x[1] for x in morceaux if isinstance(x, tuple)), b"")
            if brut and len(brut) <= TAILLE_MAX:
                try:
                    traiter(email.message_from_bytes(brut, policy=email.policy.default), v, regles_liste)
                except Exception as erreur:  # noqa: BLE001  (un courriel qui plante ne bloque pas les suivants)
                    _m.journaliser("Courriel : message en erreur ({!r}).".format(erreur))
            with VERROU:
                e = lire()
                e["uid"][cle] = uid
                ecrire(e)
            n += 1
        VIVANT["erreur"] = ""
    except Exception as erreur:  # noqa: BLE001
        VIVANT["erreur"] = addons.masquer(str(erreur), v)
        return -1
    finally:
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
    VIVANT["derniere"] = int(time.time())
    return n


def boucle():
    echecs = 0
    while not VIVANT["stop"].is_set():
        try:
            n = une_lecture()
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Courriel : lecture en erreur ({!r}).".format(erreur))
            n = -1
        if n < 0:
            echecs += 1
            VIVANT["stop"].wait(min(1800, 60 * 2 ** min(echecs, 5)))
        else:
            echecs = 0
            try:
                minutes = max(1, min(120, int(reglages_mail()["intervalle"])))
            except ValueError:
                minutes = 5
            VIVANT["stop"].wait(minutes * 60)


def demarrer():
    if VIVANT["fil"] and VIVANT["fil"].is_alive():
        return
    VIVANT["stop"].clear()
    VIVANT["fil"] = threading.Thread(target=boucle, daemon=True, name="courriel")
    VIVANT["fil"].start()


def arreter():
    VIVANT["stop"].set()


# --------------------------------------------------------------------------- panneau
def etat():
    e = lire()
    return {"brouillons": e["brouillons"], "erreur": VIVANT["erreur"], "ecoute": bool(VIVANT["fil"] and VIVANT["fil"].is_alive()), "derniere": VIVANT["derniere"],
            "adresse": addons.reglages(IDENT).get("adresse", "")}


def action(nom, donnees):
    with VERROU:
        e = lire()
        if nom in ("envoyer", "rejeter"):
            b = next((x for x in e["brouillons"] if x["id"] == str(donnees.get("brouillon"))), None)
            if b is None:
                raise addons.ErreurAddon(_t("Ce brouillon n'existe plus."))
            if nom == "envoyer":
                texte = str(donnees.get("texte") or b["texte"]).strip()
                if not texte:
                    raise addons.ErreurAddon(_t("Le message est vide."))
                try:
                    envoyer(b, texte)
                except Exception as erreur:  # noqa: BLE001
                    raise addons.ErreurAddon(_t("Envoi impossible : {}").format(addons.masquer(str(erreur), reglages_mail())))
            e["brouillons"] = [x for x in e["brouillons"] if x["id"] != b["id"]]
            ecrire(e)
            return etat()
        if nom == "verifier_regles":
            try:
                return {"ok": True, "regles": len(regles.analyser(addons.reglages(IDENT).get("regles", "")))}
            except regles.ErreurRegle as erreur:
                raise addons.ErreurAddon(str(erreur))
    raise addons.ErreurAddon(_t("Action inconnue."))

