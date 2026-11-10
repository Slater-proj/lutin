"""Les modèles d'ExLlamaV3 : où les trouver, comment les juger pour cette machine.

ExLlamaV3 lit des modèles au format EXL3, publiés sur Hugging Face. Son auteur (turboderp) en publie pour la plupart des modèles du moment, un dépôt par modèle, et UNE BRANCHE PAR QUANTIFICATION
(« 4.0bpw » = 4 bits par poids : petit et rapide ; « 6.0bpw » : plus fidèle, plus gros). D'autres personnes en publient aussi. Ce module :
  - cherche ces dépôts (récents ou populaires, auteur officiel ou toute la communauté) avec l'API publique de Hugging Face, sans compte ;
  - liste les quantifications d'un dépôt avec leur taille exacte (somme des fichiers de la branche) ;
  - estime la taille d'après le nom du modèle (« 27B » à 4 bits ≈ 16 Go) pour juger un dépôt sans demander toutes ses branches ;
  - dit si un modèle téléchargé a une version plus récente (l'empreinte de sa branche a changé).
Tout passe par `http(url, entetes) -> (statut, entetes, corps)` : testable sans réseau. Rien n'est téléchargé ici."""
import concurrent.futures
import json
import re
import time
import urllib.parse

from . import miseajour
from .i18n import t as _t

API = "https://huggingface.co/api/models"
AUTEUR_OFFICIEL = "turboderp"
PAR_PAGE = 24
RE_DEPOT = re.compile(r"^[A-Za-z0-9][\w.-]{0,60}/[A-Za-z0-9][\w.-]{0,100}$")
RE_BPW = re.compile(r"^(\d+(?:\.\d+)?)bpw")
RE_PARAMS = re.compile(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)\s?[bB](?![a-zA-Z])")
CACHE = {}          # url -> (instant, valeur) : ni la liste ni les branches ne bougent en quelques minutes
DUREE_CACHE = 300


def _json(url, http):
    garde = CACHE.get(url)
    if garde and time.time() - garde[0] < DUREE_CACHE:
        return garde[1]
    try:
        statut, _, corps = http(url, {"Accept": "application/json"})
    except OSError as e:
        raise ValueError(_t("Hugging Face ne répond pas ({}). Vérifie ta connexion.").format(str(e)[:80]))
    if statut == 404:
        raise ValueError(_t("Ce dépôt n'existe pas sur Hugging Face."))
    if statut != 200:
        raise ValueError(_t("Hugging Face a répondu une erreur (HTTP {}). Réessaie dans quelques minutes.").format(statut))
    try:
        valeur = json.loads(corps.decode("utf-8"))
    except ValueError:
        raise ValueError(_t("Réponse illisible de Hugging Face."))
    CACHE[url] = (time.time(), valeur)
    return valeur


def estimer_go(nom, bpw):
    """La taille probable (Go) d'un modèle d'après son nom (« Qwen3-8B-exl3 » à 4 bits ≈ 5,2 Go), ou None quand le nom ne donne pas le nombre de paramètres.
    Un modèle « à experts » (Qwen3-30B-A3B) pèse selon ses 30 milliards, pas ses 3 actifs : on prend le plus grand nombre du nom."""
    nombres = [float(x) for x in RE_PARAMS.findall(str(nom))]
    if not nombres or not bpw:
        return None
    return round(max(nombres) * float(bpw) / 8 * 1.1 + 0.8, 1)          # + la couche d'entrée et de sortie, gardées plus précises (mesuré : 8B à 4 bits = 5,2 Go)


def _capacites(m):
    tags = [str(t) for t in (m.get("tags") or [])]
    pipeline = str(m.get("pipeline_tag") or "")
    sortie = []
    if "image" in pipeline or any(t in ("vision", "multimodal") for t in tags):
        sortie.append("vision")
    return sortie


def chercher(q="", tri="recent", communaute=False, page=1, http=miseajour.http_get, auteur=AUTEUR_OFFICIEL, etiquette="exl3", bpw=4.0):
    """Les dépôts EXL3 qui correspondent : [{id, nom, telechargements, aime, maj, capacites, licence, base, estimation_go}] et `suite` (il y en a d'autres).
    tri : « recent » ou « populaire » ; communaute : tous les auteurs au lieu du seul auteur officiel. Une page de PAR_PAGE ; `page` agrandit la liste (l'API n'a pas de page suivante simple)."""
    page = max(1, min(int(page or 1), 10))
    limite = PAR_PAGE * page + 1          # un de plus que demandé : sert à savoir s'il y a une suite
    q = str(q or "").strip()[:60]
    parametres = [("sort", "downloads" if tri == "populaire" else "lastModified"), ("direction", "-1"), ("limit", str(limite))]
    if communaute:
        parametres += [("filter", etiquette)] + ([("search", q)] if q else [])
    else:
        parametres += [("author", auteur), ("search", (q + " " + etiquette).strip())]
    parametres += [("expand[]", x) for x in ("downloads", "likes", "lastModified", "tags", "pipeline_tag")]
    donnees = _json(API + "?" + urllib.parse.urlencode(parametres), http)
    if not isinstance(donnees, list):
        raise ValueError(_t("Réponse inattendue de Hugging Face."))
    sortie = []
    for m in donnees:
        ident = str(m.get("id", ""))
        if not RE_DEPOT.match(ident) or etiquette not in (ident.lower() + " " + " ".join(str(t).lower() for t in (m.get("tags") or []))):
            continue
        tags = [str(t) for t in (m.get("tags") or [])]
        base = next((t.split(":", 2)[2] for t in tags if t.startswith("base_model:quantized:")), "") or next((t.split(":", 1)[1] for t in tags if t.startswith("base_model:") and t.count(":") == 1), "")
        sortie.append({"id": ident, "nom": ident.split("/")[-1], "auteur": ident.split("/")[0], "telechargements": int(m.get("downloads") or 0), "aime": int(m.get("likes") or 0), "maj": str(m.get("lastModified") or "")[:10],
                       "capacites": _capacites(m), "licence": next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), ""), "base": base,
                       "estimation_go": estimer_go(ident.split("/")[-1], bpw)})
    return {"modeles": sortie[:PAR_PAGE * page], "suite": len(sortie) > PAR_PAGE * page}


def branches(depot, http=miseajour.http_get):
    """{nom de branche: empreinte} d'un dépôt."""
    if not RE_DEPOT.match(str(depot)):
        raise ValueError(_t("Nom de dépôt invalide : écris « propriétaire/modèle » (Hugging Face)."))
    d = _json(API + "/" + urllib.parse.quote(depot, safe="/") + "/refs", http)
    return {str(b.get("name")): str(b.get("targetCommit", "")) for b in (d.get("branches") or []) if b.get("name")}


def commit(depot, revision, http=miseajour.http_get):
    """L'empreinte actuelle d'une révision (branche) d'un dépôt, ou '' si elle n'existe pas."""
    return branches(depot, http).get(revision or "main", "")


def taille_revision(depot, revision, http=miseajour.http_get):
    """Octets de tous les fichiers d'une révision (somme des fichiers de la branche) : le total d'un téléchargement. ValueError si illisible."""
    if not RE_DEPOT.match(str(depot)):
        raise ValueError(_t("Nom de dépôt invalide : écris « propriétaire/modèle » (Hugging Face)."))
    d = _json(API + "/" + urllib.parse.quote(depot, safe="/") + "/tree/" + urllib.parse.quote(str(revision or "main"), safe=""), http)
    return sum(int(f.get("size") or 0) for f in d if isinstance(f, dict) and f.get("type") == "file")


def quantifications(depot, http=miseajour.http_get):
    """Les quantifications d'un dépôt : [{revision, bpw, go, commit}] triées du plus léger au plus lourd. `go` = somme exacte des fichiers de la branche (None si illisible)."""
    liste = []
    for nom, empreinte in branches(depot, http).items():
        m = RE_BPW.match(nom)
        if m:
            liste.append({"revision": nom, "bpw": float(m.group(1)), "commit": empreinte})

    def taille(q):
        try:
            d = _json(API + "/" + urllib.parse.quote(depot, safe="/") + "/tree/" + urllib.parse.quote(q["revision"], safe=""), http)
            return round(sum(int(f.get("size") or 0) for f in d if isinstance(f, dict) and f.get("type") == "file") / 1e9, 1) or None
        except (ValueError, TypeError):
            return None
    if liste:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for q, go in zip(liste, pool.map(taille, liste)):
                q["go"] = go
    return sorted(liste, key=lambda q: q["bpw"])


def versions_plus_recentes(modeles, http=miseajour.http_get):
    """Parmi les modèles téléchargés par Lutin ({nom, depot, revision, commit}), ceux dont la branche a changé depuis : [{nom, depot, revision}]. Un modèle sans origine connue ne peut pas être vérifié."""
    plus_recentes, erreurs = [], []
    for m in modeles:
        if not m.get("depot") or not m.get("commit"):
            continue
        try:
            actuel = commit(m["depot"], m.get("revision") or "main", http)
        except ValueError as e:
            erreurs.append(str(e))
            continue
        if actuel and actuel != m["commit"]:
            plus_recentes.append({"nom": m["nom"], "depot": m["depot"], "revision": m.get("revision", "")})
    return {"plus_recentes": plus_recentes, "erreurs": sorted(set(erreurs))}
