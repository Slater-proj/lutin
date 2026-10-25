"""Vérification des modèles au lancement : y a-t-il une mise à jour d'un modèle installé, ou un meilleur modèle pour ta machine ?

Règles : jamais bloquant (thread), au plus une fois par 24 h, silencieux hors ligne, ne télécharge JAMAIS de modèle tout seul : il PROPOSE.
Seules données envoyées : des requêtes GET anonymes (le catalogue, et le registre d'Ollama pour comparer des empreintes). Désactivable (réglage `verifier_maj`).
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import catalogue as cat
from . import selection

CATALOGUE_URL_DEFAUT = ""            # adresse du catalogue publié avec le dépôt (à renseigner à la publication, ou via `catalogue_url` dans la configuration)
REGISTRE = "https://registry.ollama.ai/v2"
INTERVALLE_S = 24 * 3600
TAILLE_MAX = 1_000_000
ACCEPT_MANIFESTE = "application/vnd.docker.distribution.manifest.v2+json"


def http_get(url, entetes=None, delai=10, ouvrir=urllib.request.urlopen):
    """(statut, en-têtes en minuscules, corps). Lève OSError si le réseau est absent. HTTPS obligatoire."""
    if not url.startswith("https://"):
        raise OSError("adresse non sécurisée refusée")
    req = urllib.request.Request(url, headers=dict(entetes or {}, **{"User-Agent": "lutin"}))
    try:
        with ouvrir(req, timeout=delai) as r:
            corps = r.read(TAILLE_MAX + 1)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, corps
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""


def separer(modele):
    """« huihui_ai/x:27b » -> (« huihui_ai », « x », « 27b ») ; « qwen3:8b » -> (« library », « qwen3 », « 8b »)."""
    nom, _, tag = modele.partition(":")
    espace, _, court = nom.rpartition("/")
    return espace or "library", court, tag or "latest"


def digest_registre(modele, http=http_get):
    """Empreinte (hexadécimale) du manifeste du modèle dans le registre, ou None (modèle inconnu, hors ligne)."""
    espace, nom, tag = separer(modele)
    try:
        statut, entetes, corps = http("{}/{}/{}/manifests/{}".format(REGISTRE, espace, nom, tag), {"Accept": ACCEPT_MANIFESTE})
    except OSError:
        return None
    if statut != 200:
        return None
    d = entetes.get("docker-content-digest") or "sha256:" + hashlib.sha256(corps).hexdigest()
    return d.split(":", 1)[-1]


def mises_a_jour(installes, http=http_get):
    """Modèles installés dont le contenu a changé dans le registre (même nom, nouvelle version)."""
    sortie = []
    for nom, info in installes.items():
        local = (info.get("digest") or "").split(":", 1)[-1]
        distant = digest_registre(nom, http)
        if local and distant and local != distant:
            sortie.append({"cle": "maj:" + nom, "type": "maj", "modele": nom, "raison": "Une version plus récente de ce modèle est disponible."})
    return sortie


def nouveautes(profil, catalogue, choisis, installes, ignores=()):
    """Meilleurs choix pour CETTE machine, comparés à ce que l'utilisateur a installé pour chaque rôle."""
    meilleurs = selection.choisir(profil, catalogue)
    par_id = cat.par_id(catalogue)
    budget = profil.budget_go()
    sortie = []
    for role, ancien in (choisis or {}).items():
        if role not in meilleurs or ancien not in installes:
            continue
        nouveau = meilleurs[role]
        if nouveau is None or nouveau.id == ancien or nouveau.id in installes:
            continue
        vieux = par_id.get(ancien)
        raison = ""
        if vieux is None:
            raison = "Ton modèle n'est plus dans le catalogue ; celui-ci est recommandé pour ta machine."
        elif vieux.get("remplace_par") == nouveau.id:
            raison = "Le modèle installé est remplacé par celui-ci."
        elif selection.meilleur_contexte(vieux, budget, profil.ram_libre_go or profil.ram_go * 0.5) is None:
            raison = "Le modèle installé ne tient plus dans la mémoire disponible."
        elif nouveau.modele["notes"].get(role, 0) >= vieux["notes"].get(role, 0) + 1:
            raison = "Mieux noté pour ce rôle ({} contre {}).".format(nouveau.modele["notes"][role], vieux["notes"].get(role, 0))
        if not raison:
            continue
        cle = "nouveau:{}:{}".format(role, nouveau.id)
        if cle in ignores:
            continue
        sortie.append({"cle": cle, "type": "nouveau", "role": role, "modele": nouveau.id, "ancien": ancien, "phrase": nouveau.modele["phrase"], "go": nouveau.modele["go"], "raison": raison})
    return sortie


def telecharger_catalogue(url, cache, http=http_get):
    """Catalogue en ligne -> cache/catalogue.json (seulement s'il est valide). Renvoie 'maj' | 'inchange' | 'echec' | 'absent'."""
    if not url:
        return "absent"
    cache = Path(cache)
    fichier, etag_f = cache / "catalogue.json", cache / "catalogue.etag"
    entetes = {}
    if fichier.is_file() and etag_f.is_file():
        entetes["If-None-Match"] = etag_f.read_text(encoding="utf-8").strip()
    try:
        statut, h, corps = http(url, entetes)
    except OSError:
        return "echec"
    if statut == 304:
        return "inchange"
    if statut != 200 or len(corps) > TAILLE_MAX:
        return "echec"
    try:
        cat.valider(json.loads(corps.decode("utf-8")))
    except (ValueError, cat.ErreurCatalogue):
        return "echec"                                       # un catalogue invalide n'est jamais appliqué
    cache.mkdir(parents=True, exist_ok=True)
    fichier.write_bytes(corps)
    if h.get("etag"):
        etag_f.write_text(h["etag"], encoding="utf-8")
    return "maj"


PORTEES = ("maj", "nouveaux", "tout")


def verifier(profil, cfg, dossiers, ollama, http=http_get, maintenant=time.time, force=False, portee="tout"):
    """Une vérification. Écrit cache/propositions.json et renvoie son contenu. Ne lève jamais d'exception.

    portee « maj » : seulement les mises à jour des modèles installés ; « nouveaux » : le catalogue en ligne puis les meilleurs modèles pour cette machine ; « tout » : les deux.
    Une vérification partielle garde les propositions de l'autre sorte. Seule la vérification complète automatique est limitée à une fois par 24 h."""
    if portee not in PORTEES:
        raise ValueError("portée inconnue : {}".format(portee))
    cache = Path(dossiers["cache"])
    cache.mkdir(parents=True, exist_ok=True)
    etat = cache / "derniere-verification.json"
    if not force:
        try:
            if maintenant() - json.loads(etat.read_text(encoding="utf-8")).get("date", 0) < INTERVALLE_S:
                return lire_propositions(dossiers)
        except (OSError, ValueError):
            pass
    ancien = lire_propositions(dossiers)
    resultat = {"date": maintenant(), "propositions": [], "erreurs": [], "catalogue": "absent", "portee": portee}
    try:
        if portee in ("nouveaux", "tout"):
            resultat["catalogue"] = telecharger_catalogue(cfg.get("catalogue_url") or CATALOGUE_URL_DEFAUT, cache, http)
            if resultat["catalogue"] == "echec":
                resultat["erreurs"].append("catalogue en ligne indisponible : copie locale utilisée")
        catalogue = cat.charger(cache / "catalogue.json")
        installes = ollama.installes()
        ignores = set(cfg.get("modeles", {}).get("ignores", []))
        nouvelles, recalcule = [], []
        if portee in ("maj", "tout"):
            nouvelles += mises_a_jour(installes, http)
            recalcule.append("maj")
        if portee in ("nouveaux", "tout"):
            nouvelles += nouveautes(profil, catalogue, cfg.get("modeles", {}).get("choisis", {}), installes, ignores)
            recalcule.append("nouveau")
        gardees = [p for p in ancien.get("propositions", []) if p.get("type") not in recalcule]
        resultat["propositions"] = [p for p in gardees + nouvelles if p["cle"] not in ignores]
    except Exception as e:  # noqa: BLE001 — la vérification ne doit jamais gêner le démarrage
        resultat["erreurs"].append("vérification impossible : {}".format(e))
        resultat["propositions"] = ancien.get("propositions", [])
    try:
        (cache / "propositions.json").write_text(json.dumps(resultat, ensure_ascii=False, indent=1), encoding="utf-8")
        if portee == "tout":
            etat.write_text(json.dumps({"date": resultat["date"]}), encoding="utf-8")
    except OSError:
        pass
    return resultat


def lire_propositions(dossiers):
    try:
        d = json.loads((Path(dossiers["cache"]) / "propositions.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"propositions": [], "erreurs": [], "date": 0}
    except (OSError, ValueError):
        return {"propositions": [], "erreurs": [], "date": 0}
