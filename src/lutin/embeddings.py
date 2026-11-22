"""Recherche par le sens (facultative) : retrouver un passage de la conversation même s'il n'emploie pas les mêmes mots que la question.

La recherche par mots (recall.py) trouve « prison » quand on écrit « prison », pas « détention ». Un petit modèle d'embeddings d'Ollama (nomic-embed-text, environ 270 Mo) transforme chaque passage en un
vecteur de nombres : deux passages de même sens ont des vecteurs proches. Lutin combine les deux recherches (fusion des rangs) : les mots ET le sens.

Règles de solidité :
- désactivée par défaut ; sans le modèle installé, ou si Ollama ne répond pas, Lutin retombe sur la recherche par mots, sans erreur (et n'insiste pas pendant une minute) ;
- les vecteurs sont gardés sur le disque (donnees/embeddings/<conversation>.json), un par passage : un passage n'est vectorisé qu'une fois ;
- la vectorisation des passages manquants est bornée en temps à chaque réponse (une longue conversation se vectorise sur quelques réponses, sans jamais faire attendre longtemps) ;
- la similarité minimale évite de remettre au modèle des passages « vaguement proches » ;
- l'installation du modèle est un téléchargement lancé par le bouton de la page, en arrière-plan, avec sa progression."""
import array
import base64
import hashlib
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

from . import core as _m

DEFAULT_MODEL = "nomic-embed-text"
RE_MODEL = re.compile(r"^[A-Za-z0-9_./:-]{1,100}$")
BATCH = 16                       # passages vectorisés par appel
THRESHOLD = 0.55                   # similarité (cosinus) minimale pour compter comme « du même sens »
PAUSE_AFTER_FAILURE = 60         # secondes sans réessayer après un échec (modèle absent, Ollama éteint)
FAILURE = {"jusqua": 0.0, "vu": False}
INSTALLED_CACHE = {"t": 0.0, "v": False, "modele": ""}
LOCK = threading.Lock()


def active():
    return bool(_m.reglages().get("recherche_sens"))


def model_name():
    m = str(_m.reglages().get("modele_embeddings") or DEFAULT_MODEL).strip()
    return m if RE_MODEL.match(m) else DEFAULT_MODEL


def installed(forcer=False):
    """Le modèle est-il installé sur le moteur choisi ? (résultat gardé 20 secondes : la page interroge souvent)"""
    modele = model_name()
    if not forcer and INSTALLED_CACHE["modele"] == modele and time.time() - INSTALLED_CACHE["t"] < 20:
        return INSTALLED_CACHE["v"]
    base = modele.split(":")[0]
    v = any(n.split(":")[0] == base for n in (_m.etat_moteur() if _m.moteur_actuel().id != "ollama" else _m.etat_ollama()).get("installes", []))
    INSTALLED_CACHE.update(t=time.time(), v=v, modele=modele)
    return v


def is_search_model(nom):
    """Vrai pour le modèle de recherche par le sens (il ne discute pas : jamais proposé comme modèle de conversation)."""
    from . import model_info
    base = str(nom).split(":")[0]
    if base == model_name().split(":")[0]:
        return True
    return bool((model_info.already_known(str(nom), _m.DONNEES) or {}).get("embedding"))


def state():
    return {"actif": active(), "modele": model_name(), "installe": installed(), "installation": installation_state()}


# --------------------------------------------------------------------------- vecteurs
def _normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array.array("f", (x / n for x in v))


def vectors(textes, modele=None, delai=60):
    """Les vecteurs (normalisés) d'une liste de textes, par Ollama. Lève ValueError/URLError si Ollama ne répond pas ou si le modèle est absent."""
    liste = _m.moteur_actuel().vecteurs(modele or model_name(), [str(t)[:1500] or " " for t in textes], delai)          # Ollama, ou le moteur choisi (llama.cpp en mode routeur, serveur externe)
    return [_normalize(v) for v in liste]


def _key(texte):
    return hashlib.sha1(str(texte)[:1500].encode("utf-8")).hexdigest()[:16]


def _path(ident):
    return _m.DONNEES / "embeddings" / (str(ident) + ".json")


def _load(ident, modele):
    brut = _m.read_json(_path(ident), {})
    if brut.get("modele") != modele:
        return {}                                                     # un autre modèle d'embeddings : ses vecteurs ne sont pas comparables
    cache = {}
    for h, b64 in (brut.get("v") or {}).items():
        try:
            v = array.array("f")
            v.frombytes(base64.b64decode(b64))
            cache[h] = v
        except (ValueError, TypeError):
            continue
    return cache


def _save(ident, modele, cache, gardes):
    """Écrit les vecteurs de ces passages seulement (ceux qui n'existent plus dans la conversation sont oubliés)."""
    v = {h: base64.b64encode(cache[h].tobytes()).decode("ascii") for h in gardes if h in cache}
    _m.write_atomic(_path(ident), json.dumps({"modele": modele, "v": v}))


def remove(ident):
    try:
        _path(ident).unlink(missing_ok=True)
    except OSError:
        pass


def clean_orphans(ids_existants):
    n = 0
    try:
        for f in (_m.DONNEES / "embeddings").glob("*.json"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return n


def similarities(ident, morceaux, question, budget=8.0):
    """{indice du morceau: similarité avec la question} pour les morceaux déjà vectorisés. Vectorise les morceaux manquants tant que `budget` secondes ne sont pas écoulées (le reste, aux réponses suivantes).
    {} si la recherche par le sens est coupée, si le modèle est absent ou si Ollama ne répond pas."""
    if not active() or time.time() < FAILURE["jusqua"] or not morceaux:
        return {}
    modele = model_name()
    debut = time.time()
    try:
        q = vectors([question], modele)[0]
        cache = _load(ident, modele)
        manquants = [(i, _key(m["texte"])) for i, m in enumerate(morceaux) if _key(m["texte"]) not in cache]
        nouveau = False
        for a in range(0, len(manquants), BATCH):
            if time.time() - debut > budget:
                break
            lot = manquants[a:a + BATCH]
            for (i, h), v in zip(lot, vectors([morceaux[i]["texte"] for i, _ in lot], modele)):
                cache[h] = v
            nouveau = True
        if nouveau:
            _save(ident, modele, cache, {_key(m["texte"]) for m in morceaux})
        FAILURE["vu"] = False
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        FAILURE["jusqua"] = time.time() + PAUSE_AFTER_FAILURE
        if not FAILURE["vu"]:
            FAILURE["vu"] = True
            _m.journaliser("Recherche par le sens indisponible ({!r}) : recherche par mots seulement.".format(erreur))
        return {}
    sims = {}
    for i, m in enumerate(morceaux):
        v = cache.get(_key(m["texte"]))
        if v is not None and len(v) == len(q):
            sims[i] = sum(a * b for a, b in zip(q, v))
    return sims


# --------------------------------------------------------------------------- installation du modèle
def installation_state():
    """Où en est le téléchargement du modèle de recherche : {etat: '' | 'en cours' | 'fini' | 'erreur', fait, total, erreur}. C'est le même suivi que pour tous les modèles (onglet Modèles)."""
    p = (_m.PULLS.get(model_name()) or {})
    etat_ = {"en cours": "en cours", "termine": "fini", "erreur": "erreur"}.get(p.get("statut"), "")
    return {"etat": etat_, "fait": int(p.get("fait") or 0), "total": int(p.get("total") or 0), "erreur": str(p.get("texte") or "") if etat_ == "erreur" else "", "texte": str(p.get("texte") or "")}


def start_installation():
    """Télécharge le modèle de recherche dans Ollama, en arrière-plan : il entre dans la liste de l'onglet Modèles comme les autres (progression, suppression)."""
    _m.installer_modele(model_name())
    INSTALLED_CACHE["t"] = 0.0
    FAILURE["jusqua"] = 0.0
    return installation_state()
