"""Y a-t-il une version plus récente d'un moteur (llama.cpp, Ollama) que celle qui est installée ?

Même esprit que la vérification de Lutin lui-même : jamais bloquante (fil de fond), au plus une fois par 24 heures, silencieuse hors ligne ou sans réseau, désactivable (réglage `verifier_maj`),
et RIEN n'est installé sans clic. Mais aucune notification en haut de la page : l'information apparaît sur la carte du moteur, dans Réglages > Moteurs, avec un bouton pour mettre à jour.

Seules données envoyées : une requête GET anonyme vers les publications GitHub du moteur. Le résultat est gardé dans `moteurs_maj.json` du dossier de données."""
import json
import re
import threading
import time
import urllib.error
from pathlib import Path

from . import engines

INTERVALLE_S = 24 * 3600
API_OLLAMA = "https://api.github.com/repos/ollama/ollama/releases/latest"
VERROU = threading.Lock()
EN_COURS = {"actif": False}


def numeros(version):
    """Les nombres d'une version, pour les comparer : « b12167 (cuda) » -> (12167,) ; « v0.12.3 » -> (0, 12, 3) ; () si illisible."""
    m = re.search(r"(\d+(?:\.\d+)*)", str(version or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def plus_recente(derniere, actuelle):
    """Vrai si `derniere` est strictement plus récente que `actuelle` (jamais de « mise à jour » vers une version plus ancienne ou illisible)."""
    d, a = numeros(derniere), numeros(actuelle)
    return bool(d) and bool(a) and d > a


def _fichier():
    donnees = engines.CONTEXTE["donnees"]()
    return Path(donnees) / "moteurs_maj.json" if donnees else None


def lire():
    f = _fichier()
    try:
        d = json.loads(f.read_text(encoding="utf-8")) if f else {}
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _ecrire(d):
    f = _fichier()
    if f is None:
        return
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _derniere_llamacpp(mo, http_json):
    """(version installée, dernière version publiée avec les fichiers de CETTE machine) pour llama.cpp installé par Lutin ; None sinon."""
    from . import llamacpp_engine as ml
    if mo.externe() or mo.serveur_installe() is None or mo.config().get("version_epinglee"):
        return None          # une version épinglée est voulue : jamais de « mise à jour » proposée
    import platform
    actuelle = mo.version()
    variante = str(mo.config().get("variante_installee") or "cpu")
    choix = ml.choisir_fichiers((http_json or ml._http_json)(ml.API_RELEASES), ml._systeme(), platform.machine().lower(), variante)
    return (actuelle, choix[0]) if choix else None


def _derniere_colibri(mo):
    """(version installée, dernière version publiée) pour Colibri installé par Lutin ; None sinon."""
    if not hasattr(mo, "colibri_choisi") or not mo.colibri_choisi() or not mo.version():
        return None
    from . import colibri
    return mo.version(), colibri.derniere_version()


def _derniere_exllamav3(mo):
    """(version d'ExLlamaV3 installée, dernière publiée) pour ExLlamaV3 installé par Lutin ; None sinon. TabbyAPI n'a pas de publications : c'est la bibliothèque qui donne le rythme."""
    if not hasattr(mo, "exllamav3_choisi") or not mo.exllamav3_choisi() or not mo.version():
        return None
    from . import exllamav3
    return mo.version(), exllamav3.derniere_version_lib()


def _derniere_serveur(mo):
    """Le serveur géré par Lutin derrière la carte « compatible OpenAI » (Colibri ou ExLlamaV3), s'il y en a un."""
    return _derniere_colibri(mo) or _derniere_exllamav3(mo)


def _derniere_ollama(http_json):
    """(version installée, dernière version publiée) pour Ollama local et démarré ; None sinon (Docker : l'image se met à jour avec docker compose)."""
    if engines.CONTEXTE["en_docker"]():
        from . import docker_engines
        if not docker_engines.ollama_installe_par_lutin():
            return None          # Ollama de l'image ou d'un autre conteneur : il se met à jour avec docker compose
        try:
            derniere = ((http_json or docker_engines._http_json)(docker_engines.API_OLLAMA) or {}).get("tag_name", "")
            actuelle = (docker_engines.ollama_dossier() / "version.txt").read_text(encoding="utf-8").strip()
        except (OSError, ValueError, urllib.error.URLError):
            return None
        return (actuelle, derniere) if actuelle and derniere else None
    from . import ollama_client
    try:
        actuelle = ollama_client.Ollama().version()
    except (OSError, ValueError, urllib.error.URLError):
        return None
    from . import llamacpp_engine as ml
    derniere = ((http_json or ml._http_json)(API_OLLAMA) or {}).get("tag_name", "")
    return (actuelle, derniere) if actuelle and derniere else None


def verifier(force=False, http_json=None, maintenant=time.time):
    """Contrôle chaque moteur géré par Lutin (au plus une fois par 24 h, sauf `force`) et garde le résultat. Renvoie l'état complet. Les pannes réseau sont silencieuses : l'ancien résultat reste."""
    if engines.CONTEXTE["hors_ligne"]():
        return etat()
    with VERROU:
        d = lire()
        for mo in engines.liste():
            ancien = d.get(mo.id) or {}
            if not force and maintenant() - float(ancien.get("verifie") or 0) < INTERVALLE_S:
                continue
            try:
                if mo.id == "llamacpp":
                    r = _derniere_llamacpp(mo, http_json)
                elif mo.id == "ollama":
                    r = _derniere_ollama(http_json)
                elif mo.id == "openai":
                    r = _derniere_serveur(mo)
                else:
                    r = None
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                continue          # pas de réseau, GitHub limite les requêtes… : on réessaiera plus tard
            d[mo.id] = {"actuelle": r[0] if r else "", "derniere": r[1] if r else "", "verifie": maintenant()}
        _ecrire(d)
    return etat()


def etat():
    """{identifiant: {actuelle, derniere, disponible, verifie}} d'après le dernier contrôle. `disponible` est recalculé avec la version installée MAINTENANT (après une mise à jour, l'avis disparaît sans attendre)."""
    sortie = {}
    for ident, e in lire().items():
        if not isinstance(e, dict) or not e.get("derniere"):
            continue
        mo = engines.MOTEURS.get(ident)
        actuelle = (mo.version() if mo is not None and ident in ("llamacpp", "openai") else "") or e.get("actuelle", "")
        sortie[ident] = {"actuelle": actuelle, "derniere": e["derniere"], "disponible": plus_recente(e["derniere"], actuelle), "verifie": e.get("verifie", 0)}
    return sortie


def oublier(ident):
    """Après une mise à jour (ou une réinstallation), le résultat gardé n'est plus vrai : le prochain contrôle le refera."""
    with VERROU:
        d = lire()
        if d.pop(ident, None) is not None:
            _ecrire(d)


def en_arriere_plan(activer=True):
    """Lance un contrôle dans un fil si le dernier date de plus de 24 h (et pas un autre en cours). Jamais bloquant, jamais bruyant."""
    if not activer or EN_COURS["actif"]:
        return
    d = lire()
    if d and all(time.time() - float((d.get(m.id) or {}).get("verifie") or 0) < INTERVALLE_S for m in engines.liste() if m.id in ("llamacpp", "ollama")):
        return
    EN_COURS["actif"] = True

    def travail():
        try:
            verifier()
        except Exception:  # noqa: BLE001  (jamais bloquant)
            pass
        finally:
            EN_COURS["actif"] = False
    threading.Thread(target=travail, daemon=True, name="verification-moteurs").start()

