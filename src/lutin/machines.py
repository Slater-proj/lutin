"""Machines (décision D7) : chaque Lutin est un nœud, sans agent séparé.

Le POSTE à carte graphique (le nœud) prête le moteur de sa machine ; le PETIT PC (le principal) route ses demandes vers lui et, s'il est injoignable, répond avec son moteur local, EN SILENCE.

Ce que le nœud accepte, et rien d'autre :
- il est éteint par défaut ; le propriétaire l'active (Réglages > Machines) et seulement si le niveau d'accès n'est pas « cette machine seulement » ;
- une machine s'ajoute par **validation explicite** : le nœud affiche un code à 8 chiffres (valable 5 minutes, à usage unique) que le propriétaire saisit sur l'autre Lutin. Jamais d'acceptation automatique, jamais de découverte du réseau ;
- le code s'échange contre un **jeton de nœud** (propre à chaque machine, gardé haché sur le nœud). Ce jeton ouvre `/api/noeud/*` et RIEN d'autre : ni conversations, ni fichiers, ni réglages. Il se révoque d'un clic ;
- le nœud ne garde rien des demandes : il fait tourner son moteur et renvoie la réponse.

Ce que le principal garantit :
- avant d'envoyer la moindre donnée, il vérifie que la machine au bout de l'adresse est bien celle qui a été appairée (identifiant du nœud) ; sinon il répond en local ;
- quatre états observables seulement : injoignable · réveil envoyé (0.24.0) · nœud joignable · moteur opérationnel (le nœud a ce modèle) ;
- **une machine injoignable ne produit ni erreur ni avertissement dans la conversation** : le repli local est silencieux, l'état est visible dans la page Machines et dans le journal (un seul trait à chaque changement d'état).
Routage d'abord, répartition ensuite ; un même modèle n'est jamais réparti entre machines."""
import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import alimentation
from .i18n import t as _t

ETATS = ("injoignable", "reveil_envoye", "joignable", "operationnel")
DUREE_CODE_S = 300
CODES_MAX = 3
VALIDITE_SONDE_S = 10          # un constat d'état est gardé ce temps : pas de sonde à chaque message
DELAI_SONDE_S = 1.5
RE_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
RE_ID = re.compile(r"^[0-9a-f]{32}$")
CLES_CHAT = ("model", "messages", "tools", "options", "think", "format", "stream", "keep_alive")          # ce que le nœud accepte de transmettre à son moteur

DOSSIER = None          # les tests le remplacent ; sinon le dossier de données de Lutin
VERROU = threading.RLock()
CODES = {}          # code (chiffres) -> instant d'expiration
SONDES = {}          # id de machine -> (instant, résultat)
DERNIER_ETAT = {}          # id de machine -> dernier état journalisé
REVEIL = {}          # id de machine -> instant du dernier paquet de réveil envoyé


def dossier():
    if DOSSIER is not None:
        return Path(DOSSIER)
    from . import moteur as _m
    return Path(_m.DONNEES)


def _lire(nom, defaut):
    try:
        return json.loads((dossier() / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _ecrire(nom, valeur):
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (nom + ".tmp")
    tmp.write_text(json.dumps(valeur, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / nom)


def journaliser(texte):
    """Une ligne dans machines.log (sans donnée de conversation)."""
    try:
        d = dossier()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "machines.log", "a", encoding="utf-8") as f:
            f.write("{} {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), texte))
    except OSError:
        pass


def journal(n=30):
    """Les dernières lignes du journal des machines."""
    try:
        return (dossier() / "machines.log").read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


# --------------------------------------------------------------------------- côté NŒUD : prêter le moteur de cette machine

def noeud():
    """{id, actif, jetons:[{empreinte, nom, date}]} — l'identifiant est créé une fois et ne change plus."""
    with VERROU:
        n = _lire("noeud.json", {})
        if not isinstance(n, dict) or not RE_ID.match(str(n.get("id", ""))):
            n = {"id": uuid.uuid4().hex, "actif": False, "jetons": []}
            _ecrire("noeud.json", n)
        n.setdefault("jetons", [])
        n["actif"] = bool(n.get("actif"))
        return n


def noeud_actif():
    return noeud()["actif"]


def noeud_activer(actif, niveau_local=False):
    """Prête (ou cesse de prêter) le moteur de cette machine. Refusé au niveau « cette machine seulement » : personne d'autre ne pourrait de toute façon l'atteindre."""
    if actif and niveau_local:
        raise ValueError(_t("Le niveau d'accès « cette machine seulement » n'accepte aucune autre machine : passe au niveau « réseau » (Accès) pour prêter le moteur."))
    with VERROU:
        n = noeud()
        n["actif"] = bool(actif)
        _ecrire("noeud.json", n)
    journaliser("nœud {}".format("activé" if actif else "désactivé"))
    return noeud_vue()


def noeud_nouveau_code():
    """Un code à 8 chiffres, à usage unique, valable 5 minutes, à saisir sur l'autre Lutin. Au plus 3 codes en attente."""
    with VERROU:
        maintenant = time.time()
        for c in [c for c, fin in CODES.items() if fin < maintenant]:
            del CODES[c]
        if len(CODES) >= CODES_MAX:
            del CODES[min(CODES, key=CODES.get)]
        code = "{:08d}".format(secrets.randbelow(10 ** 8))
        CODES[code] = maintenant + DUREE_CODE_S
    return {"code": code[:4] + "-" + code[4:], "expire_dans": DUREE_CODE_S}


def _empreinte(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def noeud_echanger(code, nom_demandeur):
    """Échange un code valide contre un jeton de nœud. Lève ValueError sinon (même message pour un code faux ou périmé)."""
    brut = re.sub(r"\D", "", str(code or ""))
    nom = re.sub(r"[^\w .-]", "", str(nom_demandeur or "")).strip()[:40] or "machine"
    with VERROU:
        n = noeud()
        fin = CODES.pop(brut, None) if len(brut) == 8 else None
        if not n["actif"] or fin is None or fin < time.time():
            raise ValueError(_t("Code incorrect ou expiré, ou ce Lutin ne prête pas son moteur."))
        jeton = secrets.token_urlsafe(32)
        n["jetons"].append({"empreinte": _empreinte(jeton), "nom": nom, "date": time.strftime("%Y-%m-%d %H:%M")})
        _ecrire("noeud.json", n)
    journaliser("machine autorisée : {}".format(nom))
    return {"jeton": jeton, "id": n["id"], "nom": socket.gethostname()[:40]}


def noeud_jeton_valide(jeton):
    """Le nom de la machine autorisée portant ce jeton, ou None. Un nœud éteint ne reconnaît personne."""
    if not jeton or not noeud_actif():
        return None
    vu = _empreinte(str(jeton))
    for j in noeud()["jetons"]:
        if hmac.compare_digest(j["empreinte"], vu):
            return j["nom"]
    return None


def noeud_revoquer(nom):
    with VERROU:
        n = noeud()
        avant = len(n["jetons"])
        n["jetons"] = [j for j in n["jetons"] if j["nom"] != nom]
        _ecrire("noeud.json", n)
    if len(n["jetons"]) != avant:
        journaliser("machine révoquée : {}".format(nom))
    return noeud_vue()


def noeud_autoriser_extinction(autoriser):
    """Les machines appairées peuvent-elles éteindre celle-ci ? Décoché par défaut : c'est le propriétaire de CETTE machine qui le décide."""
    with VERROU:
        n = noeud()
        n["extinction"] = bool(autoriser)
        _ecrire("noeud.json", n)
    journaliser("extinction par une machine appairée : {}".format("autorisée" if autoriser else "interdite"))
    return noeud_vue()


def noeud_vue():
    n = noeud()
    return {"actif": n["actif"], "id": n["id"], "extinction": bool(n.get("extinction")), "extinction_en_attente": alimentation.extinction_en_attente(),
            "autorisees": [{"nom": j["nom"], "date": j["date"]} for j in n["jetons"]]}


def noeud_etat(moteur, modeles):
    """Ce que le nœud répond à `GET /api/noeud/etat` : de quoi savoir s'il est joignable et si son moteur peut faire tourner le modèle voulu."""
    return {"id": noeud()["id"], "moteur": moteur.id, "moteur_nom": moteur.nom, "actif": bool(modeles.get("actif")), "modeles": sorted(modeles.get("installes", []))[:500]}


def corps_autorise(corps):
    """Le corps d'une demande de conversation, réduit à ce que le nœud accepte de transmettre à son moteur."""
    if not isinstance(corps, dict) or not isinstance(corps.get("model"), str) or not isinstance(corps.get("messages"), list):
        raise ValueError(_t("Demande invalide."))
    return {k: corps[k] for k in CLES_CHAT if k in corps}


# --------------------------------------------------------------------------- côté PRINCIPAL : le registre des machines

def normaliser_adresse(adresse):
    """http(s)://hôte:port sans chemin ; port 8777 par défaut. Lève ValueError sinon."""
    texte = str(adresse or "").strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", texte, re.I) and not re.match(r"^https?://", texte, re.I):
        raise ValueError(_t("Adresse de machine invalide (exemple : 192.168.1.20 ou http://poste:8777)."))
    if not re.match(r"^https?://", texte, re.I):
        texte = "http://" + texte
    p = urllib.parse.urlparse(texte)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError(_t("Adresse de machine invalide (exemple : 192.168.1.20 ou http://poste:8777)."))
    try:
        port = p.port or 8777
    except ValueError:
        raise ValueError(_t("Adresse de machine invalide (exemple : 192.168.1.20 ou http://poste:8777).")) from None
    hote = "[{}]".format(p.hostname) if ":" in p.hostname else p.hostname
    return "{}://{}:{}".format(p.scheme, hote, port)


REGISTRE = {"t": 0.0, "v": [], "d": None}          # le registre est relu au plus toutes les 2 s (moteur_actuel est appelé très souvent)


def lire():
    if REGISTRE["d"] == str(dossier()) and time.monotonic() - REGISTRE["t"] < 2:
        return [dict(m) for m in REGISTRE["v"]]
    liste = _lire("machines.json", [])
    liste = [m for m in liste if isinstance(m, dict) and RE_ID.match(str(m.get("id", "")))] if isinstance(liste, list) else []
    REGISTRE.update(t=time.monotonic(), v=liste, d=str(dossier()))
    return [dict(m) for m in liste]


def _ecrire_registre(liste):
    _ecrire("machines.json", liste)
    REGISTRE.update(t=0.0)


def trouver(ident):
    return next((m for m in lire() if m["id"] == ident), None)


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None          # une redirection enverrait le jeton ailleurs


def requete(m_ou_adresse, chemin, corps=None, jeton="", delai=DELAI_SONDE_S, ouvrir=None):
    """Appelle un nœud : la réponse ouverte. `m_ou_adresse` : une machine du registre, ou une adresse. Pas de redirection suivie."""
    adresse = m_ou_adresse["adresse"] if isinstance(m_ou_adresse, dict) else m_ou_adresse
    jeton = jeton or (m_ou_adresse.get("jeton", "") if isinstance(m_ou_adresse, dict) else "")
    en_tetes = {"Content-Type": "application/json"}
    if jeton:
        en_tetes["X-Noeud"] = jeton
    req = urllib.request.Request(adresse + chemin, data=None if corps is None else json.dumps(corps).encode("utf-8"), headers=en_tetes, method="GET" if corps is None else "POST")
    return (ouvrir or urllib.request.build_opener(_SansRedirection).open)(req, timeout=delai)


def _json(m_ou_adresse, chemin, corps=None, jeton="", delai=DELAI_SONDE_S, ouvrir=None):
    with requete(m_ou_adresse, chemin, corps, jeton, delai, ouvrir) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace") or "{}")


def ajouter(adresse, code, nom="", mac="", ouvrir=None):
    """Ajoute une machine après validation explicite (le code affiché sur le nœud). Renvoie la machine (sans son jeton)."""
    adresse = normaliser_adresse(adresse)
    mac = str(mac or "").strip()
    if mac and not RE_MAC.match(mac):
        raise ValueError(_t("Adresse MAC invalide (exemple : 00:1A:2B:3C:4D:5E)."))
    try:
        rep = _json(adresse, "/api/noeud/appairer", {"code": str(code or ""), "nom": socket.gethostname()[:40]}, delai=5, ouvrir=ouvrir)
    except urllib.error.HTTPError as e:
        raise ValueError(_t("Cette machine a refusé le code (incorrect, expiré, ou elle ne prête pas son moteur).") if e.code in (400, 401, 403) else _t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None
    if not RE_ID.match(str(rep.get("id", ""))) or not rep.get("jeton"):
        raise ValueError(_t("Réponse inattendue : ce n'est pas un Lutin qui prête son moteur."))
    with VERROU:
        liste = [m for m in lire() if m["id"] != rep["id"]]
        m = {"id": rep["id"], "nom": (str(nom).strip() or str(rep.get("nom") or "machine"))[:40], "adresse": adresse, "jeton": rep["jeton"], "mac": mac, "ajoutee": time.strftime("%Y-%m-%d %H:%M")}
        liste.append(m)
        _ecrire_registre(liste)
    journaliser("machine ajoutée : {} ({})".format(m["nom"], adresse))
    return vue(m)


def retirer(ident):
    with VERROU:
        liste = lire()
        m = next((x for x in liste if x["id"] == ident), None)
        if m is None:
            raise ValueError(_t("Machine inconnue."))
        _ecrire_registre([x for x in liste if x["id"] != ident])
        SONDES.pop(ident, None)
    journaliser("machine retirée : {}".format(m["nom"]))


def definir_mac(ident, mac):
    mac = str(mac or "").strip()
    if mac and not RE_MAC.match(mac):
        raise ValueError(_t("Adresse MAC invalide (exemple : 00:1A:2B:3C:4D:5E)."))
    with VERROU:
        liste = lire()
        for m in liste:
            if m["id"] == ident:
                m["mac"] = mac
                _ecrire_registre(liste)
                return vue(m)
    raise ValueError(_t("Machine inconnue."))


def vue(m):
    """Une machine pour la page : jamais son jeton."""
    return {k: m.get(k, "") for k in ("id", "nom", "adresse", "mac", "ajoutee")}


# --------------------------------------------------------------------------- l'état d'une machine (quatre états)

def sonder(m, modele="", ouvrir=None, maintenant=time.monotonic, force=False):
    """{etat, detail, modeles} : injoignable · joignable (le nœud répond mais n'a pas ce modèle ou son moteur est arrêté) · operationnel. Gardé 10 s. Vérifie que c'est bien la machine appairée."""
    with VERROU:
        gardee = SONDES.get(m["id"])
        if gardee and not force and maintenant() - gardee[0] < VALIDITE_SONDE_S and gardee[2] == modele:
            return gardee[1]
    try:
        rep = _json(m, "/api/noeud/etat", ouvrir=ouvrir)
        if rep.get("id") != m["id"]:
            r = {"etat": "injoignable", "detail": _t("Ce n'est plus la même machine à cette adresse : rien ne lui est envoyé."), "modeles": []}
        elif not rep.get("actif"):
            r = {"etat": "joignable", "detail": _t("La machine répond, mais son moteur est arrêté."), "modeles": []}
        elif modele and modele not in rep.get("modeles", []):
            r = {"etat": "joignable", "detail": _t("La machine répond, mais le modèle « {} » n'y est pas installé.").format(modele), "modeles": rep.get("modeles", [])}
        else:
            r = {"etat": "operationnel", "detail": _t("Moteur opérationnel : {}.").format(rep.get("moteur_nom") or rep.get("moteur") or "?"), "modeles": rep.get("modeles", [])}
    except urllib.error.HTTPError as e:
        r = {"etat": "injoignable", "detail": _t("La machine refuse ce Lutin (erreur {}) : l'autorisation a peut-être été retirée.").format(e.code), "modeles": []}
    except (urllib.error.URLError, OSError, ValueError):
        r = {"etat": "injoignable", "detail": _t("Pas de réponse (éteinte, hors réseau ou Lutin arrêté)."), "modeles": []}
    r = _avec_reveil(m, r, maintenant)
    _noter(m, r["etat"], maintenant, r, modele)
    return r


def _avec_reveil(m, r, maintenant=time.monotonic):
    """Un réveil a été envoyé et la machine ne répond pas encore : état « réveil envoyé » (avec ce qu'il faut vérifier si ça dure). Dès qu'elle répond, la marque du réveil est effacée."""
    with VERROU:
        envoye = REVEIL.get(m["id"])
        if r["etat"] != "injoignable":
            REVEIL.pop(m["id"], None)
            return r
        if envoye is None or maintenant() - envoye > alimentation.ATTENTE_REVEIL_S:
            return r
        depuis = maintenant() - envoye
    detail = _t("Réveil envoyé il y a {} s : une machine met de 30 secondes à quelques minutes à démarrer.").format(round(depuis))
    suite = alimentation.raison_echec(depuis)
    return {"etat": "reveil_envoye", "detail": detail + (" " + suite if suite else ""), "modeles": []}


def reveiller(ident, envoyer=alimentation.envoyer_reveil):
    """Envoie le paquet de réveil à cette machine (il faut son adresse MAC). L'état passe à « réveil envoyé » puis suit la machine : nœud joignable, moteur opérationnel."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    if not m.get("mac"):
        raise ValueError(_t("Pour réveiller cette machine, renseigne son adresse MAC (la liste des cartes réseau : « ipconfig /all » sous Windows, « ip link » sous Linux)."))
    hote = urllib.parse.urlparse(m["adresse"]).hostname or ""
    envoyer(m["mac"], hote)
    with VERROU:
        REVEIL[ident] = time.monotonic()
        SONDES.pop(ident, None)
    journaliser("réveil envoyé à {}".format(m["nom"]))
    return {"ok": True}


def eteindre(ident, annuler=False, ouvrir=None):
    """Demande à cette machine de s'éteindre (dans 30 s, annulable) ou annule la demande. Action EXPLICITE : la machine doit l'avoir autorisée, sinon elle refuse."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    try:
        rep = _json(m, "/api/noeud/eteindre", {"annuler": bool(annuler)}, delai=8, ouvrir=ouvrir)
    except urllib.error.HTTPError as e:
        raise ValueError(_t("Cette machine n'accepte pas d'être éteinte à distance : son propriétaire doit cocher « Autoriser les machines appairées à l'éteindre » dans Réglages > Machines.") if e.code == 403 else _t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None
    journaliser("{} demandée à {}".format("annulation de l'extinction" if annuler else "extinction", m["nom"]))
    SONDES.pop(ident, None)
    return rep


def _noter(m, etat, maintenant, resultat, modele):
    with VERROU:
        SONDES[m["id"]] = (maintenant(), resultat, modele)
        if DERNIER_ETAT.get(m["id"]) != etat:
            DERNIER_ETAT[m["id"]] = etat
            journaliser("{} : {}".format(m["nom"], etat))          # un trait à chaque CHANGEMENT d'état, jamais à chaque sonde


def signaler_panne(m, modele=""):
    """Une demande vers cette machine a échoué : elle passe injoignable tout de suite (la suivante répond en local sans réessayer)."""
    _noter(m, "injoignable", time.monotonic, {"etat": "injoignable", "detail": _t("Pas de réponse (éteinte, hors réseau ou Lutin arrêté)."), "modeles": []}, modele)


def etats(modele="", ouvrir=None):
    """Pour la page Machines : chaque machine avec son état."""
    return [dict(vue(m), **sonder(m, modele, ouvrir)) for m in lire()]


# --------------------------------------------------------------------------- le routage

class FluxNoeud:
    """Les évènements d'une réponse en flux d'un nœud (une ligne JSON par évènement, au format d'Ollama). Fermer ferme la connexion : le nœud arrête de générer."""

    def __init__(self, reponse):
        self.reponse = reponse

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.reponse.close()
        except OSError:
            pass
        return False

    def __iter__(self):
        for brut in self.reponse:
            ligne = brut.decode("utf-8", "replace").strip() if isinstance(brut, (bytes, bytearray)) else str(brut).strip()
            if ligne:
                try:
                    yield json.loads(ligne)
                except ValueError:
                    continue


class Routage:
    """Le moteur local, devant lequel se place une machine : la demande part vers la machine SI elle est opérationnelle pour ce modèle, sinon (ou si elle échoue avant la première réponse) le moteur local répond, en silence.
    Tout le reste (modèles installés, mémoire, installation…) reste celui de ce Lutin."""

    def __init__(self, local, machine, ouvrir=None):
        self.local, self.machine, self.ouvrir = local, machine, ouvrir

    def __getattr__(self, nom):
        return getattr(self.local, nom)

    def _ouvrir_noeud(self, corps, delai):
        if sonder(self.machine, corps.get("model", ""), self.ouvrir)["etat"] != "operationnel":
            return None
        try:
            return requete(self.machine, "/api/noeud/chat", {"corps": corps_autorise(corps)}, delai=min(delai, 30), ouvrir=self.ouvrir)
        except (urllib.error.URLError, OSError, ValueError):
            signaler_panne(self.machine, corps.get("model", ""))
            return None          # repli silencieux

    def chat(self, corps, delai=60):
        rep = self._ouvrir_noeud(dict(corps, stream=False), delai)
        if rep is None:
            return self.local.chat(corps, delai)
        try:
            with rep:
                return json.loads(rep.read(20_000_000).decode("utf-8", "replace") or "{}")
        except (urllib.error.URLError, OSError, ValueError):
            signaler_panne(self.machine, corps.get("model", ""))
            return self.local.chat(corps, delai)

    def chat_flux(self, corps, delai=900):
        rep = self._ouvrir_noeud(dict(corps, stream=True), delai)
        if rep is None:
            return self.local.chat_flux(corps, delai)
        return FluxNoeud(rep)


def acheminer(local, reglages, ouvrir=None):
    """Le moteur à utiliser pour cette demande : `local`, ou `local` derrière la machine choisie dans les réglages (`machine`). Une machine retirée du registre est ignorée."""
    ident = str((reglages or {}).get("machine") or "")
    if not ident:
        return local
    m = trouver(ident)
    return Routage(local, m, ouvrir) if m else local
