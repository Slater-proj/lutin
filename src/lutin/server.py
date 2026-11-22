"""Le serveur HTTP de Lutin : le gestionnaire de requêtes (pages, API JSON, flux de la conversation). L'état et les fonctions métier restent dans moteur ; ce module les atteint par « _m.NOM » (lu à chaque appel)."""
import gzip
from http.server import BaseHTTPRequestHandler
from . import power as _alimentation
from . import machines as _machines
from . import engines as _moteurs
from . import access as _acces
from . import api_v1 as _api_v1
from . import web_app as _web_app
from . import managed_models as _geres
from . import modes as _modes
from . import attachments as _pieces
from . import images as _images
from . import produced_files as _fichiers
from . import mission as _mission
from . import background_jobs as _fond
from . import i18n as _i18n
from . import security as _sec
from .i18n import t as _t
import json
import os
import time
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from . import core as _m
from . import turn_runner as _turns


STREAM_WRITE_TIMEOUT = 20      # secondes : une page qui ne lit plus (onglet gelé) ne doit pas figer la réponse
COMPRESSIBLE_TYPES = ("text/html", "application/json", "text/javascript", "application/javascript", "text/css", "image/svg+xml")          # jamais les images ni les archives (déjà compressées)
STREAM_HEARTBEAT = 15          # secondes entre deux lignes vides envoyées pour garder le flux ouvert derrière un reverse proxy


class _CountedBody:
    """Le flux d'entrée d'une requête, qui compte les octets du corps déjà lus (pour savoir, à la fin, ce qu'une réponse de refus a laissé sans lecture)."""

    def __init__(self, brut):
        self.brut = brut
        self.lus = 0

    def read(self, taille=-1):
        donnees = self.brut.read(taille)
        self.lus += len(donnees)
        return donnees

    def __getattr__(self, nom):
        return getattr(self.brut, nom)


class Handler(BaseHTTPRequestHandler):
    server_version = "Lutin/" + _m.VERSION

    def log_message(self, fmt, *args):
        pass

    def parse_request(self):
        self._corps = None
        if not super().parse_request():
            return False
        self._corps = self.rfile if isinstance(self.rfile, _CountedBody) else _CountedBody(self.rfile)
        self.rfile = self._corps
        return True

    def handle_one_request(self):
        super().handle_one_request()
        self._jeter_corps_restant()

    def _jeter_corps_restant(self):
        """Une requête refusée (401, 403...) sans que son corps ait été lu : fermer la connexion avec ces octets en attente la réinitialise chez l'appelant, qui perd la réponse
        (une course, vue sur Windows). Après la réponse, on lit donc ce qui reste, dans la limite de `api_v1.DISCARD_MAX` et sans attendre plus de deux secondes."""
        corps = getattr(self, "_corps", None)
        if corps is None:
            return
        try:
            reste = self._taille_corps() - corps.lus
            if reste <= 0 or reste > _api_v1.DISCARD_MAX:
                return
            self.connection.settimeout(2)
            while reste > 0:
                morceau = corps.read(min(reste, 65536))
                if not morceau:
                    break
                reste -= len(morceau)
        except (OSError, ValueError, AttributeError):
            self.close_connection = True

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError):          # la page a été fermée ou rechargée pendant la réponse : sans importance
            pass

    def _envoyer(self, code, corps, type_="application/json; charset=utf-8", en_tetes=None):
        if code == 403 and isinstance(corps, dict) and "cette machine" in str(corps.get("erreur", "")) and _acces.in_docker():
            corps = dict(corps, erreur=str(corps["erreur"]) + _t(" Dans Docker : ajoute LUTIN_ADMIN_TOUS=1 aux variables du conteneur (ou, derrière un proxy, ton identifiant dans LUTIN_ADMINS), puis redémarre-le."))
        elif code == 403 and isinstance(corps, dict) and "cette machine" in str(corps.get("erreur", "")):
            corps = dict(corps, erreur=str(corps["erreur"]) + _t(" Pour le faire depuis un autre appareil : Accès > Administration à distance (à activer depuis cette machine)."))
        if isinstance(corps, dict) and _i18n.language() != "fr":
            corps = _m.translate_json(corps)
        donnees = corps if isinstance(corps, (bytes, bytearray)) else (corps if isinstance(corps, str) else json.dumps(corps, ensure_ascii=False)).encode("utf-8")
        compressible = len(donnees) > 1400 and type_.split(";")[0].strip() in COMPRESSIBLE_TYPES and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        if compressible:          # la page (370 Ko) et l'état se compressent à environ le quart : sensible sur un téléphone ou le Wi-Fi
            donnees = gzip.compress(bytes(donnees), 5, mtime=0)
        self.send_response(code)
        self.send_header("Content-Type", type_)
        if compressible:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(donnees)))
        if "Cache-Control" not in (en_tetes or {}):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (en_tetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(donnees)

    # ---- sécurité (voir lutin.security) ----
    _via_relais = ""          # nom de la machine appairée dont cette requête est relayée (droit « piloter »), sinon ""

    def _local(self):
        """La requête vient de cette machine : la boucle locale, ou l'adresse de la machine sur le réseau local (un navigateur d'ici qui ouvre http://192.168.x.y:8777 arrive avec cette adresse-là).
        Une autre machine ne peut pas se faire passer pour elle : la connexion TCP n'aboutirait pas."""
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or bool(_m.IP_LAN and ip == _m.IP_LAN)

    def _jeton_valide(self):
        if self._via_relais:
            return True                                      # déjà contrôlé par le jeton de nœud (voir _relais)
        donne = self.headers.get("X-Token") or ""
        return any(_sec.equal(donne, attendu) for attendu in (_m.TOKEN, _m.CONSOLE_TOKEN))

    def _authentifie(self):
        if self._via_relais:
            return True
        if self._local() and _sec.equal(self.headers.get("X-Token") or "", _m.CONSOLE_TOKEN):
            return True                                      # la console de cette machine (fichier réservé à l'utilisateur)
        return _sec.access_decision(_m.SECURITY, _m.DEVICES, self.client_address[0], self.headers)[0]

    def _identite(self):
        """Qui fait cette requête, pour le journal : « console », « local », le nom donné par le proxy, ou « appareil »."""
        if self._via_relais:
            return "machine : " + self._via_relais
        if self._local() and _sec.equal(self.headers.get("X-Token") or "", _m.CONSOLE_TOKEN):
            return "console"
        return _sec.access_decision(_m.SECURITY, _m.DEVICES, self.client_address[0], self.headers)[1]

    def _sur_cette_machine(self):
        """Le navigateur est sur cette machine : connexion de boucle locale, nom d'hôte de boucle locale, et aucun en-tête laissant croire qu'un relais (proxy, tunnel) a transmis une requête venue d'ailleurs."""
        relais = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "Via", "X-Real-IP")
        return self._local() and not any(self.headers.get(h) for h in relais) and (_sec._is_loop(_sec._without_port(self.headers.get("Host") or "")) or bool(_m.IP_LAN and _sec._without_port(self.headers.get("Host") or "") == _m.IP_LAN))


    REFLEXION = {}          # (moteur, machine, modèle) -> (instant, résultat) : /api/etat est demandé très souvent, le moteur ne doit pas être interrogé à chaque fois


    @staticmethod
    def _admin_tous():
        """Le propriétaire a ouvert la configuration à toute personne déjà admise par le niveau d'accès : Docker (LUTIN_ADMIN_TOUS=1 dans le docker-compose, car le navigateur n'y est jamais « sur la machine »)
        ou, partout, le réglage Accès > Administration à distance (qui ne se change que depuis la machine elle-même)."""
        if _acces.in_docker() and os.environ.get("LUTIN_ADMIN_TOUS", "").strip().lower() in ("1", "true", "oui", "yes", "on"):
            return True
        try:
            return bool(_m.read_config().get("admin_a_distance"))
        except (OSError, ValueError):
            return False

    def _configurateur(self):
        """Peut-on configurer depuis cette page ? Oui depuis la machine elle-même, ou depuis n'importe quel appareil admis si le propriétaire a ouvert l'administration à distance."""
        if self._via_relais:
            return False                                     # une machine qui pilote une conversation ne configure jamais celle-ci
        if self._admin_tous():
            return self._authentifie()
        return self._configurateur_strict()

    def _configurateur_strict(self):
        """Peut-on changer ce qui ouvre ou modifie la machine (dossiers de travail, niveau d'accès, restauration) ? Seulement depuis cette machine : au niveau « machine seulement », avec le jeton de la console,
        ou — au niveau « réseau » — depuis le navigateur de cette machine (jamais depuis un appareil appairé). Derrière un proxy, la commande lutin seulement : le proxy est sur la machine, il ne prouve rien.
        C'est la règle d'origine, sans l'ouverture à distance (voir _configurateur) : elle seule peut activer ou retirer l'administration à distance."""
        if self._via_relais:
            return False
        if _m.SECURITY.niveau == _sec.LOCAL:
            return True
        if self._local() and _sec.equal(self.headers.get("X-Token") or "", _m.CONSOLE_TOKEN):
            return True
        if _sec.is_admin_proxy(_m.SECURITY, self.client_address[0], self.headers):
            return True                                                    # niveau proxy : un administrateur déclaré (LUTIN_ADMINS) identifié par le proxy de confiance (Authelia…)
        return _m.SECURITY.niveau == _sec.RESEAU and self._sur_cette_machine()

    def _controle(self, ecriture):
        """Nom d'hôte (contre le « DNS rebinding ») et origine (contre les requêtes venues d'autres sites). Répond lui-même en cas de refus."""
        if not _sec.allowed_host(_m.SECURITY, self.headers.get("Host"), _m.IP_LAN):
            code, message = "host_not_allowed", "nom d'hôte non autorisé"
        elif ecriture and not _sec.allowed_origin(_m.SECURITY, self.headers.get("Origin"), self.headers.get("Host"), _m.IP_LAN):
            code, message = "origin_not_allowed", "origine non autorisée"
        else:
            return True
        if self.path.split("?")[0].startswith("/api/v1/"):      # l'API versionnée refuse dans SA forme (un code, un message) et lit le corps avant de répondre
            _api_v1.refuse(self, 403, code, message)
        else:
            self._envoyer(403, {"erreur": message})
        return False

    def _page_connexion(self):
        page = _m.LOGIN_PAGE
        if _i18n.language() != "fr":
            for phrase in _m.LOGIN_PAGE_TEXTS:
                page = page.replace(phrase, _t(phrase))
            page = page.replace('<html lang="fr">', '<html lang="{}">'.format(_i18n.language()))
        return self._envoyer(200, page, "text/html; charset=utf-8")

    def _nouvelle_interface(self, chemin):
        """`/app/` : la page construite depuis `frontend/` et ses fichiers (lutin.web_app). Rien n'est servi sans session ; la page reçoit le jeton comme l'ancienne."""
        reste = chemin[len(_web_app.PREFIX):]
        if reste.startswith("assets/"):
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            fichier = _web_app.asset(reste[len("assets/"):])
            if fichier is None:
                return self._envoyer(404, {"erreur": "introuvable"})
            return self._envoyer(200, fichier[0], fichier[1], {"Cache-Control": _web_app.ASSET_CACHE})
        if reste == _web_app.DIAGRAM:                            # le cadre isolé qui dessine les diagrammes (ADR 0011) : sa propre politique, ni jeton ni session dedans
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            cadre = _web_app.diagram_page()
            if cadre is None:
                return self._envoyer(404, {"erreur": "introuvable"})
            return self._envoyer(200, cadre[0], "text/html; charset=utf-8", {"Content-Security-Policy": cadre[1]})
        if reste not in ("", "index.html"):
            return self._envoyer(404, {"erreur": "introuvable"})
        if not self._authentifie():
            return self._page_connexion()
        page = _web_app.page(_m.TOKEN, _m.VERSION, _i18n.language())
        if page is None:
            return self._envoyer(404, _web_app.NOT_BUILT, "text/html; charset=utf-8")
        return self._envoyer(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": _web_app.CSP})

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if not self._controle(False):
            return
        if chemin.startswith("/api/v1/"):                      # l'API versionnée, en anglais (lutin.api_v1) : droits déclarés dans sa table, erreurs avec un code
            return _api_v1.dispatch(self, "GET")
        if chemin.startswith("/api/noeud/relais/"):            # une machine appairée mène une conversation ICI (droit « piloter »)
            return self._relais("GET")
        if chemin == "/api/noeud/etat":                        # une autre machine demande si ce Lutin peut faire tourner un modèle : jeton de nœud, rien d'autre n'est ouvert
            return self._noeud_etat()
        if chemin.startswith("/app/"):                           # la nouvelle interface (ADR 0002), aussi servie à « / » depuis la 1.0
            return self._nouvelle_interface(chemin)
        if chemin in ("/", "/index.html") and not self._authentifie():
            return self._page_connexion()
        if chemin in ("/", "/index.html"):                     # the interface built from frontend/ (ADR 0002); a page says how to build it when it is missing
            return self._nouvelle_interface(_web_app.PREFIX)
        if chemin.startswith("/api/"):
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            if not self._jeton_valide():
                return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        if chemin.startswith("/image/"):                       # hors /api/ : la balise <img> envoie le cookie de session, pas le jeton de la page
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                octets, mime = _images.read_image(chemin[len("/image/"):])
            except ValueError:
                return self._envoyer(404, {"erreur": _t("Image inconnue.")})
            return self._envoyer(200, octets, mime, {"Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin.startswith("/piece/"):                       # télécharger de nouveau un fichier envoyé par l'utilisateur, sous son vrai nom
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                octets, mime, nom = _fichiers.part_read(chemin[len("/piece/"):], (q.get("nom") or [""])[0])
            except ValueError as e:
                return self._envoyer(404, {"erreur": str(e)})
            return self._envoyer(200, octets, mime, {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nom), "Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin.startswith("/fichier/"):                     # télécharger un fichier produit pendant une conversation (cookie de session, comme /image/)
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                _, ident, fichier_id = chemin.split("/", 3)[1:]
                octets, mime, nom = _fichiers.read(ident, fichier_id)
            except ValueError as e:
                return self._envoyer(404, {"erreur": str(e)})
            return self._envoyer(200, octets, mime, {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nom), "Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin in ("/manifest.webmanifest", "/icone.svg", "/logo.svg") or re.match(r"^/icone-(180|192|512)\.png$", chemin):
            return self._statique_pwa(chemin)
        if chemin == "/api/conversation" and self._via_relais:          # the machine protocol: a paired machine reads a conversation it leads here
            try:
                ident = (re.search(r"id=([0-9a-f]+)", self.path) or [None, ""])[1]
                return self._envoyer(200, dict(_m.conv_read(ident), options=_m.options_read(ident)))          # + les options de cette conversation (accords automatiques, mode…)
            except ValueError as erreur:
                return self._envoyer(404, {"erreur": str(erreur)})
        return self._envoyer(404, {"erreur": "introuvable"})

    def _statique_pwa(self, chemin):
        """Manifeste et icônes pour « Ajouter à l'écran d'accueil » (téléphone). Les icônes sont dessinées par le serveur : aucun fichier image à fournir."""
        if chemin == "/manifest.webmanifest":
            manifeste = {"name": "Lutin", "short_name": "Lutin", "description": "Assistant IA local", "start_url": "/", "scope": "/", "display": "standalone",
                         "background_color": "#0b0f14", "theme_color": "#0b0f14",
                         "icons": [{"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"}, {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]}
            return self._envoyer(200, manifeste, "application/manifest+json; charset=utf-8")
        if chemin in ("/icone.svg", "/logo.svg"):
            return self._envoyer(200, _m.ICONE_SVG, "image/svg+xml; charset=utf-8")
        return self._envoyer(200, _m.icon_png(int(re.search(r"(\d+)", chemin).group(1))), "image/png")


    def _taille_corps(self):
        """La taille annoncée du corps de la requête : un nombre positif ou nul ; une valeur absurde (négative ou pas un nombre) vaut « trop gros », jamais une lecture sans fin."""
        brut = str(self.headers.get("Content-Length") or "0").strip()
        return int(brut) if brut.isascii() and brut.isdigit() else 1 << 40


    def _image(self):
        """Une image jointe : corps brut (le type est reconnu au contenu), au plus 8 Mo."""
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        taille = self._taille_corps()
        if taille > _images.MAX_SIZE:
            return self._envoyer(413, {"erreur": _t("Image trop grosse ({} Mo au plus).").format(_images.MAX_SIZE // (1024 * 1024))})
        try:
            return self._envoyer(200, {"id": _images.save(self.rfile.read(taille))})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _document(self):
        """Un document ou fichier texte joint : corps brut, nom dans l'en-tête X-Nom (encodé en URL), au plus 20 Mo ; le texte est extrait tout de suite."""
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        taille = self._taille_corps()
        if taille > _pieces.MAX_SIZE:
            return self._envoyer(413, {"erreur": _t("Fichier trop gros ({} Mo au plus).").format(_pieces.MAX_SIZE // (1024 * 1024))})
        try:
            ident, nom, caracteres = _pieces.save(self.rfile.read(taille), urllib.parse.unquote(self.headers.get("X-Nom") or ""))
            return self._envoyer(200, {"id": ident, "nom": nom, "caracteres": caracteres})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _api_v1_ecriture(self, methode):
        """PATCH et DELETE n'existent que pour l'API versionnée ; comme tout ce qui modifie, la requête doit venir de la page de Lutin (contrôle de l'origine)."""
        if not self._controle(True):
            return
        if not self.path.split("?")[0].startswith("/api/v1/"):
            _api_v1.discard_body(self)                             # un refus sans lire le corps fait réinitialiser la connexion chez l'appelant, même pour deux octets
            return self._envoyer(404, {"erreur": "introuvable"})
        return _api_v1.dispatch(self, methode)

    def do_PATCH(self):
        return self._api_v1_ecriture("PATCH")

    def do_DELETE(self):
        return self._api_v1_ecriture("DELETE")

    def do_POST(self):
        if not self._controle(True):
            return
        if self.path.split("?")[0].startswith("/api/v1/"):
            return _api_v1.dispatch(self, "POST")
        if self.path.startswith("/api/noeud/relais/"):
            return self._relais("POST")
        if self.path == "/api/image" and self._via_relais:
            return self._image()
        if self.path == "/api/document" and self._via_relais:
            return self._document()
        taille = self._taille_corps()
        if taille > 2_000_000:
            return self._envoyer(413, {"erreur": "message trop gros"})
        try:
            donnees = json.loads(self.rfile.read(taille) or b"{}")
        except (ValueError, RecursionError):
            return self._envoyer(400, {"erreur": "JSON invalide"})
        if not isinstance(donnees, dict):
            return self._envoyer(400, {"erreur": "JSON invalide : un objet est attendu"})
        if self.path == "/api/appairer":                      # le seul POST sans authentification : il sert justement à en obtenir une
            return self._appairer(donnees)
        if self.path == "/api/noeud/appairer":                 # une autre machine échange le code affiché ici contre un jeton de nœud
            return self._noeud_appairer(donnees)
        if self.path == "/api/noeud/chat":                     # ... et l'utilise pour faire tourner le moteur de cette machine
            return self._noeud_chat(donnees)
        if self.path == "/api/noeud/partage":                  # ... ou pour LIRE ce que son propriétaire a accepté de partager (conversations, skills, mémoire) ; jamais écrire
            if not _machines.node_token_valid(self.headers.get("X-Noeud")):
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            try:
                return self._envoyer(200, _machines.node_share(str(donnees.get("genre", "")), donnees))
            except PermissionError:
                return self._envoyer(403, {"erreur": "ce nœud ne partage pas cela"})
            except (ValueError, OSError) as e:
                return self._envoyer(400, {"erreur": str(e)})
        if self.path == "/api/noeud/capacites":                # ... ou pour savoir ce qu'un de ses modèles sait faire (outils, images, réflexion)
            if not _machines.node_token_valid(self.headers.get("X-Noeud")):
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            mo = _moteurs.by_id(_m.settings().get("moteur") or _moteurs.OLLAMA)
            return self._envoyer(200, {"capacites": _machines.node_capabilities(mo, donnees.get("modele"))})
        if self.path == "/api/noeud/eteindre":                 # ... ou, si le propriétaire l'a autorisé, pour l'éteindre (30 s, annulable, journalisé)
            return self._noeud_eteindre(donnees)
        if self.path == "/api/noeud/maj":                      # ... ou, si le propriétaire l'a autorisé, pour mettre Lutin à jour ici (puis redémarrage si Lutin est supervisé)
            return self._noeud_maj()
        if self.path == "/api/noeud/demande":                  # ... ou pour DEMANDER un droit (rien n'est accordé : le propriétaire de cette machine répond)
            nom = _machines.node_token_valid(self.headers.get("X-Noeud"))
            if not nom:
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            try:
                return self._envoyer(200, dict(_machines.node_request(nom, str(donnees.get("droit", ""))), ok=True))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        if not self._via_relais:                               # below: only the routes of the machine protocol, reached through /api/noeud/relais (RELAIS_POST)
            return self._envoyer(404, {"erreur": "introuvable"})
        try:
            if self.path == "/api/chat":
                return self._chat(donnees)
            if self.path == "/api/annuler-tour":
                return self._envoyer(200, _m.undo_turn(str(donnees.get("conversation", ""))))
            if self.path == "/api/epingler" and str(donnees.get("id", "")) in _m.ACTIVE_TURNS:
                return self._envoyer(409, {"erreur": _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")})
            if self.path == "/api/epingler":
                return self._envoyer(200, _m.pin_conversation(str(donnees.get("id", "")), donnees.get("epingle")))
            if self.path == "/api/memoire-choix":                                   # ancienne réponse à « fiche de suivi ou résumé ? » : la question n'est plus posée (ADR 0019), toujours 409
                if not _m.answer_memory_choice(str(donnees.get("conversation", "")), str(donnees.get("choix", "")), donnees.get("garder")):
                    return self._envoyer(409, {"erreur": _t("Plus de question en attente pour cette conversation.")})
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/arreter":
                return self._envoyer(200, _m.stop_conversation(str(donnees.get("conversation", ""))))
            if self.path == "/api/approuver":
                _m.answer_pending(str(donnees.get("id", "")), donnees.get("ok"), bool(donnees.get("reactiver")))
                return self._envoyer(200, {"ok": True})
            if self.path in ("/api/supprimer", "/api/renommer", "/api/epingler") and str(donnees.get("id", "")) in _m.ACTIVE_TURNS:
                return self._envoyer(409, {"erreur": _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")})          # sinon la fin de la réponse réécrirait la conversation par-dessus
            if self.path == "/api/supprimer":
                _mission.forget_conversation(str(donnees.get("id", "")))                  # sa mission, s'il y en a une, s'arrête avec elle
                _m.conv_delete(str(donnees.get("id", "")))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/renommer":
                c = _m.conv_rename(str(donnees.get("id", "")), str(donnees.get("titre", "")))
                return self._envoyer(200, {"ok": True, "titre": c["titre"]})
        except (ValueError, OSError, TypeError, subprocess.SubprocessError) as erreur:
            return self._envoyer(400, {"erreur": str(erreur)})
        return self._envoyer(404, {"erreur": "introuvable"})

    # ---- ce Lutin prête son moteur à une autre machine (voir lutin.machines) ----


    _catalogue_colibri = staticmethod(lambda mo, installes, q: _geres.colibri_catalog(mo, installes, q))

    def _noeud_etat(self):
        if not _machines.node_token_valid(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        mo = _moteurs.by_id(_m.settings().get("moteur") or _moteurs.OLLAMA)
        return self._envoyer(200, _machines.node_state(mo, mo.modeles(), self.request.getsockname()[0], _machines.node_load(bool(_m.ACTIVE_TURNS), self.NOEUD_ACTIFS["n"]), _machines.node_token_valid(self.headers.get("X-Noeud")) or ""))

    def _noeud_appairer(self, donnees):
        if not _m.PIN_LIMITER.autoriser(self.client_address[0]):
            return self._envoyer(429, {"erreur": "Trop d'essais : attends une minute."})
        try:
            return self._envoyer(200, _machines.node_exchange(donnees.get("code"), donnees.get("nom"), self.request.getsockname()[0]))
        except ValueError as e:
            return self._envoyer(403, {"erreur": str(e)})

    def _noeud_eteindre(self, donnees):
        nom = _machines.node_token_valid(self.headers.get("X-Noeud"))
        if not nom:
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        if not _machines.node().get("extinction"):
            return self._envoyer(403, {"erreur": "l'extinction à distance n'est pas autorisée sur cette machine"})
        if donnees.get("annuler"):
            return self._envoyer(200, {"annulee": _alimentation.cancel_shutdown(_machines.log_event)})
        try:
            return self._envoyer(200, {"dans_s": _alimentation.schedule_shutdown(nom, journaliser=_machines.log_event)})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _noeud_maj(self):
        if not _machines.node_token_valid(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        if not _machines.node().get("maj"):
            return self._envoyer(403, {"erreur": "la mise à jour à distance n'est pas autorisée sur cette machine"})
        try:
            _machines.log_event("mise à jour demandée par une machine appairée")
            return self._envoyer(200, {"ok": True, "maj": _acces.update()})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    RELAIS_GET = re.compile(r"^/(api/conversation\?id=[0-9a-f]{8}|image/[A-Za-z0-9_.\-]{1,80}|piece/[A-Za-z0-9_.\-]{1,80}(\?nom=[^&\s]{0,300})?|fichier/[0-9a-f]{8}/[A-Za-z0-9_.\-]{1,80})$")
    RELAIS_POST = ("/api/chat", "/api/arreter", "/api/approuver", "/api/annuler-tour", "/api/memoire-choix", "/api/image", "/api/document", "/api/renommer", "/api/epingler", "/api/supprimer")

    def _relais(self, methode):
        """Cette machine (l'hôte) exécute ce qu'une machine appairée lui demande dans une de SES conversations : le tour entier, avec ses modèles, ses outils, ses addons ; les fichiers restent ici.
        Droit « piloter » (décoché par défaut), jeton de nœud, liste blanche de chemins ; les règles de cette machine (dossiers, accords) s'appliquent et rien de ce qui change les accès n'est joignable."""
        def refuser(code, corps):
            if methode == "POST":          # un refus sans lire le corps fait réinitialiser la connexion chez l'appelant : on le lit (borné) puis on le jette
                reste = min(self._taille_corps(), 64 * 1024 * 1024)
                while reste > 0:
                    morceau = self.rfile.read(min(reste, 65536))
                    if not morceau:
                        break
                    reste -= len(morceau)
            return self._envoyer(code, corps)
        nom = _machines.node_token_valid(self.headers.get("X-Noeud"))
        if not nom:
            return refuser(401, {"erreur": "machine non autorisée"})
        if not _machines.node().get("piloter"):
            return refuser(403, {"erreur": _t("Cette machine n'accepte pas de conversations pilotées à distance : son propriétaire doit cocher « Laisser les machines appairées mener des conversations ici » dans l'onglet Machines.")})
        interne = self.path[len("/api/noeud/relais"):]
        chemin = interne.split("?")[0]
        if not (self.RELAIS_GET.match(interne) if methode == "GET" else chemin in self.RELAIS_POST):
            return refuser(404, {"erreur": "chemin inconnu"})
        if chemin == "/api/chat":
            _machines.log_event("conversation menée ici par {}".format(nom))
        self._via_relais, self.path = nom, interne
        return self.do_GET() if methode == "GET" else self.do_POST()


    NOEUD_PLACES = threading.BoundedSemaphore(2)          # deux demandes de machines à la fois au plus : une seule carte graphique
    NOEUD_ACTIFS = {"n": 0}          # demandes d'autres machines en cours ici (montré dans l'état du nœud)
    ATTENTE_LOCAL_S = 120          # une demande d'une autre machine laisse passer l'utilisateur de CETTE machine : au plus ce temps d'attente avant de passer quand même

    def _laisser_passer_l_utilisateur_local(self):
        """Le moteur est partagé : si quelqu'un utilise Lutin sur cette machine, la demande de l'autre machine attend la fin de son tour (au plus ATTENTE_LOCAL_S), puis passe. Le propriétaire de la carte graphique passe en premier."""
        fin = time.monotonic() + self.ATTENTE_LOCAL_S
        while _m.ACTIVE_TURNS and time.monotonic() < fin:
            time.sleep(0.5)

    def _noeud_chat(self, donnees):
        if not _machines.node_token_valid(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        try:
            corps = _machines.allowed_body(donnees.get("corps"))
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})
        mo = _moteurs.by_id(_m.settings().get("moteur") or _moteurs.OLLAMA)          # le moteur de CETTE machine : jamais une autre machine (pas de chaîne)
        if corps["model"] not in mo.modeles()["installes"]:
            return self._envoyer(404, {"erreur": "modèle absent de cette machine"})
        if not self.NOEUD_PLACES.acquire(blocking=False):
            return self._envoyer(429, {"erreur": "cette machine répond déjà à d'autres demandes"})
        self.NOEUD_ACTIFS["n"] += 1
        try:
            if not corps.get("stream"):
                self._laisser_passer_l_utilisateur_local()
                return self._envoyer(200, mo.chat(corps, 900))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self._laisser_passer_l_utilisateur_local()
                with mo.chat_flux(corps, 900) as flux:
                    for e in flux:
                        self.wfile.write(json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass          # l'autre machine a coupé (Arrêter) : sortir du « with » ferme le moteur, qui arrête de générer
            except ValueError as e:
                try:
                    self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8") + b"\n")
                except OSError:
                    pass
        finally:
            self.NOEUD_ACTIFS["n"] = max(0, self.NOEUD_ACTIFS["n"] - 1)
            self.NOEUD_PLACES.release()


    def _appairer(self, donnees):
        if _m.SECURITY.niveau == _sec.LOCAL:
            return self._envoyer(400, {"erreur": "Cet accès est réservé à cette machine : pas de code à saisir."})
        if not _m.PIN_LIMITER.autoriser(self.client_address[0]):
            return self._envoyer(429, {"erreur": "Trop d'essais : attends une minute."})
        nom = donnees.get("nom")
        jeton = _m.DEVICES.appairer(str(donnees.get("pin", "")), _sec.device_name(nom if isinstance(nom, str) else "", self.headers.get("User-Agent"), self._sur_cette_machine()))
        if not jeton:
            return self._envoyer(403, {"erreur": "Code incorrect ou expiré. Demande-en un nouveau sur l'ordinateur (lutin pin)."})
        return self._envoyer(200, {"ok": True}, en_tetes={"Set-Cookie": _sec.set_cookie_header(jeton, _m.SECURITY.url_publique.startswith("https://"))})

    _flux_v1 = False          # posé par lutin.api_v1 : cette demande de réponse vient de /api/v1, ses refus et ses évènements sont traduits à la frontière

    def _refus_tour(self, statut, message, code):
        """Refus d'une demande de réponse, avant que le flux commence. `code` est le code d'erreur de /api/v1 ; les routes historiques ne renvoient que le message."""
        return self._envoyer(statut, _api_v1.error(code, message) if self._flux_v1 else {"erreur": message})

    def _evenement_flux(self, evenement):
        return _api_v1.event(evenement) if self._flux_v1 else evenement

    def _chat(self, donnees):
        texte = str(donnees.get("message", "")).strip()
        if not texte or len(texte) > 60000:
            return self._refus_tour(400, "Écris un message (60 000 caractères au maximum).", "invalid_request")
        try:
            images = _images.check_list(donnees.get("images"))
            pieces = _pieces.check_list(donnees.get("pieces"))
        except ValueError as erreur:
            return self._refus_tour(400, str(erreur), "invalid_request")
        if self._via_relais:                                      # le tour s'exécute avec les réglages DE CETTE machine : ni modèle, ni mode, ni accords automatiques, ni autre machine imposés de l'extérieur
            donnees = {k: v for k, v in donnees.items() if k not in ("modele", "machine", "mode", "options", "reflexion", "travail")}
        ident = str(donnees.get("conversation") or "")
        with _m.TURNS_LOCK:                                   # trop de réponses en cours : on refuse avant de créer quoi que ce soit
            if len(_m.ACTIVE_TURNS) >= _m.CONCURRENT_TURNS and ident not in _m.ACTIVE_TURNS:
                return self._refus_tour(429, "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_m.ACTIVE_TURNS)), "too_many_turns")
        _fond.interrupt_for_user(8)                    # le travail de fond cède la place : son document en cours sera refait plus tard
        conv = _m.conv_read(ident) if ident else _m.conv_new()

        def abandon():                                            # une demande refusée ne laisse pas une conversation vide dans la liste
            if not ident:
                try:
                    _m.conv_delete(conv["id"])
                except (OSError, ValueError):
                    pass
        depuis = donnees.get("remplacer_depuis")
        if depuis is not None:
            try:
                depuis = int(depuis)
            except (TypeError, ValueError):
                abandon()
                return self._refus_tour(400, "Indice de message invalide.", "invalid_request")
            if not (0 <= depuis < len(conv["messages"]) and conv["messages"][depuis].get("role") == "user"):
                abandon()
                return self._refus_tour(400, "Ce message n'existe plus dans la conversation : recharge-la.", "invalid_request")
        if isinstance(donnees.get("options"), dict):
            _m.options_write(conv["id"], donnees["options"])                                  # les options affichées par la page deviennent celles de cette conversation (créée au premier message)
        mode_voulu = _m.options_read(conv["id"]).get("mode") or (donnees.get("mode") if not isinstance(donnees.get("options"), dict) else None) or _m.settings()["mode"]
        if mode_voulu == "mission":                                                            # mode « Mission longue » : ce message est le cahier des charges (ou une consigne), la conversation sert de compte rendu
            mission_en_cours = _mission.find_for_conversation(conv["id"])
            if not (mission_en_cours and mission_en_cours["etat"] != "terminee") and conv["id"] in _m.ACTIVE_TURNS:
                return self._refus_tour(409, "Cette conversation est déjà en train de répondre. Attends la fin ou clique sur Arrêter.", "turn_running")
            return self._mission_dans_la_conversation(conv, texte, donnees, mission_en_cours, abandon, not ident)
        try:
            siege = _turns.reserve(conv, work=str(donnees.get("travail") or ""))          # la place du tour : mêmes règles pour tous les lanceurs (ADR 0015)
        except _turns.TurnRefused as refus:
            if refus.code == _turns.TURN_RUNNING:
                return self._refus_tour(409, "Cette conversation est déjà en train de répondre (autre onglet ou téléphone ?). Attends la fin ou clique sur Arrêter.", "turn_running")
            abandon()
            if refus.code == _turns.WORKSPACE_CONFLICT:
                return self._refus_tour(409, refus.message, "workspace_conflict")
            return self._refus_tour(429, "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_turns.active())), "too_many_turns")
        fin_flux = threading.Event()
        try:
            r = _m.apply_options(_m.settings(), conv["id"])
            for k in ("modele", "reflexion", "mode"):
                if k in donnees and (k == "modele" or not isinstance(donnees.get("options"), dict)):
                    r[k] = donnees[k]
            if "machine" in donnees:          # le modèle choisi dans la liste peut être celui d'une autre machine (« » : cette machine-ci)
                ident = str(donnees.get("machine") or "")
                r["machine"] = ident if ident and _machines.find(ident) else ""
            if not _modes.is_valid(r["mode"]):
                abandon()
                return self._refus_tour(400, "Mode inconnu.", "invalid_request")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")                  # nginx (reverse proxy) n'attend pas la fin de la réponse pour la transmettre
            self.end_headers()

            page_partie, verrou_flux = [False], threading.Lock()
            try:
                self.connection.settimeout(STREAM_WRITE_TIMEOUT)
            except (OSError, ValueError):
                pass

            def ecrire(octets):
                # Si la page est fermée ou gelée (onglet en arrière-plan, téléphone verrouillé, proxy qui coupe), le tour continue et la conversation est enregistrée à la fin.
                # Une page qui ne lit plus remplit la mémoire du réseau : sans délai, l'écriture bloquerait et la réponse se figerait avec elle. Au premier échec on arrête d'écrire.
                if page_partie[0]:
                    return
                with verrou_flux:
                    try:
                        self.wfile.write(octets)
                        self.wfile.flush()
                    except (OSError, ValueError):
                        page_partie[0] = True

            def emit(evenement):
                ecrire((json.dumps(self._evenement_flux(_m.translate_event(evenement)), ensure_ascii=False) + "\n").encode("utf-8"))

            def battement():
                while not fin_flux.wait(STREAM_HEARTBEAT):                  # une ligne vide (la page l'ignore) : un reverse proxy coupe un flux resté silencieux (modèle qui charge, commande longue, attente d'un accord)
                    ecrire(b"\n")
            threading.Thread(target=battement, daemon=True).start()
            emit({"type": "debut", "conversation": conv["id"]})
            siege.run(texte, emit, r, depuis, identite=self._identite(), images=images, pieces=pieces)
        finally:
            fin_flux.set()
            siege.release()                                   # seulement si c'est encore la sienne : un tour abandonné (arreter_conversation) ne retire pas celle d'une réponse plus récente

    def _mission_dans_la_conversation(self, conv, texte, donnees, mission_en_cours, abandon, nouvelle):
        """Mode « Mission longue » : le message lance une mission menée DANS cette conversation, ou, si une mission y est déjà en cours, lui apporte une réponse ou une consigne."""
        opts = _m.options_read(conv["id"])
        extrait = texte if len(texte) <= 160 else texte[:160] + "…"
        if mission_en_cours and mission_en_cours["etat"] != "terminee":
            try:
                _mission.action("repondre", {"id": mission_en_cours["id"], "texte": texte})
            except ValueError as erreur:
                return self._refus_tour(400, str(erreur), "invalid_request")
            info = _t("✉ Noté, Lutin en tient compte à son prochain tour : {}").format(extrait)
        else:
            autonome = bool(opts.get("auto_ecriture") and opts.get("auto_commandes"))
            nom = " ".join(texte.split()[:6])[:60] or _t("Mission")
            titre_avant = conv.get("titre", "")
            try:
                if titre_avant in ("", "Nouvelle conversation"):
                    conv["titre"] = "🎯 " + nom
                    _m.conv_write(conv)
                nouvelle_mission = _mission.create(nom, texte, str(donnees.get("travail") or conv.get("travail") or ""), opts.get("mission_duree_h", 8), autonome, conv["id"])
            except ValueError as erreur:
                if nouvelle:
                    abandon()
                elif conv.get("titre") != titre_avant:
                    conv["titre"] = titre_avant
                    _m.conv_write(conv)
                return self._refus_tour(400, str(erreur), "invalid_request")
            info = (_t("🎯 Mission lancée : Lutin travaille seul, jusqu'à {} h, et tu suis tout ici. Pause ou arrêt avec les boutons au-dessus du champ de saisie.") if autonome else
                    _t("🎯 Mission lancée « à blanc » : Lutin montre ce qu'il ferait sans rien écrire ni lancer. Coche Fichiers auto et Commandes auto pour qu'il agisse vraiment (ça compte dès le tour suivant).")).format(nouvelle_mission["duree_h"])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for evenement in ({"type": "debut", "conversation": conv["id"]}, {"type": "info", "texte": info}, {"type": "fin", "conversation": {"id": conv["id"], "titre": conv.get("titre", "")}}):
            try:
                self.wfile.write((json.dumps(self._evenement_flux(evenement), ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                break

