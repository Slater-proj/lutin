"""Mode hors ligne strict : plus aucune connexion vers Internet, seulement vers cette machine et les services que tu as toi-même configurés.

Autorisés : l'adresse locale (127.0.0.1, localhost), l'adresse d'Ollama (OLLAMA_URL), et celles des extensions déclarées (LUTIN_OUTIL_URL, COMFY_URL).
Bloqués : recherche et lecture web, catalogue en ligne, empreintes du registre d'Ollama, téléchargement de modèles, mise à jour de Lutin.

Le mode est lu dans config.json (clé `hors_ligne`), ou forcé par la variable LUTIN_HORS_LIGNE=1 (conteneur, poste isolé). Chaque point qui sort sur Internet appelle
`garde(url)` ou `exiger_en_ligne(action)` : un seul endroit à auditer. Le test `test_hors_ligne.py` surveille les connexions réelles.
"""
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

LOCAUX = {"127.0.0.1", "localhost", "::1", "[::1]"}
_cache = {"chemin": "", "mtime": None, "valeur": False}
_verrou = threading.Lock()


class HorsLigne(OSError):
    """Une action qui demande Internet a été refusée parce que le mode hors ligne strict est actif."""


def _vrai(valeur):
    return str(valeur).strip().lower() in ("1", "true", "oui", "yes", "on")


def actif(chemin_config=None):
    """Vrai si le mode hors ligne strict est actif. Relit config.json seulement quand il a changé."""
    if _vrai(os.environ.get("LUTIN_HORS_LIGNE", "")):
        return True
    chemin = str(chemin_config or os.environ.get("LUTIN_CONFIG") or "")
    if not chemin:
        return False
    try:
        mtime = Path(chemin).stat().st_mtime_ns
    except OSError:
        return False
    with _verrou:
        if _cache["chemin"] == chemin and _cache["mtime"] == mtime:
            return _cache["valeur"]
        try:
            valeur = bool(json.loads(Path(chemin).read_text(encoding="utf-8")).get("hors_ligne"))
        except (OSError, ValueError, AttributeError):
            valeur = False
        _cache.update(chemin=chemin, mtime=mtime, valeur=valeur)
        return valeur


def definir(valeur, chemin_config=None):
    """Active ou coupe le mode (écrit dans config.json). Renvoie le nouvel état."""
    chemin = Path(str(chemin_config or os.environ.get("LUTIN_CONFIG") or ""))
    if not str(chemin) or str(chemin) == ".":
        raise ValueError("Pas de fichier de configuration.")
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
    with _verrou:
        _cache["mtime"] = None
    return bool(valeur)


def hotes_autorises(env=None):
    """Les machines avec lesquelles Lutin a le droit de parler même en mode strict."""
    env = os.environ if env is None else env
    hotes = set(LOCAUX)
    for cle in ("OLLAMA_URL", "LUTIN_OUTIL_URL", "COMFY_URL"):
        h = urlparse(env.get(cle, "")).hostname
        if h:
            hotes.add(h.lower())
    return hotes


def garde(url, chemin_config=None):
    """À appeler avant toute connexion sortante. Ne fait rien hors mode strict ; sinon refuse tout hôte non autorisé."""
    if not actif(chemin_config):
        return
    hote = (urlparse(url).hostname or "").lower()
    if hote not in hotes_autorises():
        raise HorsLigne("Mode hors ligne strict : la connexion vers {} est refusée. Désactive-le pour utiliser Internet (lutin hors-ligne non).".format(hote or "cette adresse"))


def exiger_en_ligne(action, chemin_config=None):
    """Pour les actions qui passent par un autre programme (Ollama télécharge lui-même ses modèles) : on ne peut pas contrôler l'adresse, on refuse l'action."""
    if actif(chemin_config):
        raise HorsLigne("Mode hors ligne strict : impossible de {}. Désactive-le pour continuer (lutin hors-ligne non).".format(action))
