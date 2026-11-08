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
import os
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
INFOS_NOEUD = {}          # adresse locale -> (instant, infos du nœud)
INFOS_EN_COURS = {}          # adresse locale -> évènement : un calcul d'infos est en cours
DISTANTS = {"t": 0.0, "v": [], "en_cours": False}          # modèles des autres machines, pour la liste de choix (voir modeles_distants)
CAPACITES_DISTANTES = {}          # (id de machine, modèle) -> (instant, capacités)


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
    if actif:
        threading.Thread(target=cartes_en_cache, daemon=True, name="noeud-cartes-chaud").start()          # la première fois est la plus lente : autant la faire avant l'appairage
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


VIDE_INFOS = {"mac": "", "reveil": {"pret": None, "carte": "", "avertissements": []}, "demarrage": {"installe": False, "possible": False, "docker": False}}


def noeud_infos(ip_locale="", attente=1.5):
    """Ce que ce nœud transmet à la machine qui l'appaire, pour qu'elle n'ait rien à saisir : son adresse MAC, s'il peut être réveillé à distance, si Lutin démarre tout seul chez lui.
    Le calcul lance des programmes (PowerShell sous Windows : plusieurs secondes à froid) : il se fait en arrière-plan et gardé 60 s. L'appairage et les sondes n'attendent jamais plus de `attente` secondes ;
    sans réponse à temps, des informations vides sont rendues et l'autre machine les recevra à sa prochaine sonde (retenir_infos)."""
    maintenant = time.monotonic()
    gardee = INFOS_NOEUD.get(ip_locale)
    perimee = not gardee or maintenant - gardee[0] >= 60
    evenement = None
    if perimee:
        with VERROU:
            evenement = INFOS_EN_COURS.get(ip_locale)
            if evenement is None:
                evenement = INFOS_EN_COURS[ip_locale] = threading.Event()

                def travail(ev=evenement):
                    try:
                        INFOS_NOEUD[ip_locale] = (time.monotonic(), _calculer_infos(ip_locale))
                    except Exception:  # noqa: BLE001  (un renseignement de plus : jamais un appairage qui échoue)
                        pass
                    finally:
                        with VERROU:
                            INFOS_EN_COURS.pop(ip_locale, None)
                        ev.set()
                threading.Thread(target=travail, daemon=True, name="noeud-infos").start()
        if not gardee:
            evenement.wait(attente)
            gardee = INFOS_NOEUD.get(ip_locale)
    return gardee[1] if gardee else VIDE_INFOS


CARTES = {"t": -999.0, "v": None}


def cartes_en_cache():
    """Les cartes réseau de cette machine (le plus lent à lire : PowerShell sous Windows), gardées 60 s."""
    if CARTES["v"] is None or time.monotonic() - CARTES["t"] > 60:
        CARTES.update(t=time.monotonic(), v=alimentation.cartes_reseau())
    return CARTES["v"]


def _calculer_infos(ip_locale):
    docker = os.environ.get("LUTIN_DOCKER") == "1"
    try:
        reveil = alimentation.etat_reveil(ip_locale, cartes=None if docker else cartes_en_cache(), en_docker=docker)
    except Exception:  # noqa: BLE001  (un renseignement de plus : jamais un appairage qui échoue)
        reveil = {"mac": "", "carte": "", "pret": None, "avertissements": []}
    try:
        demarrage = alimentation.etat_demarrage()
    except Exception:  # noqa: BLE001
        demarrage = {"installe": False, "possible": False}
    infos = {"mac": reveil.get("mac", ""), "reveil": {k: reveil.get(k) for k in ("pret", "carte", "avertissements")},
             "demarrage": {"installe": bool(demarrage.get("installe")), "possible": bool(demarrage.get("possible")), "docker": docker}}
    return infos


def noeud_echanger(code, nom_demandeur, ip_locale=""):
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
    return dict(noeud_infos(ip_locale), jeton=jeton, id=n["id"], nom=socket.gethostname()[:40])


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


DROITS = ("conversations", "skills", "memoire")          # ce qu'une machine appairée peut LIRE si le propriétaire de celle-ci l'a coché (jamais écrire)
PARTAGE_MAX_OCTETS = 4_000_000


def noeud_droit(droit, actif):
    """Le propriétaire de CE nœud autorise (ou non) les machines appairées à lire ses conversations, ses skills ou sa mémoire. Décoché par défaut ; journalisé."""
    if droit not in DROITS:
        raise ValueError(_t("Droit inconnu."))
    with VERROU:
        n = noeud()
        n.setdefault("droits", {})[droit] = bool(actif)
        _ecrire("noeud.json", n)
    journaliser("partage de {} avec les machines appairées : {}".format(droit, "autorisé" if actif else "interdit"))
    return noeud_vue()


def noeud_droits():
    d = noeud().get("droits") or {}
    return {k: bool(d.get(k)) for k in DROITS}


def _conversation_partageable(ident):
    """Une conversation de ce nœud prête à être copiée ailleurs : sans images ni fichiers joints (ils restent ici), taille bornée."""
    from . import moteur as _m
    c = _m.conv_lire(ident)
    messages = []
    for m in c.get("messages", []):
        if isinstance(m, dict):
            messages.append({k: v for k, v in m.items() if k not in ("images", "medias", "medias_fichiers", "fichiers_joints", "pieces")})
    sortie = {"id": c["id"], "titre": c.get("titre", ""), "date": c.get("date", ""), "maj": c.get("maj", c.get("date", "")), "resume": c.get("resume", ""), "messages": messages}
    if len(json.dumps(sortie, ensure_ascii=False)) > PARTAGE_MAX_OCTETS:
        raise ValueError(_t("Cette conversation est trop volumineuse pour être copiée."))
    return sortie


def noeud_partager(genre, corps):
    """Ce que ce nœud donne à lire à une machine appairée. PermissionError si le propriétaire ne l'a pas autorisé. genre : conversations, conversation, skills, skill, memoire."""
    from . import moteur as _m
    droit = {"conversations": "conversations", "conversation": "conversations", "skills": "skills", "skill": "skills", "memoire": "memoire"}.get(genre)
    if droit is None:
        raise ValueError(_t("Demande inconnue."))
    if not noeud_droits()[droit]:
        raise PermissionError(droit)
    if genre == "conversations":
        return {"conversations": [{"id": c["id"], "titre": c.get("titre", ""), "maj": c.get("maj", ""), "messages": c.get("messages", 0)} for c in _m.conv_liste() if not c.get("origine")][:300]}
    if genre == "conversation":
        return {"conversation": _conversation_partageable(str(corps.get("id", "")))}
    if genre == "skills":
        return {"skills": [{"nom": nom, "titre": titre} for nom, titre in _m.lister_skills()][:300]}
    if genre == "skill":
        nom = str(corps.get("nom", ""))
        return {"nom": nom, "texte": _m.lire_skill(nom)}
    return {"memoire": {nom: _m.lire_memoire(nom) for nom in ("CONTEXTE.md", "MEMOIRE.md")}}


def noeud_vue():
    n = noeud()
    return {"actif": n["actif"], "id": n["id"], "droits": noeud_droits(), "extinction": bool(n.get("extinction")), "extinction_en_attente": alimentation.extinction_en_attente(),
            "autorisees": [{"nom": j["nom"], "date": j["date"]} for j in n["jetons"]]}


def noeud_charge(locale_occupee, distantes):
    """Ce que le nœud dit de sa charge : mémoire, et qui utilise son moteur en ce moment (son utilisateur, des machines appairées). Lecture seule, rien de plus."""
    from . import moteur as _m
    ram, vram = _m.memoire_vive(), _m.memoire_video()
    return {"locale_occupee": bool(locale_occupee), "distantes": int(distantes),
            "ram": {"total": ram["total"], "libre": ram["libre"]} if ram else None, "vram": {"total": vram["total"], "libre": vram["libre"], "nom": vram["nom"]} if vram else None}


def noeud_etat(moteur, modeles, ip_locale="", charge=None):
    """Ce que le nœud répond à `GET /api/noeud/etat` : de quoi savoir s'il est joignable et si son moteur peut faire tourner le modèle voulu, plus son adresse MAC, son aptitude au réveil et son démarrage automatique."""
    return dict(noeud_infos(ip_locale), id=noeud()["id"], moteur=moteur.id, moteur_nom=moteur.nom, actif=bool(modeles.get("actif")), modeles=sorted(modeles.get("installes", []))[:500], charge=charge, droits=noeud_droits())


def noeud_capacites(moteur, modele):
    """Les capacités (outils, vision, réflexion…) d'un modèle de CE nœud, ou None quand son moteur ne le dit pas."""
    caps = moteur.capacites(str(modele or ""))
    return None if caps is None else sorted(caps)


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
    mac_auto = alimentation_mac(rep.get("mac"))
    with VERROU:
        liste = [m for m in lire() if m["id"] != rep["id"]]
        m = {"id": rep["id"], "nom": (str(nom).strip() or str(rep.get("nom") or "machine"))[:40], "adresse": adresse, "jeton": rep["jeton"], "mac": mac or mac_auto, "ajoutee": time.strftime("%Y-%m-%d %H:%M"),
             "mac_auto": bool(not mac and mac_auto), "reveil": rep.get("reveil") if isinstance(rep.get("reveil"), dict) else {}, "demarrage": rep.get("demarrage") if isinstance(rep.get("demarrage"), dict) else {}}
        liste.append(m)
        _ecrire_registre(liste)
    journaliser("machine ajoutée : {} ({}){}".format(m["nom"], adresse, ", adresse MAC reçue de la machine" if m["mac_auto"] else ""))
    return vue(m)


def alimentation_mac(mac):
    return alimentation.normaliser_mac(mac)


def retenir_infos(m, rep):
    """Garde ce que le nœud dit de lui (MAC, réveil, démarrage) : la page peut ainsi avertir même quand la machine est éteinte. L'adresse MAC reçue complète une adresse manquante, sans jamais écraser celle que tu as saisie."""
    reveil = rep.get("reveil") if isinstance(rep.get("reveil"), dict) else None
    demarrage = rep.get("demarrage") if isinstance(rep.get("demarrage"), dict) else None
    mac = alimentation_mac(rep.get("mac"))
    if reveil is None and demarrage is None and not mac:
        return
    with VERROU:
        liste = lire()
        for x in liste:
            if x["id"] != m["id"]:
                continue
            avant = (x.get("mac"), x.get("reveil"), x.get("demarrage"))
            if mac and not x.get("mac"):
                x["mac"], x["mac_auto"] = mac, True
                journaliser("{} : adresse MAC reçue de la machine ({})".format(x["nom"], mac))
            if reveil is not None:
                x["reveil"] = reveil
            if demarrage is not None:
                x["demarrage"] = demarrage
            if avant != (x.get("mac"), x.get("reveil"), x.get("demarrage")):
                _ecrire_registre(liste)
            m.update({k: x.get(k) for k in ("mac", "reveil", "demarrage", "mac_auto")})
            return


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


def avertissements(m):
    """Ce qui empêche (ou risque d'empêcher) de réveiller cette machine puis de s'en servir, d'après ce qu'elle a elle-même dit : adresse MAC, Wake-on-LAN, démarrage de Lutin."""
    sortie = []
    if not m.get("mac"):
        sortie.append(_t("Adresse MAC inconnue : elle sera reçue de la machine dès qu'elle aura répondu une fois. Sans elle, impossible de la réveiller."))
    sortie += [str(x) for x in ((m.get("reveil") or {}).get("avertissements") or [])][:4]
    d = m.get("demarrage") or {}
    if d.get("docker"):
        sortie.append(_t("Cette machine fait tourner Lutin dans Docker : pour qu'il soit là après un réveil, le conteneur doit avoir « restart: unless-stopped » et Docker doit démarrer avec la machine."))
    elif d and d.get("possible") and not d.get("installe"):
        sortie.append(_t("Lutin ne démarre pas tout seul sur cette machine : une fois réveillée, personne ne le lance et elle restera injoignable. Sur cette machine : Réglages > Machines > « Démarrer Lutin à l'ouverture de ma session » (et auto-connexion Windows pour un PC qui démarre sans personne)."))
    return sortie


def vue(m):
    """Une machine pour la page : jamais son jeton."""
    v = {k: m.get(k, "") for k in ("id", "nom", "adresse", "mac", "ajoutee")}
    v["mac_auto"] = bool(m.get("mac_auto"))
    v["avertissements"] = avertissements(m)
    return v


# --------------------------------------------------------------------------- l'état d'une machine (quatre états)

def sonder(m, modele="", ouvrir=None, maintenant=time.monotonic, force=False):
    """{etat, detail, modeles} : injoignable · joignable (le nœud répond mais n'a pas ce modèle ou son moteur est arrêté) · operationnel. Gardé 10 s. Vérifie que c'est bien la machine appairée."""
    with VERROU:
        gardee = SONDES.get(m["id"])
        if gardee and not force and maintenant() - gardee[0] < VALIDITE_SONDE_S and gardee[2] == modele:
            return gardee[1]
    charge, droits = None, {}
    try:
        rep = _json(m, "/api/noeud/etat", ouvrir=ouvrir)
        if rep.get("id") == m["id"]:
            retenir_infos(m, rep)
            charge = rep.get("charge") if isinstance(rep.get("charge"), dict) else None
            droits = {k: bool((rep.get("droits") or {}).get(k)) for k in DROITS}
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
    r = _avec_reveil(m, dict(r, charge=charge, droits=droits), maintenant)
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
    return {"ok": True, "avertissements": [a for a in [alimentation.emission_limitee()] + avertissements(m) if a][:4]}          # le paquet est parti, mais on dit ce qui risque de l'empêcher de marcher


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


# --------------------------------------------------------------------------- ce que les autres machines partagent : conversations, skills, mémoire (copies locales, à ta demande)

CONVERSATIONS = {"t": 0.0, "v": [], "en_cours": False}


def demander_partage(m, genre, **corps):
    """Lit chez l'autre machine ce qu'elle partage. ValueError avec la marche à suivre si son propriétaire ne l'a pas autorisé."""
    try:
        return _json(m, "/api/noeud/partage", dict(corps, genre=genre), delai=20)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ValueError(_t("La machine « {} » ne partage pas cela : sur elle, Réglages > Machines > « Partager avec les machines appairées », puis coche la case voulue.").format(m.get("nom", "?"))) from None
        raise ValueError(_t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None


def _rafraichir_conversations():
    liste = []
    for m in lire():
        try:
            if not sonder(m, "").get("droits", {}).get("conversations"):
                continue
            for c in demander_partage(m, "conversations").get("conversations", []):
                if isinstance(c, dict) and RE_IDENT_CONV.match(str(c.get("id", ""))):
                    liste.append({"machine": m["id"], "machine_nom": m["nom"], "id": c["id"], "titre": str(c.get("titre", ""))[:120], "maj": str(c.get("maj", ""))[:30], "messages": int(c.get("messages") or 0)})
        except (ValueError, TypeError):
            continue
    with VERROU:
        CONVERSATIONS.update(t=time.monotonic(), v=liste, en_cours=False)


RE_IDENT_CONV = re.compile(r"^[0-9a-f]{8}$")


def conversations_distantes(attente=False):
    """Les conversations des machines appairées qui les partagent. Rendues tout de suite depuis la mémoire (la liste ne doit jamais attendre une machine éteinte) ; mise à jour en arrière-plan toutes les 30 s."""
    if not lire():
        return []
    with VERROU:
        vieux = time.monotonic() - CONVERSATIONS["t"] > 30
        lancer = vieux and not CONVERSATIONS["en_cours"]
        if lancer:
            CONVERSATIONS["en_cours"] = True
    if lancer:
        if attente:
            _rafraichir_conversations()
        else:
            def travail():
                try:
                    _rafraichir_conversations()
                except Exception:  # noqa: BLE001
                    with VERROU:
                        CONVERSATIONS["en_cours"] = False
            threading.Thread(target=travail, daemon=True, name="machines-conversations").start()
    ids = {m["id"] for m in lire()}
    importees = _registre_import("conversations_importees.json")
    sortie = []
    for c in CONVERSATIONS["v"]:
        if c["machine"] not in ids:
            continue
        deja = importees.get("{}:{}".format(c["machine"], c["id"]))
        deja = deja if isinstance(deja, dict) else {"id": deja} if deja else None
        sortie.append(dict(c, locale=deja["id"] if deja else "", plus_recente=bool(deja and str(c.get("maj", "")) > str(deja.get("maj", "")))))
    return sortie


def _registre_import(nom):
    return _lire(nom, {})


def importer_conversation(ident, id_distant):
    """Copie une conversation d'une machine appairée dans CELLE-CI, pour la continuer ici (avec ses skills, sa mémoire et ses modèles). La copie garde son origine ; l'original n'est jamais touché.
    Déjà importée : mise à jour si l'original a avancé et que la copie n'a pas bougé ; sinon la copie locale est gardée. {id, etat : nouvelle | a_jour | mise_a_jour | divergente}."""
    from . import moteur as _m
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    if not RE_IDENT_CONV.match(str(id_distant)):
        raise ValueError(_t("Conversation inconnue."))
    distante = demander_partage(m, "conversation", id=id_distant).get("conversation")
    if not isinstance(distante, dict) or not isinstance(distante.get("messages"), list):
        raise ValueError(_t("Réponse inattendue de la machine."))
    cle = "{}:{}".format(ident, id_distant)
    registre = _registre_import("conversations_importees.json")
    entree = registre.get(cle)
    local_id = entree.get("id") if isinstance(entree, dict) else entree
    if local_id:
        try:
            locale = _m.conv_lire(local_id)
        except ValueError:
            locale, local_id = None, None
        if locale is not None:
            origine = locale.get("origine") or {}
            if str(distante.get("maj", "")) <= str(origine.get("maj_distante", "")):
                return {"id": local_id, "etat": "a_jour"}
            if len(locale.get("messages", [])) != int(origine.get("messages_importes") or -1):
                return {"id": local_id, "etat": "divergente"}          # elle a continué ici depuis la copie : on ne l'écrase pas
            locale["messages"], locale["resume"] = distante["messages"], distante.get("resume", "")
            locale["origine"] = dict(origine, maj_distante=str(distante.get("maj", "")), messages_importes=len(distante["messages"]))
            _m.conv_ecrire(locale)
            registre[cle] = {"id": local_id, "maj": str(distante.get("maj", "")), "n": len(distante["messages"])}
            _ecrire("conversations_importees.json", registre)
            return {"id": local_id, "etat": "mise_a_jour"}
    nouvelle = _m.conv_nouvelle()
    nouvelle.update(titre=str(distante.get("titre", ""))[:120] or _t("Conversation importée"), date=str(distante.get("date", "")) or nouvelle["date"], messages=distante["messages"], resume=distante.get("resume", ""),
                    origine={"machine": m["nom"], "machine_id": ident, "id": id_distant, "maj_distante": str(distante.get("maj", "")), "messages_importes": len(distante["messages"])})
    _m.conv_ecrire(nouvelle)
    registre[cle] = {"id": nouvelle["id"], "maj": str(distante.get("maj", "")), "n": len(distante["messages"])}
    _ecrire("conversations_importees.json", registre)
    journaliser("conversation importée de {} : {}".format(m["nom"], nouvelle["titre"]))
    return {"id": nouvelle["id"], "etat": "nouvelle"}


def importer_skills(ident):
    """Ajoute à CETTE machine les skills de l'autre qui n'y sont pas (les deux jeux se cumulent). Un skill qui existe déjà ici n'est jamais écrasé, sauf s'il vient de cette machine et n'a pas été modifié depuis.
    {ajoutes, mis_a_jour, deja_la}."""
    import hashlib
    from . import moteur as _m
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    origines = _registre_import("skills_origine.json")
    ajoutes = mis = deja = 0
    for s in demander_partage(m, "skills").get("skills", []):
        nom = str((s or {}).get("nom", ""))
        try:
            texte = str(demander_partage(m, "skill", nom=nom).get("texte", ""))
            empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
            existe = True
            try:
                local = _m.lire_skill(nom)
            except OSError:
                existe, local = False, ""
            if not existe:
                _m.ecrire_skill(nom, texte)
                origines[nom] = {"machine": m["nom"], "empreinte": empreinte}
                ajoutes += 1
            elif (origines.get(nom) or {}).get("machine") == m["nom"] and hashlib.sha256(local.encode("utf-8")).hexdigest() == origines[nom].get("empreinte") and empreinte != origines[nom].get("empreinte"):
                _m.ecrire_skill(nom, texte)
                origines[nom]["empreinte"] = empreinte
                mis += 1
            else:
                deja += 1
        except (ValueError, OSError):
            deja += 1
    _ecrire("skills_origine.json", origines)
    journaliser("skills importés de {} : {} ajoutés, {} mis à jour, {} déjà là".format(m["nom"], ajoutes, mis, deja))
    return {"ajoutes": ajoutes, "mis_a_jour": mis, "deja_la": deja}


def importer_memoire(ident):
    """Ajoute à la mémoire de CETTE machine les notes de l'autre qu'elle n'a pas (sous un titre « Depuis <machine> »). Le profil (CONTEXTE.md) n'est copié que s'il est vide ici. {notes_ajoutees, profil_copie}."""
    from . import moteur as _m
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    distante = demander_partage(m, "memoire").get("memoire") or {}
    local = _m.lire_memoire("MEMOIRE.md")
    connues = {re.sub(r"\W+", " ", ligne).strip().lower() for ligne in local.splitlines()}
    neuves = []
    for ligne in str(distante.get("MEMOIRE.md", "")).splitlines():
        brut = ligne.strip()
        cle = re.sub(r"\W+", " ", brut).strip().lower()
        if brut and not brut.startswith("#") and cle and cle not in connues:
            neuves.append(brut)
            connues.add(cle)
    if neuves:
        bloc = "\n\n## {}\n{}\n".format(_t("Depuis {} ({})").format(m["nom"], time.strftime("%Y-%m-%d")), "\n".join(neuves))
        _m.ecrire_memoire("MEMOIRE.md", (local.rstrip() + bloc)[-59000:])
    profil = False
    if str(distante.get("CONTEXTE.md", "")).strip() and not _m.lire_memoire("CONTEXTE.md").strip():
        _m.ecrire_memoire("CONTEXTE.md", str(distante["CONTEXTE.md"])[:59000])
        profil = True
    journaliser("mémoire importée de {} : {} note(s)".format(m["nom"], len(neuves)))
    return {"notes_ajoutees": len(neuves), "profil_copie": profil}


# --------------------------------------------------------------------------- les modèles des autres machines (pour les choisir comme les siens)

def _rafraichir_distants():
    liste = []
    avant = {d["id"]: d for d in DISTANTS["v"]}
    for m in lire():
        r = sonder(m, "")
        modeles = list(r.get("modeles") or []) or list((avant.get(m["id"]) or {}).get("modeles") or [])          # une machine éteinte garde sa dernière liste (grisée dans le choix)
        if modeles:
            liste.append({"id": m["id"], "nom": m["nom"], "etat": r["etat"], "modeles": modeles})
    with VERROU:
        DISTANTS.update(t=time.monotonic(), v=liste, en_cours=False)


def modeles_distants(attente=False):
    """Les modèles des machines appairées qui répondent : [{id, nom, etat, modeles}]. Ce qui est gardé en mémoire est rendu tout de suite (la page ne doit jamais attendre une machine éteinte) ;
    une mise à jour part en arrière-plan quand la dernière date de plus de 15 s. `attente=True` (tests) la fait sur place."""
    if not lire():
        return []
    with VERROU:
        vieux = time.monotonic() - DISTANTS["t"] > 15
        lancer = vieux and not DISTANTS["en_cours"]
        if lancer:
            DISTANTS["en_cours"] = True
    if lancer:
        if attente:
            _rafraichir_distants()
        else:
            def travail():
                try:
                    _rafraichir_distants()
                except Exception:  # noqa: BLE001
                    with VERROU:
                        DISTANTS["en_cours"] = False
            threading.Thread(target=travail, daemon=True, name="machines-modeles").start()
    ids = {m["id"] for m in lire()}
    return [dict(d) for d in DISTANTS["v"] if d["id"] in ids]


def modele_distant(reglages, installes_locaux):
    """La machine qui porte le modèle choisi quand celui-ci n'existe QUE là-bas (réglages `machine` + `modele`), sinon None."""
    ident = str((reglages or {}).get("machine") or "")
    modele = str((reglages or {}).get("modele") or "")
    if not ident or not modele or modele in (installes_locaux or []):
        return None
    m = trouver(ident)
    if m is None:
        return None
    gardee = next((d for d in DISTANTS["v"] if d["id"] == ident), None)
    return m if gardee is None or modele in gardee["modeles"] else None


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

    def _modele_local(self, modele):
        try:
            return modele in self.local.modeles().get("installes", [])
        except Exception:  # noqa: BLE001
            return True

    def capacites(self, modele):
        """Les capacités du modèle : celles du moteur local s'il l'a, sinon celles que la machine distante déclare (gardées 5 minutes)."""
        if self._modele_local(modele):
            return self.local.capacites(modele)
        cle = (self.machine["id"], modele)
        gardee = CAPACITES_DISTANTES.get(cle)
        if gardee and time.monotonic() - gardee[0] < 300:
            return gardee[1]
        try:
            rep = _json(self.machine, "/api/noeud/capacites", {"modele": modele}, ouvrir=self.ouvrir)
            caps = set(rep["capacites"]) if isinstance(rep.get("capacites"), list) else None
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return None
        CAPACITES_DISTANTES[cle] = (time.monotonic(), caps)
        return caps

    def _repli(self, corps):
        """Le moteur local répond à la place de la machine, en silence — sauf si le modèle n'existe que sur la machine : une erreur claire vaut mieux qu'un « modèle introuvable » du moteur local."""
        modele = corps.get("model", "")
        connu_la_bas = next((d for d in DISTANTS["v"] if d["id"] == self.machine["id"] and modele in d["modeles"]), None)
        if connu_la_bas is not None and not self._modele_local(modele):
            raise ValueError(_t("Le modèle « {} » n'existe que sur la machine « {} », qui ne répond pas pour l'instant (éteinte, hors réseau ou Lutin arrêté). Réveille-la dans Réglages > Machines, ou choisis un modèle de cette machine-ci.").format(modele, self.machine.get("nom", "?")))

    def _occupee(self, corps):
        """La machine est occupée (trop de demandes à la fois) : le moteur d'ici répond si le modèle y est, sinon on dit de réessayer — jamais « injoignable »."""
        modele = corps.get("model", "")
        if not self._modele_local(modele):
            raise ValueError(_t("La machine « {} » répond déjà à d'autres demandes : réessaie dans un instant.").format(self.machine.get("nom", "?")))

    def _ouvrir_noeud(self, corps, delai):
        if sonder(self.machine, corps.get("model", ""), self.ouvrir)["etat"] != "operationnel":
            self._repli(corps)
            return None
        try:
            # Le nœud répond tout de suite (état vérifié juste avant) mais peut attendre son moteur : son propre utilisateur, un modèle à charger. Le délai est donc celui de la demande, pas 30 s.
            return requete(self.machine, "/api/noeud/chat", {"corps": corps_autorise(corps)}, delai=delai, ouvrir=self.ouvrir)
        except urllib.error.HTTPError as e:
            if e.code == 429:          # la machine répond déjà à d'autres demandes : elle n'est pas en panne
                self._occupee(corps)
                return None
            signaler_panne(self.machine, corps.get("model", ""))
            self._repli(corps)
            return None
        except (urllib.error.URLError, OSError, ValueError):
            signaler_panne(self.machine, corps.get("model", ""))
            self._repli(corps)
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
