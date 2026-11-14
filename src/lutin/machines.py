"""Machines (décision D7) : chaque Lutin est un nœud, sans agent séparé.

Le POSTE à carte graphique (le nœud) prête le moteur de sa machine ; le PETIT PC (le principal) route ses demandes vers lui et, s'il est injoignable, répond avec son moteur local, EN SILENCE.

Ce que le nœud accepte, et rien d'autre :
- il est éteint par défaut ; le propriétaire l'active (onglet Machines) et seulement si le niveau d'accès n'est pas « cette machine seulement » ;
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

from . import power
from .i18n import t as _t

ETATS = ("injoignable", "reveil_envoye", "joignable", "operationnel")
DUREE_CODE_S = 300
CODES_MAX = 3
VALIDITE_SONDE_S = 10          # un constat d'état est gardé ce temps : pas de sonde à chaque message
DELAI_SONDE_REVEIL_S = 3.0
VERIFICATION_ALLUMEE_S = 4          # « le système de la machine répond-il ? » est regardé au plus toutes les 4 s pendant un réveil
VALIDITE_SONDE_ATTENTE_S = 2          # une machine pas encore opérationnelle (éteinte, qui démarre) est resondée vite : on la voit s'allumer sans attendre
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
ECHEC_REVEIL = {}          # id de machine -> texte : le réveil n'a pas abouti dans le délai (cinq minutes) ; effacé au prochain réveil ou dès que la machine répond
ALLUMEE = {}          # id de machine -> (instant, verdict) : « le système répond » constaté pendant un réveil (gardé quelques secondes : la vérification coûte une ou deux secondes)
DEPUIS_ALLUMEE = {}          # id de machine -> instant où elle a été vue allumée pour la première fois pendant ce réveil
HOTE_ALLUME = None          # remplaçable (tests) ; par défaut alimentation.hote_allume
A_REPONDU = {}          # machines dont Lutin a répondu pendant ce réveil (pour dire « il redémarre » s'il disparaît de nouveau)
REPONDU = {}          # id de machine -> instant où Lutin a répondu pour la première fois pendant ce réveil (sans interruption depuis)
STABLE_REPONSE_S = 25          # le réveil n'est « fini » que quand Lutin répond sans interruption depuis ce temps : un Lutin qui redémarre juste après avoir répondu ne fait pas retomber la machine à « éteinte »
_REVEILS_REPRIS = {"fait": False}
INFOS_NOEUD = {}          # adresse locale -> (instant, infos du nœud)
INFOS_EN_COURS = {}          # adresse locale -> évènement : un calcul d'infos est en cours
DISTANTS = {"t": 0.0, "v": [], "en_cours": False}          # modèles des autres machines, pour la liste de choix (voir modeles_distants)
ARRET = {}          # id de machine -> instant où on lui a demandé de s'éteindre (le suivi « extinction » de la page)
MAJ_DISTANTE = {}          # id de machine -> (instant, version d'avant) : une mise à jour lui a été demandée
SYNCHRO = {}          # id de machine -> {"modeles": bool, "conv": bool} : ce qui a été relu depuis qu'elle répond
DELAI_ARRET_S = 150
DELAI_SYNCHRO_S = 90
DELAI_MAJ_S = 400
CAPACITES_DISTANTES = {}          # (id de machine, modèle) -> (instant, capacités)


def dossier():
    if DOSSIER is not None:
        return Path(DOSSIER)
    from . import core as _m
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
        CARTES.update(t=time.monotonic(), v=power.cartes_reseau())
    return CARTES["v"]


def _calculer_infos(ip_locale):
    docker = os.environ.get("LUTIN_DOCKER") == "1"
    try:
        reveil = power.etat_reveil(ip_locale, cartes=None if docker else cartes_en_cache(), en_docker=docker)
    except Exception:  # noqa: BLE001  (un renseignement de plus : jamais un appairage qui échoue)
        reveil = {"mac": "", "carte": "", "pret": None, "avertissements": []}
    try:
        demarrage = power.etat_demarrage()
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


def noeud_autoriser_piloter(autoriser):
    """Les machines appairées peuvent-elles mener des conversations SUR celle-ci (le tour entier s'exécute ici : modèles, outils, addons, fichiers) ? Décoché par défaut : le propriétaire de cette machine le décide.
    Les règles de cette machine s'appliquent (dossiers autorisés, accords demandés) ; chaque tour est journalisé."""
    with VERROU:
        n = noeud()
        n["piloter"] = bool(autoriser)
        _ecrire("noeud.json", n)
    journaliser("conversations pilotées par une machine appairée : {}".format("autorisées" if autoriser else "interdites"))
    return noeud_vue()


def noeud_autoriser_maj(autoriser):
    """Les machines appairées peuvent-elles mettre Lutin à jour sur CETTE machine ? Décoché par défaut : c'est le propriétaire de cette machine qui le décide."""
    with VERROU:
        n = noeud()
        n["maj"] = bool(autoriser)
        _ecrire("noeud.json", n)
    journaliser("mise à jour par une machine appairée : {}".format("autorisée" if autoriser else "interdite"))
    return noeud_vue()


DROITS_DEMANDABLES = ("piloter", "maj", "extinction")          # ce qu'une machine appairée peut DEMANDER (le propriétaire de celle-ci accepte ou refuse, jamais automatiquement)
LIMITE_MEMOIRE = 59000          # caractères : la limite de ecrire_memoire (60 000) moins une marge
MAX_DEMANDES = 20


def noeud_demander(machine, droit):
    """Une machine appairée demande un droit (mener des conversations ici, mettre Lutin à jour, éteindre). Rien n'est accordé : la demande attend la réponse du propriétaire de CETTE machine."""
    if droit not in DROITS_DEMANDABLES:
        raise ValueError(_t("Droit inconnu."))
    with VERROU:
        n = noeud()
        if n.get(droit):
            return {"deja": True}
        demandes = [d for d in n.get("demandes", []) if not (d.get("machine") == machine and d.get("droit") == droit)]
        demandes.append({"machine": str(machine)[:40], "droit": droit, "date": time.strftime("%Y-%m-%d %H:%M")})
        n["demandes"] = demandes[-MAX_DEMANDES:]
        _ecrire("noeud.json", n)
    journaliser("{} demande l'autorisation « {} » (en attente de ta réponse)".format(machine, droit))
    return {"deja": False}


def noeud_repondre_demande(machine, droit, accepter):
    """Le propriétaire de CETTE machine accepte ou refuse une demande. Accepter active le droit (décochable à tout moment) ; refuser l'efface."""
    if droit not in DROITS_DEMANDABLES:
        raise ValueError(_t("Droit inconnu."))
    with VERROU:
        n = noeud()
        restantes = [d for d in n.get("demandes", []) if not (d.get("machine") == machine and d.get("droit") == droit)]
        if len(restantes) == len(n.get("demandes", [])):
            raise ValueError(_t("Cette demande n'existe plus."))
        n["demandes"] = restantes
        if accepter:
            n[droit] = True
        _ecrire("noeud.json", n)
    journaliser("demande « {} » de {} : {}".format(droit, machine, "acceptée" if accepter else "refusée"))
    return noeud_vue()


DROITS = ("skills", "memoire")          # ce qu'une machine appairée peut LIRE si le propriétaire de celle-ci l'a coché (jamais écrire) ; les conversations, elles, se pilotent (voir noeud_autoriser_piloter)


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


def noeud_partager(genre, corps):
    """Ce que ce nœud donne à lire à une machine appairée. PermissionError si le propriétaire ne l'a pas autorisé. genre : conversations (la liste, pour les piloter), skills, skill, memoire."""
    from . import core as _m
    droit = {"conversations": "piloter", "skills": "skills", "skill": "skills", "memoire": "memoire"}.get(genre)
    if droit is None:
        raise ValueError(_t("Demande inconnue."))
    if not (noeud().get("piloter") if droit == "piloter" else noeud_droits()[droit]):
        raise PermissionError(droit)
    if genre == "conversations":
        return {"conversations": [{"id": c["id"], "titre": c.get("titre", ""), "maj": c.get("maj", ""), "messages": c.get("messages", 0)} for c in _m.conv_liste() if not c.get("origine")][:300]}
    if genre == "skills":
        return {"skills": [{"nom": nom, "titre": titre} for nom, titre in _m.lister_skills()][:300]}
    if genre == "skill":
        nom = str(corps.get("nom", ""))
        return {"nom": nom, "texte": _m.lire_skill(nom)}
    return {"memoire": {nom: _m.lire_memoire(nom) for nom in ("CONTEXTE.md", "MEMOIRE.md")}}


def noeud_vue():
    n = noeud()
    return {"actif": n["actif"], "id": n["id"], "droits": noeud_droits(), "extinction": bool(n.get("extinction")), "maj": bool(n.get("maj")), "piloter": bool(n.get("piloter")), "extinction_en_attente": power.extinction_en_attente(),
            "demandes": [dict(d) for d in n.get("demandes", [])], "autorisees": [{"nom": j["nom"], "date": j["date"]} for j in n["jetons"]]}


def noeud_charge(locale_occupee, distantes):
    """Ce que le nœud dit de sa charge : mémoire, et qui utilise son moteur en ce moment (son utilisateur, des machines appairées). Lecture seule, rien de plus."""
    from . import core as _m
    ram, vram = _m.memoire_vive(), _m.memoire_video()
    return {"locale_occupee": bool(locale_occupee), "distantes": int(distantes),
            "ram": {"total": ram["total"], "libre": ram["libre"]} if ram else None, "vram": {"total": vram["total"], "libre": vram["libre"], "nom": vram["nom"]} if vram else None}


def noeud_etat(moteur, modeles, ip_locale="", charge=None, demandeur=""):
    """Ce que le nœud répond à `GET /api/noeud/etat` : de quoi savoir s'il est joignable et si son moteur peut faire tourner le modèle voulu, plus son adresse MAC, son aptitude au réveil et son démarrage automatique."""
    from . import core as _m
    n = noeud()
    return dict(noeud_infos(ip_locale), id=n["id"], moteur=moteur.id, moteur_nom=moteur.nom, actif=bool(modeles.get("actif")), modeles=sorted(modeles.get("installes", []))[:500], charge=charge, droits=noeud_droits(),
                version=str(_m.VERSION), agir={"extinction": bool(n.get("extinction")), "maj": bool(n.get("maj")), "piloter": bool(n.get("piloter"))},
                demandes=sorted({d["droit"] for d in n.get("demandes", []) if demandeur and d.get("machine") == demandeur}))          # seulement les demandes DE celui qui interroge


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
    return power.normaliser_mac(mac)


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
        sortie.append(_t("Lutin ne démarre pas tout seul sur cette machine : une fois réveillée, personne ne le lance et elle restera injoignable. Sur cette machine : onglet Machines > « Démarrer Lutin à l'ouverture de ma session » (et auto-connexion Windows pour un PC qui démarre sans personne)."))
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
        if gardee and not force and maintenant() - gardee[0] < (VALIDITE_SONDE_S if gardee[1].get("etat") == "operationnel" else VALIDITE_SONDE_ATTENTE_S) and gardee[2] == modele:
            return gardee[1]
    charge, droits, version, agir, allumee, demandes = None, {}, "", {}, False, []
    _reprendre_reveils()
    try:
        rep = _json(m, "/api/noeud/etat", ouvrir=ouvrir, delai=DELAI_SONDE_REVEIL_S if m["id"] in REVEIL else DELAI_SONDE_S)          # une machine qui vient de démarrer répond lentement : plus de patience pendant un réveil
        if rep.get("id") == m["id"]:
            retenir_infos(m, rep)
            charge = rep.get("charge") if isinstance(rep.get("charge"), dict) else None
            droits = {k: bool((rep.get("droits") or {}).get(k)) for k in DROITS}
            version = str(rep.get("version") or "")[:30]
            agir = {k: bool((rep.get("agir") or {}).get(k)) for k in ("extinction", "maj", "piloter")}
            demandes = [d for d in (rep.get("demandes") or []) if d in DROITS_DEMANDABLES]
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
    except (urllib.error.URLError, OSError, ValueError) as e:
        allumee = _hote_allume(e) or _allumee_pendant_reveil(m, maintenant)
        r = {"etat": "injoignable", "detail": _t("Pas de réponse (éteinte, hors réseau ou Lutin arrêté)."), "modeles": []}
    r = _avec_reveil(m, dict(r, charge=charge, droits=droits, version=version, agir=agir, demandes=demandes, maj_disponible=_maj_disponible(version)), maintenant, allumee)
    r = dict(r, **_etape(m, r, allumee))
    _noter(m, r["etat"], maintenant, r, modele)
    return r


def _sauver_reveils():
    """Les réveils en cours (heure réelle) sont notés sur disque : si CE Lutin redémarre pendant que l'autre machine démarre, la séquence reprend là où elle en était au lieu de tout oublier."""
    reste = {i: round(time.time() - (time.monotonic() - t)) for i, t in REVEIL.items()}
    try:
        _ecrire("reveils.json", reste)
    except OSError:
        pass


def _reprendre_reveils():
    """Une fois par processus : les réveils notés sur disque qui ne sont pas périmés redeviennent « en cours »."""
    if _REVEILS_REPRIS["fait"]:
        return
    _REVEILS_REPRIS["fait"] = True
    notes = _lire("reveils.json", {})
    for ident, quand in (notes.items() if isinstance(notes, dict) else []):
        try:
            age = time.time() - float(quand or 0)
        except (TypeError, ValueError):
            continue
        if -2 <= age < power.ATTENTE_REVEIL_S and ident not in REVEIL and RE_ID.match(str(ident)):
            REVEIL[ident] = time.monotonic() - max(age, 0)


def _allumee_pendant_reveil(m, maintenant=time.monotonic):
    """Pendant un réveil seulement : le système de la machine répond-il (même si Lutin n'y répond pas encore ni son pare-feu) ? Preuves indépendantes de Lutin : voir alimentation.hote_allume.
    Windows jette les connexions que son pare-feu refuse au lieu de dire « refusé » : sans cela, une machine allumée restait « réveil envoyé » indéfiniment."""
    if m["id"] not in REVEIL:
        return False
    with VERROU:
        gardee = ALLUMEE.get(m["id"])
        if gardee and maintenant() - gardee[0] < VERIFICATION_ALLUMEE_S:
            return gardee[1]
    hote = urllib.parse.urlparse(m["adresse"]).hostname or ""
    try:
        port = urllib.parse.urlparse(m["adresse"]).port or 0
    except ValueError:
        port = 0
    try:
        verdict = bool(hote) and bool((HOTE_ALLUME or power.hote_allume)(hote, m.get("mac", ""), port))
    except Exception:  # noqa: BLE001  (un constat de plus : jamais une page cassée)
        verdict = False
    with VERROU:
        ALLUMEE[m["id"]] = (maintenant(), verdict)
        if verdict:
            DEPUIS_ALLUMEE.setdefault(m["id"], maintenant())
    return verdict


def _hote_allume(erreur):
    """Une connexion REFUSÉE prouve que la machine est allumée (son système répond) alors que Lutin n'y tourne pas : une absence de réponse, elle, veut dire éteinte ou hors réseau."""
    cause = getattr(erreur, "reason", erreur)
    return isinstance(cause, ConnectionRefusedError) or getattr(cause, "errno", None) in (111, 10061)


def _maj_disponible(version_distante):
    """Vrai si la version de CETTE machine est plus récente que celle de la machine distante : Lutin n'y est pas à jour."""
    if not version_distante:
        return False
    from . import updates, core as _m
    return updates.plus_recente(str(_m.VERSION), version_distante)


def _etape(m, r, allumee):
    """Où en est la machine, pour la page : eteinte · reveil (paquet envoyé) · allumee (le système répond, pas Lutin) · lutin (Lutin répond, moteur pas prêt) · synchro (relecture de ses modèles et conversations) · pret ·
    extinction (demandée, en cours) · maj (mise à jour demandée, Lutin redémarre). `dans_s` : secondes restantes avant l'extinction."""
    maintenant = time.monotonic()
    with VERROU:
        arret = ARRET.get(m["id"])
        if arret is not None and maintenant - arret > DELAI_ARRET_S:
            ARRET.pop(m["id"], None)
            arret = None
        majd = MAJ_DISTANTE.get(m["id"])
        if majd is not None and (maintenant - majd[0] > DELAI_MAJ_S or (r.get("version") and r["version"] != majd[1])):
            MAJ_DISTANTE.pop(m["id"], None)
            majd = None
        if r["etat"] == "injoignable" or r["etat"] == "reveil_envoye":
            if arret is not None:
                ARRET.pop(m["id"], None)          # elle ne répond plus : c'est fait
            if majd is not None:
                return {"etape": "maj", "dans_s": 0}
            if r.get("reveil_echec"):
                return {"etape": "eteinte", "dans_s": 0}          # le réveil n'a pas abouti : « pas démarrée », avec la raison (et le bouton Réveiller)
            return {"etape": "allumee" if allumee else ("reveil" if r["etat"] == "reveil_envoye" else "eteinte"), "dans_s": 0}
        if arret is not None:
            return {"etape": "extinction", "dans_s": max(0, round(30 - (maintenant - arret)))}
        if majd is not None:
            return {"etape": "maj", "dans_s": 0}
        if r["etat"] == "joignable":
            return {"etape": "lutin", "dans_s": 0}
        s = SYNCHRO.get(m["id"]) or {}
        coince = maintenant - s.get("debut", maintenant) > DELAI_SYNCHRO_S          # une relecture qui n'aboutit pas ne garde pas la machine « en synchronisation » indéfiniment
        return {"etape": "pret" if (s.get("modeles") and s.get("conv")) or coince else "synchro", "dans_s": 0}


def _avec_reveil(m, r, maintenant=time.monotonic, allumee=False):
    """Un réveil a été envoyé et la machine ne répond pas encore : état « réveil envoyé » avec ce qu'on sait (le système répond-il ?). Dès qu'elle répond, la marque du réveil est effacée.
    Au bout de ATTENTE_REVEIL_S (cinq minutes) sans réponse de Lutin, le réveil est déclaré non abouti : l'état revient à « pas démarrée », avec la RAISON la plus probable (machine éteinte, ou allumée sans Lutin), jusqu'au prochain réveil."""
    with VERROU:
        envoye = REVEIL.get(m["id"])
        if r["etat"] != "injoignable":
            ECHEC_REVEIL.pop(m["id"], None)
            if envoye is not None:
                A_REPONDU[m["id"]] = True
                debut = REPONDU.setdefault(m["id"], maintenant())
                if maintenant() - debut < STABLE_REPONSE_S:
                    return r          # Lutin répond, mais depuis trop peu pour dire que le réveil est fini : s'il disparaît de nouveau (il redémarre), la séquence continue
                journaliser("{} répond depuis {} s : réveil terminé".format(m["nom"], round(maintenant() - debut)))
            for suivi in (REVEIL, ALLUMEE, DEPUIS_ALLUMEE, REPONDU, A_REPONDU):
                suivi.pop(m["id"], None)
            _sauver_reveils()
            return r
        REPONDU.pop(m["id"], None)          # elle ne répond plus : le compte de stabilité repart de zéro
        if envoye is None:
            if m["id"] in ECHEC_REVEIL:
                return dict(r, detail=ECHEC_REVEIL[m["id"]], reveil_echec=True)
            return r
        depuis = maintenant() - envoye
        if depuis > power.ATTENTE_REVEIL_S:
            REVEIL.pop(m["id"], None)
            DEPUIS_ALLUMEE.pop(m["id"], None)
            A_REPONDU.pop(m["id"], None)
            _sauver_reveils()
            ECHEC_REVEIL[m["id"]] = echec = _echec_reveil(m, allumee)
            journaliser("réveil de {} non abouti après {} s ({})".format(m["nom"], round(depuis), "allumée, Lutin ne répond pas" if allumee else "aucune réponse"))
            return dict(r, detail=echec, reveil_echec=True)
        vue_depuis = maintenant() - DEPUIS_ALLUMEE.get(m["id"], maintenant()) if allumee else 0
    if allumee and m["id"] in A_REPONDU:
        detail = _t("La machine est allumée et Lutin y avait répondu, mais il ne répond plus : il redémarre (démarrage de session, réseau pas encore prêt). Je continue d'attendre.")
        suite = ""
    elif allumee:
        detail = _t("La machine est allumée (elle répond au réseau) ; Lutin n'y répond pas encore — il démarre, ou ne démarre pas tout seul. Réveil envoyé il y a {} s ; je laisse jusqu'à {} min.").format(round(depuis), power.ATTENTE_REVEIL_S // 60)
        suite = _t("Si Lutin ne démarre pas après la connexion de la session : sur cette machine, onglet Machines > « Démarrer Lutin à l'ouverture de ma session » (et auto-connexion Windows).") if vue_depuis > 90 else ""
    else:
        detail = _t("Réveil envoyé il y a {} s : une machine met de 30 secondes à quelques minutes à démarrer. Je laisse jusqu'à {} min.").format(round(depuis), power.ATTENTE_REVEIL_S // 60)
        suite = power.raison_echec(depuis)
    return {"etat": "reveil_envoye", "detail": detail + (" " + suite if suite else ""), "modeles": []}


def _echec_reveil(m, allumee):
    """Pourquoi le réveil n'a pas abouti (le texte qui reste affiché, avec le bouton « Réveiller », jusqu'au prochain essai)."""
    minutes = power.ATTENTE_REVEIL_S // 60
    if allumee:
        return _t("Réveil non abouti : la machine est bien allumée, mais Lutin n'y répond pas après {} minutes. Vérifie que Lutin y démarre avec la session (sur cette machine : onglet Machines > « Démarrer Lutin à l'ouverture de ma session »), que la session s'ouvre toute seule (auto-connexion Windows) et que le pare-feu laisse passer le port de Lutin.").format(minutes)
    return _t("Réveil non abouti : aucune réponse après {} minutes. {} Si la machine est en fait allumée, son adresse IP a peut-être changé (réserve-lui une adresse fixe dans ta box).").format(minutes, power.raison_echec(power.ATTENTE_REVEIL_S))


def reveiller(ident, envoyer=power.envoyer_reveil):
    """Envoie le paquet de réveil à cette machine (il faut son adresse MAC). L'état passe à « réveil envoyé » puis suit la machine : nœud joignable, moteur opérationnel."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    if not m.get("mac"):
        raise ValueError(_t("Pour réveiller cette machine, renseigne son adresse MAC (la liste des cartes réseau : « ipconfig /all » sous Windows, « ip link » sous Linux)."))
    hote = urllib.parse.urlparse(m["adresse"]).hostname or ""
    envoyes = envoyer(m["mac"], hote)
    with VERROU:
        REVEIL[ident] = time.monotonic()
        for suivi in (SONDES, ECHEC_REVEIL, ALLUMEE, DEPUIS_ALLUMEE, REPONDU, A_REPONDU):
            suivi.pop(ident, None)
        _sauver_reveils()
    journaliser("réveil envoyé à {}".format(m["nom"]))
    return {"ok": True, "mac": m["mac"], "envois": len(envoyes or []), "cartes": power.adresses_locales(), "avertissements": [a for a in [power.emission_limitee()] + avertissements(m) if a][:4]}          # le paquet est parti, mais on dit ce qui risque de l'empêcher de marcher


def eteindre(ident, annuler=False, ouvrir=None):
    """Demande à cette machine de s'éteindre (dans 30 s, annulable) ou annule la demande. Action EXPLICITE : la machine doit l'avoir autorisée, sinon elle refuse."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    try:
        rep = _json(m, "/api/noeud/eteindre", {"annuler": bool(annuler)}, delai=8, ouvrir=ouvrir)
    except urllib.error.HTTPError as e:
        raise ValueError(_t("Cette machine n'accepte pas d'être éteinte à distance : son propriétaire doit cocher « Autoriser les machines appairées à l'éteindre » dans l'onglet Machines.") if e.code == 403 else _t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None
    journaliser("{} demandée à {}".format("annulation de l'extinction" if annuler else "extinction", m["nom"]))
    with VERROU:
        if annuler:
            ARRET.pop(ident, None)
        else:
            ARRET[ident] = time.monotonic()
            oublier_machine(ident)          # elle va s'éteindre : on ne propose déjà plus ses modèles ni ses conversations
    SONDES.pop(ident, None)
    return rep


def demander_droit(ident, droit, ouvrir=None):
    """Demande à l'autre machine de t'accorder un droit (conversations, mise à jour, extinction) : son propriétaire répond sur elle. Rien n'est accordé d'office."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    if droit not in DROITS_DEMANDABLES:
        raise ValueError(_t("Droit inconnu."))
    try:
        _json(m, "/api/noeud/demande", {"droit": droit}, delai=8, ouvrir=ouvrir)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404, 405):
            raise ValueError(_t("Cette machine ne reconnaît pas la demande : soit son autorisation a été retirée, soit sa version de Lutin est trop ancienne. Mets-la à jour une première fois sur elle-même (relance l'installeur ou la commande « lutin update »).")) from None
        raise ValueError(_t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None
    SONDES.pop(ident, None)
    journaliser("autorisation « {} » demandée à {}".format(droit, m["nom"]))
    return {"ok": True}


def mettre_a_jour_distante(ident, ouvrir=None):
    """Demande à la machine distante de mettre Lutin à jour (elle doit l'avoir autorisé) ; elle redémarre ensuite toute seule si Lutin y tourne sous supervision. Le suivi se lit dans son étape « maj »."""
    m = trouver(ident)
    if m is None:
        raise ValueError(_t("Machine inconnue."))
    ancienne = (SONDES.get(ident) or (0, {}, ""))[1].get("version", "")
    try:
        _json(m, "/api/noeud/maj", {}, delai=15, ouvrir=ouvrir)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ValueError(_t("Cette machine n'accepte pas d'être mise à jour à distance : son propriétaire doit cocher « Autoriser les machines appairées à mettre Lutin à jour » dans l'onglet Machines.")) from None
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("erreur", "")
        except (ValueError, OSError, AttributeError):
            detail = ""
        raise ValueError(detail or _t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None
    with VERROU:
        MAJ_DISTANTE[ident] = (time.monotonic(), ancienne)
    SONDES.pop(ident, None)
    journaliser("mise à jour demandée à {}".format(m["nom"]))
    return {"ok": True}


def _noter(m, etat, maintenant, resultat, modele):
    with VERROU:
        SONDES[m["id"]] = (maintenant(), resultat, modele)
        if DERNIER_ETAT.get(m["id"]) != etat:
            DERNIER_ETAT[m["id"]] = etat
            journaliser("{} : {}".format(m["nom"], etat))          # un trait à chaque CHANGEMENT d'état, jamais à chaque sonde
            if etat in ("operationnel", "joignable"):
                DISTANTS["t"] = CONVERSATIONS["t"] = 0.0          # elle vient de répondre : ses modèles et ses conversations sont relus tout de suite
                SYNCHRO[m["id"]] = {"modeles": False, "conv": False, "debut": time.monotonic()}
            else:
                oublier_machine(m["id"])          # elle ne répond plus : ses modèles et ses conversations ne sont plus proposés


FRAICHEUR_S = 40          # une machine n'est proposée (modèles, conversations) que si elle a répondu depuis moins que ça
VEILLE = {"en_cours": False}


def _recente(ident):
    """Vrai si la machine a répondu à une sonde récente : sans cela, une machine éteinte resterait « opérationnelle » dans les listes tant que personne ne la sonde."""
    g = SONDES.get(ident)
    return bool(g) and time.monotonic() - g[0] < FRAICHEUR_S


def veiller(attente=False):
    """Garde l'état des machines à jour sans que la page Machines soit ouverte : une sonde en arrière-plan quand la dernière date de plus de la moitié de la fraîcheur.
    Une machine qui ne répond plus disparaît des listes en quelques secondes ; quand elle répond de nouveau, ses modèles et conversations reviennent (voir _noter)."""
    machines = lire()
    with VERROU:
        a_faire = [m for m in machines if not SONDES.get(m["id"]) or time.monotonic() - SONDES[m["id"]][0] > FRAICHEUR_S / 2]
        if not a_faire or VEILLE["en_cours"]:
            return
        VEILLE["en_cours"] = True

    def travail():
        try:
            for m in a_faire:
                try:
                    sonder(m, "")
                except Exception:  # noqa: BLE001
                    pass
        finally:
            with VERROU:
                VEILLE["en_cours"] = False
    if attente:
        travail()
    else:
        threading.Thread(target=travail, daemon=True, name="machines-veille").start()


def vider_listes():
    """Mode multi-machines désactivé : plus aucune liste distante gardée en mémoire (elles se reconstruisent à la réactivation)."""
    with VERROU:
        DISTANTS.update(t=0.0, v=[])
        CONVERSATIONS.update(t=0.0, v=[])
        SYNCHRO.clear()


def hors_ligne():
    """Noms des machines appairées qui ne répondent pas : leurs conversations importées restent utilisables ici mais ne se synchronisent plus."""
    return [m["nom"] for m in lire() if DERNIER_ETAT.get(m["id"]) not in ("joignable", "operationnel") or not _recente(m["id"])]


def oublier_machine(ident):
    """Plus rien de cette machine dans les listes (modèles à choisir, conversations en jaune) : on ne peut plus lui parler."""
    with VERROU:
        DISTANTS["v"] = [d for d in DISTANTS["v"] if d["id"] != ident]
        CONVERSATIONS["v"] = [c for c in CONVERSATIONS["v"] if c["machine"] != ident]
        SYNCHRO.pop(ident, None)


def _synchro_fait(cle, ids):
    with VERROU:
        for i in ids:
            if i in SYNCHRO:
                SYNCHRO[i][cle] = True


def signaler_panne(m, modele=""):
    """Une demande vers cette machine a échoué : elle passe injoignable tout de suite (la suivante répond en local sans réessayer)."""
    _noter(m, "injoignable", time.monotonic, {"etat": "injoignable", "detail": _t("Pas de réponse (éteinte, hors réseau ou Lutin arrêté)."), "modeles": []}, modele)


def cluster_actif(reglage):
    """L'onglet Machines est-il visible ? Le réglage explicite l'emporte ; sans réglage (None), dès qu'une machine est appairée ou que celle-ci en prête le moteur."""
    if reglage is not None:
        return bool(reglage)
    return bool(lire()) or bool(noeud_vue().get("actif"))


def etats(modele="", ouvrir=None, choisie=""):
    """Pour la page Machines : chaque machine avec son état. Le modèle choisi ici n'est cherché que sur la machine CHOISIE pour répondre : les autres ont leurs propres modèles, ce n'est pas un défaut."""
    return [dict(vue(m), **sonder(m, modele if m["id"] == choisie else "", ouvrir)) for m in lire()]


# --------------------------------------------------------------------------- ce que les autres machines partagent : conversations, skills, mémoire (copies locales, à ta demande)

CONVERSATIONS = {"t": 0.0, "v": [], "en_cours": False}


def demander_partage(m, genre, **corps):
    """Lit chez l'autre machine ce qu'elle partage. ValueError avec la marche à suivre si son propriétaire ne l'a pas autorisé."""
    try:
        return _json(m, "/api/noeud/partage", dict(corps, genre=genre), delai=20)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ValueError(_t("La machine « {} » ne partage pas cela : sur elle, onglet Machines > « Partager avec les machines appairées », puis coche la case voulue.").format(m.get("nom", "?"))) from None
        raise ValueError(_t("Cette machine a répondu une erreur ({}).").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Impossible de joindre cette machine : vérifie l'adresse et qu'elle est allumée.")) from None


def _rafraichir_conversations():
    liste = []
    for m in lire():
        try:
            if not sonder(m, "").get("agir", {}).get("piloter"):
                continue
            for c in demander_partage(m, "conversations").get("conversations", []):
                if isinstance(c, dict) and RE_IDENT_CONV.match(str(c.get("id", ""))):
                    liste.append({"machine": m["id"], "machine_nom": m["nom"], "id": c["id"], "titre": str(c.get("titre", ""))[:120], "maj": str(c.get("maj", ""))[:30], "messages": int(c.get("messages") or 0)})
        except (ValueError, TypeError):
            continue
    with VERROU:
        CONVERSATIONS.update(t=time.monotonic(), v=liste, en_cours=False)
    _synchro_fait("conv", [m["id"] for m in lire()])


RE_IDENT_CONV = re.compile(r"^[0-9a-f]{8}$")


def conversations_distantes(attente=False):
    """Les conversations des machines appairées qui les partagent. Rendues tout de suite depuis la mémoire (la liste ne doit jamais attendre une machine éteinte) ; mise à jour en arrière-plan toutes les 30 s."""
    if not lire():
        return []
    nettoyer_copies_importees()
    veiller(attente)
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
    ids = {m["id"] for m in lire() if DERNIER_ETAT.get(m["id"]) in ("joignable", "operationnel") and _recente(m["id"])}          # une machine qui ne répond pas n'a plus de conversations proposées
    return [dict(c) for c in CONVERSATIONS["v"] if c["machine"] in ids]


def _registre_import(nom):
    return _lire(nom, {})


COPIES_NETTOYEES = [False]


def nettoyer_copies_importees():
    """Les anciennes copies locales de conversations d'autres machines (jamais continuées ici) sont supprimées : les conversations des autres machines se mènent maintenant SUR elles (voir relais).
    Une copie qui a continué ici reste, comme n'importe quelle conversation de cette machine."""
    if COPIES_NETTOYEES[0]:
        return 0
    COPIES_NETTOYEES[0] = True
    from . import core as _m
    supprimees = 0
    for c in _m.conv_liste():
        if not c.get("origine"):
            continue
        try:
            complete = _m.conv_lire(c["id"])
            origine = complete.get("origine") or {}
            if len(complete.get("messages", [])) == int(origine.get("messages_importes") or -1):
                _m.conv_supprimer(c["id"])
                supprimees += 1
        except (ValueError, OSError, TypeError):
            continue
    try:
        (dossier() / "conversations_importees.json").unlink()
    except OSError:
        pass
    if supprimees:
        journaliser("{} ancienne(s) copie(s) de conversations supprimée(s)".format(supprimees))
    return supprimees


ENTETES_RELAIS = ("Content-Type", "Content-Disposition", "Content-Security-Policy", "Cache-Control", "X-Accel-Buffering")
RE_CHEMIN_RELAIS = re.compile(r"^/[A-Za-z0-9_\-./%?=&]{1,300}$")


def ouvrir_relais(m, methode, chemin, corps=None, type_contenu="application/json", nom="", ouvrir=None):
    """Transmet une requête de CETTE page à la conversation pilotée sur l'autre machine (`/api/noeud/relais`, droit « piloter »). Renvoie la réponse en flux ; HTTPError/URLError/OSError à l'appelant.
    La conversation, les outils, les addons et les fichiers restent sur l'autre machine : ici on ne fait que passer les octets."""
    if not RE_CHEMIN_RELAIS.match(chemin) or ".." in chemin:
        raise ValueError(_t("Chemin invalide."))
    en_tetes = {"X-Noeud": m.get("jeton", ""), "Content-Type": type_contenu}
    if nom:
        en_tetes["X-Nom"] = nom
    req = urllib.request.Request(m["adresse"] + "/api/noeud/relais" + chemin, data=corps if methode == "POST" else None, headers=en_tetes, method=methode)
    return (ouvrir or urllib.request.build_opener(_SansRedirection).open)(req, timeout=DELAI_RELAIS_S)


DELAI_RELAIS_S = 180          # un silence plus long que ça (la machine hôte envoie un battement toutes les quelques secondes) : la machine est perdue


def importer_skills(ident):
    """Ajoute à CETTE machine les skills de l'autre qui n'y sont pas (les deux jeux se cumulent). Un skill qui existe déjà ici n'est jamais écrasé, sauf s'il vient de cette machine et n'a pas été modifié depuis.
    {ajoutes, mis_a_jour, deja_la}."""
    import hashlib
    from . import core as _m
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
    from . import core as _m
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
    ignorees = 0
    if neuves:
        entete = "\n\n## {}\n".format(_t("Depuis {} ({})").format(m["nom"], time.strftime("%Y-%m-%d")))
        place = LIMITE_MEMOIRE - len(local.rstrip()) - len(entete) - 1
        gardees, taille = [], 0
        for ligne in neuves:
            if taille + len(ligne) + 1 > place:
                break
            gardees.append(ligne)
            taille += len(ligne) + 1
        ignorees = len(neuves) - len(gardees)          # ce qui ne tient pas n'est PAS écrit (et le début du fichier local, ses décisions, n'est jamais rogné) : on le dit
        if gardees:
            _m.ecrire_memoire("MEMOIRE.md", local.rstrip() + entete + "\n".join(gardees) + "\n")
        neuves = gardees
    profil, profil_coupe = False, False
    if str(distante.get("CONTEXTE.md", "")).strip() and not _m.lire_memoire("CONTEXTE.md").strip():
        contexte = str(distante["CONTEXTE.md"])
        profil_coupe = len(contexte) > LIMITE_MEMOIRE
        _m.ecrire_memoire("CONTEXTE.md", contexte[:LIMITE_MEMOIRE])
        profil = True
    journaliser("mémoire importée de {} : {} note(s), {} ignorée(s) faute de place{}".format(m["nom"], len(neuves), ignorees, ", profil coupé" if profil_coupe else ""))
    return {"notes_ajoutees": len(neuves), "notes_ignorees": ignorees, "profil_copie": profil, "profil_coupe": profil_coupe}


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
    _synchro_fait("modeles", [m["id"] for m in lire()])


def modeles_distants(attente=False):
    """Les modèles des machines appairées qui répondent : [{id, nom, etat, modeles}]. Ce qui est gardé en mémoire est rendu tout de suite (la page ne doit jamais attendre une machine éteinte) ;
    une mise à jour part en arrière-plan quand la dernière date de plus de 15 s. `attente=True` (tests) la fait sur place."""
    if not lire():
        return []
    veiller(attente)
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
    ids = {m["id"] for m in lire() if DERNIER_ETAT.get(m["id"]) == "operationnel" and _recente(m["id"])}          # une machine qui ne répond pas n'est plus proposée
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
            raise ValueError(_t("Le modèle « {} » n'existe que sur la machine « {} », qui ne répond pas pour l'instant (éteinte, hors réseau ou Lutin arrêté). Réveille-la dans l'onglet Machines, ou choisis un modèle de cette machine-ci.").format(modele, self.machine.get("nom", "?")))

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
