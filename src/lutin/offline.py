"""Mode hors ligne strict : plus aucune connexion vers Internet, seulement vers cette machine et les services que tu as toi-même configurés.

Autorisés : l'adresse locale (127.0.0.1, localhost), l'adresse d'Ollama (OLLAMA_URL), et celles des extensions déclarées (LUTIN_OUTIL_URL, COMFY_URL).
Bloqués : recherche et lecture web, catalogue en ligne, empreintes du registre d'Ollama, téléchargement de modèles, mise à jour de Lutin.

Le mode est lu dans config.json (clé `hors_ligne`), ou forcé par la variable LUTIN_HORS_LIGNE=1 (conteneur, poste isolé). Chaque point qui sort sur Internet appelle
`guard(url)` ou `require_online(action)`. The single net (`install_net`, put in place by `lutin.cli.main`) also refuses a connection to a public
address from a caller that forgot `guard`. Le test `test_hors_ligne.py` surveille les connexions réelles.
"""
import ipaddress
import json
import os
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
from .i18n import t as _t

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
_cache = {"chemin": "", "mtime": None, "valeur": False}
_lock = threading.Lock()


class OfflineError(OSError):
    """Une action qui demande Internet a été refusée parce que le mode hors ligne strict est actif."""


def _truthy(valeur):
    return str(valeur).strip().lower() in ("1", "true", "oui", "yes", "on")


def is_active(chemin_config=None):
    """Vrai si le mode hors ligne strict est actif. Relit config.json seulement quand il a changé."""
    if _truthy(os.environ.get("LUTIN_HORS_LIGNE", "")):
        return True
    chemin = str(chemin_config or os.environ.get("LUTIN_CONFIG") or "")
    if not chemin:
        return False
    try:
        mtime = Path(chemin).stat().st_mtime_ns
    except OSError:
        return False
    with _lock:
        if _cache["chemin"] == chemin and _cache["mtime"] == mtime:
            return _cache["valeur"]
        try:
            valeur = bool(json.loads(Path(chemin).read_text(encoding="utf-8")).get("hors_ligne"))
        except (OSError, ValueError, AttributeError):
            valeur = False
        _cache.update(chemin=chemin, mtime=mtime, valeur=valeur)
        return valeur


def set_mode(valeur, chemin_config=None):
    """Active ou coupe le mode (écrit dans config.json). Renvoie le nouvel état."""
    chemin = Path(str(chemin_config or os.environ.get("LUTIN_CONFIG") or ""))
    if not str(chemin) or str(chemin) == ".":
        raise ValueError(_t("Pas de fichier de configuration."))
    try:
        cfg = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    cfg["hors_ligne"] = bool(valeur)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)
    with _lock:
        _cache["mtime"] = None
    return bool(valeur)


def allowed_hosts(env=None):
    """Les machines avec lesquelles Lutin a le droit de parler même en mode strict."""
    env = os.environ if env is None else env
    hotes = set(LOCAL_HOSTS)
    for cle in ("OLLAMA_URL", "LUTIN_OUTIL_URL", "COMFY_URL"):
        h = urlparse(env.get(cle, "")).hostname
        if h:
            hotes.add(h.lower())
    return hotes


def guard(url, chemin_config=None):
    """À appeler avant toute connexion sortante. Ne fait rien hors mode strict ; sinon refuse tout hôte non autorisé."""
    if not is_active(chemin_config):
        return
    hote = (urlparse(url).hostname or "").lower()
    if hote not in allowed_hosts():
        raise OfflineError(_t("Mode hors ligne strict : la connexion vers {} est refusée. Désactive-le pour utiliser Internet (lutin offline off).").format(hote or _t("cette adresse")))


def require_online(action, chemin_config=None):
    """Pour les actions qui passent par un autre programme (Ollama télécharge lui-même ses modèles) : on ne peut pas contrôler l'adresse, on refuse l'action."""
    if is_active(chemin_config):
        raise OfflineError(_t("Mode hors ligne strict : impossible de {}. Désactive-le pour continuer (lutin offline off).").format(action))


# ------------------------------------------------------------------------------------------------ the single net
# `guard(url)` above depends on every caller remembering it (a forgotten one let the llama.cpp search reach Hugging Face). The net below does not: once
# installed (lutin.cli.main, so every command and the server), Python itself calls it before any socket of this process connects or sends, and in
# strict mode it refuses an address that is neither this machine nor the local network. The callers keep `guard`: its message says what was refused
# before anything is tried, the net is what holds when one forgets.
_SHARED = ipaddress.ip_network("100.64.0.0/10")          # shared address space: Tailscale and carrier NAT, a network the user set up, not the internet
_NET = {"installed": False}


def _ip_allowed(text):
    try:
        ip = ipaddress.ip_address(str(text).split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local or (ip.version == 4 and ip in _SHARED)


def address_allowed(host):
    """True for this machine, the local network (private, link-local, shared addresses, IPv6 unique local) and the hosts allowed by name
    (allowed_hosts). A name is resolved here and allowed only when every address it gives is."""
    host = str(host or "").strip("[]").lower()
    if not host or host in allowed_hosts() or _ip_allowed(host):
        return bool(host)
    try:
        ipaddress.ip_address(host.split("%")[0])
        return False                                      # a public address
    except ValueError:
        pass
    try:
        found = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return bool(found) and all(_ip_allowed(address) for address in found)


def _audit(event, args):
    if event not in ("socket.connect", "socket.sendto"):
        return
    address = args[1] if len(args) > 1 else None
    if not isinstance(address, tuple) or not address or not is_active():
        return                                            # a Unix socket (a path), or the mode is off
    if not address_allowed(address[0]):
        raise OfflineError(_t("Mode hors ligne strict : la connexion vers {} est refusée. Désactive-le pour utiliser Internet (lutin offline off).").format(address[0]))


def install_net():
    """Puts the net in place for this process (once: an audit hook cannot be removed). It costs one comparison per audited event while the mode is off."""
    if not _NET["installed"]:
        sys.addaudithook(_audit)
        _NET["installed"] = True
