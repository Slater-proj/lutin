"""Recherche par le sens (facultative) : retrouver un passage de la conversation même s'il n'emploie pas les mêmes mots que la question.

La recherche par mots (rappel.py) trouve « prison » quand on écrit « prison », pas « détention ». Un petit modèle d'embeddings d'Ollama (nomic-embed-text, environ 270 Mo) transforme chaque passage en un
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

from . import moteur as _m
from .i18n import t as _t

MODELE_DEFAUT = "nomic-embed-text"
RE_MODELE = re.compile(r"^[A-Za-z0-9_./:-]{1,100}$")
LOT = 16                       # passages vectorisés par appel
SEUIL = 0.55                   # similarité (cosinus) minimale pour compter comme « du même sens »
PAUSE_APRES_ECHEC = 60         # secondes sans réessayer après un échec (modèle absent, Ollama éteint)
ECHEC = {"jusqua": 0.0, "vu": False}
INSTALLATION = {"etat": "", "fait": 0, "total": 0, "erreur": ""}
INSTALLE_CACHE = {"t": 0.0, "v": False, "modele": ""}
VERROU = threading.Lock()


def actif():
    return bool(_m.reglages().get("recherche_sens"))


def nom_modele():
    m = str(_m.reglages().get("modele_embeddings") or MODELE_DEFAUT).strip()
    return m if RE_MODELE.match(m) else MODELE_DEFAUT


def installe(forcer=False):
    """Le modèle est-il installé dans Ollama ? (résultat gardé 20 secondes : la page interroge souvent)"""
    modele = nom_modele()
    if not forcer and INSTALLE_CACHE["modele"] == modele and time.time() - INSTALLE_CACHE["t"] < 20:
        return INSTALLE_CACHE["v"]
    base = modele.split(":")[0]
    v = any(n.split(":")[0] == base for n in _m.etat_ollama().get("installes", []))
    INSTALLE_CACHE.update(t=time.time(), v=v, modele=modele)
    return v


def etat():
    return {"actif": actif(), "modele": nom_modele(), "installe": installe(), "installation": dict(INSTALLATION)}


# --------------------------------------------------------------------------- vecteurs
def _normaliser(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array.array("f", (x / n for x in v))


def vecteurs(textes, modele=None, delai=60):
    """Les vecteurs (normalisés) d'une liste de textes, par Ollama. Lève ValueError/URLError si Ollama ne répond pas ou si le modèle est absent."""
    corps = json.dumps({"model": modele or nom_modele(), "input": [str(t)[:1500] or " " for t in textes]}).encode("utf-8")
    req = urllib.request.Request(_m.OLLAMA + "/api/embed", data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        donnees = json.loads(r.read().decode("utf-8"))
    liste = donnees.get("embeddings")
    if not isinstance(liste, list) or len(liste) != len(textes) or not all(isinstance(v, list) and v for v in liste):
        raise ValueError(_t("Réponse d'embeddings inattendue."))
    return [_normaliser(v) for v in liste]


def _cle(texte):
    return hashlib.sha1(str(texte)[:1500].encode("utf-8")).hexdigest()[:16]


def _chemin(ident):
    return _m.DONNEES / "embeddings" / (str(ident) + ".json")


def _charger(ident, modele):
    brut = _m.lire_json(_chemin(ident), {})
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


def _enregistrer(ident, modele, cache, gardes):
    """Écrit les vecteurs de ces passages seulement (ceux qui n'existent plus dans la conversation sont oubliés)."""
    v = {h: base64.b64encode(cache[h].tobytes()).decode("ascii") for h in gardes if h in cache}
    _m.ecrire_atomique(_chemin(ident), json.dumps({"modele": modele, "v": v}))


def supprimer(ident):
    try:
        _chemin(ident).unlink(missing_ok=True)
    except OSError:
        pass


def nettoyer_orphelins(ids_existants):
    n = 0
    try:
        for f in (_m.DONNEES / "embeddings").glob("*.json"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return n


def similarites(ident, morceaux, question, budget=8.0):
    """{indice du morceau: similarité avec la question} pour les morceaux déjà vectorisés. Vectorise les morceaux manquants tant que `budget` secondes ne sont pas écoulées (le reste, aux réponses suivantes).
    {} si la recherche par le sens est coupée, si le modèle est absent ou si Ollama ne répond pas."""
    if not actif() or time.time() < ECHEC["jusqua"] or not morceaux:
        return {}
    modele = nom_modele()
    debut = time.time()
    try:
        q = vecteurs([question], modele)[0]
        cache = _charger(ident, modele)
        manquants = [(i, _cle(m["texte"])) for i, m in enumerate(morceaux) if _cle(m["texte"]) not in cache]
        nouveau = False
        for a in range(0, len(manquants), LOT):
            if time.time() - debut > budget:
                break
            lot = manquants[a:a + LOT]
            for (i, h), v in zip(lot, vecteurs([morceaux[i]["texte"] for i, _ in lot], modele)):
                cache[h] = v
            nouveau = True
        if nouveau:
            _enregistrer(ident, modele, cache, {_cle(m["texte"]) for m in morceaux})
        ECHEC["vu"] = False
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        ECHEC["jusqua"] = time.time() + PAUSE_APRES_ECHEC
        if not ECHEC["vu"]:
            ECHEC["vu"] = True
            _m.journaliser("Recherche par le sens indisponible ({!r}) : recherche par mots seulement.".format(erreur))
        return {}
    sims = {}
    for i, m in enumerate(morceaux):
        v = cache.get(_cle(m["texte"]))
        if v is not None and len(v) == len(q):
            sims[i] = sum(a * b for a, b in zip(q, v))
    return sims


# --------------------------------------------------------------------------- installation du modèle
def _installer(modele):
    t = INSTALLATION
    try:
        req = urllib.request.Request(_m.OLLAMA + "/api/pull", data=json.dumps({"model": modele, "stream": True}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            for brut in r:
                try:
                    x = json.loads(brut.decode("utf-8"))
                except ValueError:
                    continue
                if x.get("error"):
                    raise ValueError(str(x["error"])[:300])
                if x.get("total"):
                    t["total"], t["fait"] = int(x["total"]), int(x.get("completed") or 0)
        t["etat"] = "fini"
        INSTALLE_CACHE["t"] = 0.0
        ECHEC["jusqua"] = 0.0
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        t.update(etat="erreur", erreur=_t("Téléchargement impossible : {}").format(erreur))


def demarrer_installation():
    """Télécharge le modèle d'embeddings dans Ollama, en arrière-plan (la progression est dans etat())."""
    from . import horsligne
    horsligne.exiger_en_ligne(_t("télécharger un modèle"))
    with VERROU:
        if INSTALLATION["etat"] == "en cours":
            return dict(INSTALLATION)
        INSTALLATION.update(etat="en cours", fait=0, total=0, erreur="")
    threading.Thread(target=_installer, args=(nom_modele(),), daemon=True, name="embeddings-installation").start()
    return dict(INSTALLATION)
