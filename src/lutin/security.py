"""Les trois niveaux d'accès de Lutin et tout ce qui les fait respecter.

  local    cette machine seulement (127.0.0.1), aucun mot de passe
  reseau   réseau local : appairage par code PIN, une session par appareil
  proxy    derrière un proxy inverse (Authelia, Authentik…) : l'identité vient du proxy, et seulement de lui

Le module ne touche ni au réseau ni au disque (sauf `Appareils`, qui écrit son fichier à la demande) : tout se teste sans serveur.
Règle dure : hors du niveau « local », les accords automatiques (écriture, commandes) sont désactivés, quoi que dise le fichier de réglages.
"""
import hashlib
import hmac
import os
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from .i18n import t as _t

LOCAL, RESEAU, PROXY = "local", "reseau", "proxy"
LEVELS = (LOCAL, RESEAU, PROXY)
NAME_COOKIE = "lutin_session"
DURATION_SESSION_S = 30 * 24 * 3600
DURATION_PIN_S = 600
ATTEMPTS_PIN = 5
LOCK_OUT_S = 300


@dataclass
class Security:
    niveau: str = LOCAL
    port: int = 8777
    url_publique: str = ""                     # niveau proxy : « https://lutin.exemple.fr »
    proxy_ips: list = field(default_factory=list)   # niveau proxy : adresses (ou réseaux) dont on accepte l'identité
    en_tete_identite: str = "Remote-User"
    ecoute: str = ""                                # adresse d'écoute imposée (conteneur : « 0.0.0.0 ») ; interdit au niveau « local »

    def valider(self):
        """Liste des problèmes de configuration (vide = correcte)."""
        pb = []
        if self.niveau not in LEVELS:
            pb.append("niveau inconnu : " + str(self.niveau))
        if not (1 <= int(self.port) <= 65535):
            pb.append("port invalide")
        if self.ecoute:
            if self.niveau == LOCAL:
                pb.append(_t("une adresse d'écoute imposée n'est pas permise au niveau « local » (il n'écoute que sur 127.0.0.1)"))
            else:
                try:
                    ipaddress.ip_address(self.ecoute)
                except ValueError:
                    pb.append(_t("adresse d'écoute invalide : ") + str(self.ecoute))
        if self.niveau == PROXY:
            if not self.url_publique.startswith(("http://", "https://")):
                pb.append(_t("l'adresse publique (https://…) est obligatoire derrière un proxy"))
            elif self.url_publique.startswith("http://"):
                pb.append(_t("l'adresse publique devrait être en https:// (sinon les mots de passe circulent en clair)"))
            if not self.proxy_ips:
                pb.append(_t("indique l'adresse du proxy de confiance (celle qui apparaît côté Lutin)"))
            for ip in self.proxy_ips:
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    pb.append(_t("adresse de proxy invalide : ") + str(ip))
        return pb

    @staticmethod
    def depuis_dict(d):
        return Security(**{k: v for k, v in (d or {}).items() if k in Security.__dataclass_fields__})


def address_listening(sec, ip_lan=""):
    """Adresse sur laquelle le serveur se lie. `local` : jamais autre chose que 127.0.0.1 ; proxy : l'interface locale (le proxy est sur la même machine) ou le réseau si un proxy distant est déclaré."""
    if sec.niveau == LOCAL:
        return "127.0.0.1"
    if sec.ecoute:
        return sec.ecoute
    if sec.niveau == PROXY:
        distants = [i for i in sec.proxy_ips if not _is_loop(i)]
        return (ip_lan or "0.0.0.0") if distants else "127.0.0.1"
    return ip_lan or "0.0.0.0"


def _is_loop(texte):
    try:
        return ipaddress.ip_network(texte, strict=False).is_loopback
    except ValueError:
        return False


def _without_port(hote):
    hote = (hote or "").strip().lower()
    if hote.startswith("["):
        return hote.split("]")[0] + "]"
    return hote.rsplit(":", 1)[0] if hote.count(":") == 1 else hote


def allowed_host(sec, entete_host, ip_lan=""):
    """Protège du « DNS rebinding » : le nom demandé doit être un des noms de CETTE application (pas celui d'un site tiers qui pointerait vers 127.0.0.1)."""
    hote = _without_port(entete_host)
    if not hote:
        return False
    permis = {"127.0.0.1", "localhost", "[::1]"}
    if sec.niveau == RESEAU:
        if ip_lan:
            permis.add(ip_lan.lower())
        try:
            ipaddress.ip_address(hote.strip("[]"))
            return ipaddress.ip_address(hote.strip("[]")).is_private or hote in permis      # sur un réseau local : adresses privées seulement
        except ValueError:
            return hote in permis or hote.endswith(".local") or "." not in hote                  # noms mDNS / noms de machine locaux
    if sec.niveau == PROXY:
        permis.add(_without_port(sec.url_publique.split("://", 1)[-1].split("/")[0]))
    return hote in permis


def allowed_origin(sec, entete_origin, entete_host, ip_lan=""):
    """Les requêtes qui MODIFIENT quelque chose doivent venir de la page de Lutin elle-même. Pas d'Origin (outil en ligne de commande) : acceptée, le jeton protège."""
    if not entete_origin:
        return True
    if entete_origin == "null":
        return False
    hote = entete_origin.split("://", 1)[-1].split("/")[0]
    return allowed_host(sec, hote, ip_lan) and _without_port(hote) == _without_port(entete_host)


def ip_in(ip, reseaux):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for r in reseaux:
        try:
            if a in ipaddress.ip_network(r, strict=False):
                return True
        except ValueError:
            continue
    return False


def admins():
    """Les identités (en minuscules) qui peuvent configurer Lutin depuis la page au niveau « proxy » : variable LUTIN_ADMINS (« alice,bob »). Vide par défaut : personne, tout se configure alors par la commande lutin."""
    return {x.strip().lower() for x in os.environ.get("LUTIN_ADMINS", "").replace(";", ",").replace(" ", ",").split(",") if x.strip()}


def is_admin_proxy(sec, ip_client, en_tetes):
    """La requête vient du proxy de confiance, qui a identifié un administrateur déclaré (l'en-tête n'est cru que de la part du proxy : voir identite_proxy)."""
    nom = identity_proxy(sec, ip_client, en_tetes)
    return bool(nom) and nom.lower() in admins()


def identity_proxy(sec, ip_client, en_tetes):
    """Nom d'utilisateur transmis par le proxy, ou None. L'en-tête n'est cru QUE si la connexion vient du proxy déclaré : n'importe qui peut écrire « Remote-User: admin »."""
    if sec.niveau != PROXY or not ip_in(ip_client, sec.proxy_ips):
        return None
    nom = (en_tetes.get(sec.en_tete_identite) or "").strip()
    return nom[:128] or None


def equal(a, b):
    """Comparaison de secrets à temps constant, sur des octets : un caractère hors ASCII n'est pas une exception."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _digest(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


class RateLimiter:
    """Au plus `maximum` événements par `fenetre` secondes et par clé (adresse IP)."""

    def __init__(self, maximum=10, fenetre=60, horloge=time.monotonic):
        self.maximum, self.fenetre, self.horloge, self.evenements = maximum, fenetre, horloge, {}

    def autoriser(self, cle):
        maintenant = self.horloge()
        recents = [t for t in self.evenements.get(cle, []) if maintenant - t < self.fenetre]
        if len(recents) >= self.maximum:
            self.evenements[cle] = recents
            return False
        recents.append(maintenant)
        self.evenements[cle] = recents
        return True


def device_name(donne, agent="", sur_la_machine=False):
    """Le nom affiché d'un appareil appairé : celui qu'on a tapé, sinon d'après le navigateur (« Chrome · Windows »). Un appairage par QR code ou par adresse ne porte pas de nom : on ne l'appelle pas « QR »."""
    donne = (donne or "").strip()
    if donne and donne.lower() != "qr":
        return donne[:60]
    systemes = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux"))
    navigateurs = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
    agent = agent or ""
    morceaux = [n for cle, n in navigateurs if cle in agent][:1] + [n for cle, n in systemes if cle in agent][:1]
    base = " · ".join(morceaux) or "Appareil"
    return ("Cet ordinateur (" + base + ")") if sur_la_machine else base


class Devices:
    """Code PIN d'appairage et sessions des appareils. Seules les EMPREINTES des jetons sont gardées sur disque : le fichier ne permet pas d'usurper une session."""

    def __init__(self, fichier=None, horloge=time.time):
        self.fichier, self.horloge = Path(fichier) if fichier else None, horloge
        self.pin = self.pin_expire = None
        self.echecs, self.bloque_jusqua = 0, 0.0
        self.sessions = self._lire()

    def _lire(self):
        if self.fichier and self.fichier.is_file():
            try:
                d = json.loads(self.fichier.read_text(encoding="utf-8"))
                return d if isinstance(d, dict) else {}
            except (OSError, ValueError):
                pass
        return {}

    def _ecrire(self):
        if self.fichier:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.fichier.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.sessions, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.fichier)

    def nouveau_pin(self):
        """Affiché sur la machine elle-même (jamais envoyé sur le réseau)."""
        self.pin = "{:06d}".format(secrets.randbelow(1_000_000))
        self.pin_expire = self.horloge() + DURATION_PIN_S
        self.echecs = 0
        return self.pin

    def appairer(self, pin, device=""):
        """Renvoie un jeton de session si le PIN est bon ; None sinon. Après ESSAIS_PIN échecs, le PIN est invalidé et plus aucun essai n'est accepté pendant BLOCAGE_S."""
        maintenant = self.horloge()
        if maintenant < self.bloque_jusqua or not self.pin or maintenant > (self.pin_expire or 0):
            return None
        if not equal(str(pin).strip(), self.pin):
            self.echecs += 1
            if self.echecs >= ATTEMPTS_PIN:
                self.pin, self.bloque_jusqua = None, maintenant + LOCK_OUT_S
            return None
        jeton = secrets.token_urlsafe(32)
        self.sessions[_digest(jeton)] = {"nom": (device or "Appareil")[:60], "cree": maintenant, "vu": maintenant}
        self.pin = None                                     # un PIN ne sert qu'une fois
        self._ecrire()
        return jeton

    def valide(self, jeton):
        if not jeton:
            return False
        e = self.sessions.get(_digest(jeton))
        if not e:
            return False
        maintenant = self.horloge()
        if maintenant - e["cree"] > DURATION_SESSION_S:
            self.sessions.pop(_digest(jeton), None)
            self._ecrire()
            return False
        e["vu"] = maintenant
        return True

    def liste(self):
        return [{"id": cle[:10], "nom": e["nom"], "cree": e["cree"], "vu": e["vu"]} for cle, e in self.sessions.items()]

    def revoquer(self, identifiant=None):
        """Un appareil (par les 10 premiers caractères de son identifiant), ou tous."""
        avant = len(self.sessions)
        self.sessions = {} if identifiant is None else {k: v for k, v in self.sessions.items() if not k.startswith(identifiant)}
        if len(self.sessions) != avant:
            self._ecrire()
        return avant - len(self.sessions)


def cookie_session(en_tetes_cookie):
    """Valeur du cookie de session dans l'en-tête Cookie, ou ''."""
    for morceau in (en_tetes_cookie or "").split(";"):
        cle, _, valeur = morceau.strip().partition("=")
        if cle == NAME_COOKIE:
            return valeur
    return ""


def set_cookie_header(jeton, https):
    return "{}={}; Path=/; HttpOnly; SameSite=Strict; Max-Age={}{}".format(NAME_COOKIE, jeton, DURATION_SESSION_S, "; Secure" if https else "")


def access_decision(sec, appareils, ip_client, en_tetes, jeton_local=None):
    """Décision d'accès pour une requête : (autorise, identité ou raison du refus).

    local   : toute requête arrivant sur 127.0.0.1 (le serveur n'écoute pas ailleurs) ; le jeton de page protège contre les autres sites web
    reseau  : cookie de session obtenu par PIN
    proxy   : identité transmise par le proxy de confiance, sinon cookie de session
    """
    if sec.niveau == LOCAL:
        return True, "local"
    if sec.niveau == PROXY:
        nom = identity_proxy(sec, ip_client, en_tetes)
        if nom:
            return True, nom
    if appareils.valide(cookie_session(en_tetes.get("Cookie"))):
        return True, "appareil"
    return False, "authentification requise"
