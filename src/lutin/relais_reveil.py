"""Relais de réveil : pour un Lutin dans Docker en réseau « bridge », qui ne peut pas diffuser sur le réseau local.

Un petit programme tourne SUR LE RÉSEAU DE L'HÔTE (docker-compose.wake.yml) et envoie le paquet de réveil à la place du conteneur. Il n'accepte qu'une seule chose : « réveille cette adresse MAC »,
et seulement avec le secret partagé (LUTIN_WAKE_TOKEN). Bibliothèque standard seulement."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import alimentation
from .i18n import t as _t

PORT = 8778


def fabriquer(token, envoyer=alimentation.envoyer_reveil):
    class Relais(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _repondre(self, code, corps):
            octets = json.dumps(corps).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(octets)))
            self.end_headers()
            self.wfile.write(octets)

        def do_POST(self):
            if self.path != "/wake":
                return self._repondre(404, {"erreur": "?"})
            if not hmac.compare_digest(self.headers.get("X-Token", ""), token):
                return self._repondre(403, {"erreur": "token"})
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                demande = json.loads(self.rfile.read(n) or b"{}")
                envoyes = envoyer(str(demande.get("mac", "")), str(demande.get("host", "")))
            except (ValueError, TypeError) as e:
                return self._repondre(400, {"erreur": str(e)})
            self._repondre(200, {"ok": True, "envois": len(envoyes)})
    return Relais


def servir(port=PORT, token=None, bind="0.0.0.0"):
    token = token if token is not None else os.environ.get("LUTIN_WAKE_TOKEN", "")
    if len(token) < 16:
        raise ValueError(_t("Le secret du relais (LUTIN_WAKE_TOKEN) est absent ou trop court (16 caractères au moins)."))
    ThreadingHTTPServer((bind, port), fabriquer(token)).serve_forever()


def via_relais(mac, adresse_machine="", ouvrir=None):
    """Demande au relais (LUTIN_WAKE_RELAY, avec LUTIN_WAKE_TOKEN) d'envoyer le paquet. Renvoie le nombre d'envois, ou None s'il n'y a pas de relais configuré. Lève ValueError s'il refuse ou ne répond pas."""
    url = os.environ.get("LUTIN_WAKE_RELAY", "").strip().rstrip("/")
    if not url:
        return None
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url + "/wake", data=json.dumps({"mac": mac, "host": adresse_machine}).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": os.environ.get("LUTIN_WAKE_TOKEN", "")})
    try:
        with (ouvrir or urllib.request.urlopen)(req, timeout=5) as r:
            return int(json.loads(r.read()).get("envois", 0))
    except urllib.error.HTTPError as e:
        raise ValueError(_t("Le relais de réveil a refusé la demande (code {}) : le secret LUTIN_WAKE_TOKEN est-il le même des deux côtés ?").format(e.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError(_t("Le relais de réveil ne répond pas : est-il démarré (docker-compose.wake.yml) ?")) from None
