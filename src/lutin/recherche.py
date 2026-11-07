"""Recherche web complète : fournisseurs au choix (SearXNG chez soi, Brave avec sa clé, puis DuckDuckGo et Bing sans rien configurer), options de recherche (période, site, actualités, langue),
résultats nettoyés (adresses sans suivi, doublons retirés, variété des sites) et configuration rangée à part, avec la clé jamais renvoyée à la page.

Les fournisseurs « maison » (SearXNG) sont à une adresse que l'utilisateur choisit, souvent sur son réseau : c'est la seule exception à l'interdiction des adresses locales de l'accès web, et elle ne vaut que pour CETTE
adresse et seulement pour la recherche (pas pour la lecture de pages). Elle ne se règle que depuis la machine elle-même."""
import json
import os
import re
import threading
import urllib.parse

from . import donnees as _donnees
from .i18n import t as _t

BRAVE_URL = os.environ.get("LUTIN_BRAVE_URL", "https://api.search.brave.com/res/v1/")
PERIODES = {"jour": ("day", "pd", "d"), "semaine": ("week", "pw", "w"), "mois": ("month", "pm", "m"), "an": ("year", "py", "y")}          # SearXNG, Brave, DuckDuckGo
RE_CLE_BRAVE = re.compile(r"^[A-Za-z0-9_\-]{10,200}$")
RE_DOMAINE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
PARAMETRES_SUIVI = ("utm_", "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid", "_hsenc", "_hsmi", "ref_src", "ref_url")
PAR_SITE_MAX = 2          # au plus deux résultats du même site : la variété vaut mieux que dix pages d'un seul endroit (sauf si on a demandé un site)
VERROU = threading.Lock()
ACTUELLES = threading.local()          # les options de la recherche en cours (les fournisseurs n'ont que « requête » comme paramètre)


# --------------------------------------------------------------------------- configuration (recherche.json, à part de reglages.json : elle porte un secret)
def _chemin():
    from . import moteur as _m
    return _m.DONNEES / "recherche.json"


def config():
    c = _donnees.lire_json(_chemin(), {})
    return {"searxng": str(c.get("searxng") or ""), "brave_cle": str(c.get("brave_cle") or "")}


def normaliser_adresse(adresse):
    """http(s)://hôte[:port][/chemin] sans identifiants ni requête ; « » pour retirer. ValueError sinon."""
    texte = str(adresse or "").strip()
    if not texte:
        return ""
    if re.match(r"^[a-z][a-z0-9+.\-]*://", texte, re.I) and not re.match(r"^https?://", texte, re.I):
        raise ValueError(_t("Adresse de SearXNG invalide (exemple : http://127.0.0.1:8080)."))          # ftp://, file://… : jamais
    if not re.match(r"^https?://", texte, re.I):
        texte = "http://" + texte
    p = urllib.parse.urlparse(texte)
    if re.search(r"\s", texte) or p.scheme not in ("http", "https") or not p.hostname or not re.match(r"^[A-Za-z0-9.\-_:\[\]]+$", p.hostname) or p.username or p.password or p.query or p.fragment:
        raise ValueError(_t("Adresse de SearXNG invalide (exemple : http://127.0.0.1:8080)."))
    try:
        port = p.port
    except ValueError:
        raise ValueError(_t("Adresse de SearXNG invalide (exemple : http://127.0.0.1:8080).")) from None
    hote = "[{}]".format(p.hostname) if ":" in p.hostname else p.hostname
    return "{}://{}{}{}".format(p.scheme, hote, ":%d" % port if port else "", p.path.rstrip("/"))


def enregistrer(searxng=None, brave_cle=None):
    """Change l'adresse de SearXNG et/ou la clé de Brave (None = ne pas toucher ; « » = retirer). Renvoie la vue sans secret."""
    with VERROU:
        c = config()
        if searxng is not None:
            c["searxng"] = normaliser_adresse(searxng)
        if brave_cle is not None:
            cle = str(brave_cle).strip()
            if cle and not RE_CLE_BRAVE.match(cle):
                raise ValueError(_t("Clé Brave invalide (des lettres, des chiffres, - et _ seulement)."))
            c["brave_cle"] = cle
        chemin = _chemin()
        _donnees.ecrire_atomique(chemin, json.dumps(c, ensure_ascii=False, indent=1))
        try:
            os.chmod(chemin, 0o600)          # la clé n'est lisible que par son propriétaire (là où le système le permet)
        except OSError:
            pass
    return vue()


def vue():
    c = config()
    return {"searxng": c["searxng"], "brave": bool(c["brave_cle"]), "brave_fin": c["brave_cle"][-4:] if c["brave_cle"] else ""}


def hote_autorise():
    """L'hôte de SearXNG, seul hôte local que la recherche a le droit de joindre."""
    adresse = config()["searxng"]
    return (urllib.parse.urlparse(adresse).hostname or "").lower() if adresse else ""


# --------------------------------------------------------------------------- options de la recherche en cours
def options():
    return dict(getattr(ACTUELLES, "v", None) or {})


SYNONYMES_PERIODE = {"année": "an", "annee": "an", "ans": "an", "year": "an", "années": "an", "annees": "an", "annuel": "an", "day": "jour", "jours": "jour", "journée": "jour", "aujourd'hui": "jour", "today": "jour", "24h": "jour",
                     "week": "semaine", "semaines": "semaine", "hebdomadaire": "semaine", "month": "mois", "mensuel": "mois"}


def definir_options(periode=None, site=None, actualites=False, langue=None):
    """Valide et pose les options de la recherche en cours (ce fil seulement). Renvoie le dictionnaire posé."""
    periode = str(periode or "").strip().lower() or None
    periode = SYNONYMES_PERIODE.get(periode, periode)          # « année », « year »… : le modèle écrit ce qui lui vient, on le comprend
    if periode and periode not in PERIODES:
        raise ValueError(_t("Période inconnue : {} (jour, semaine, mois ou an).").format(periode[:20]))
    site = re.sub(r"^https?://", "", str(site or "").strip().lower()).split("/")[0].removeprefix("www.") or None
    if site and not RE_DOMAINE.match(site):
        raise ValueError(_t("Site invalide : {} (un nom de domaine, par exemple docs.python.org).").format(site[:60]))
    langue = (str(langue or "").strip().lower() or "fr")[:2]
    ACTUELLES.v = {"periode": periode, "site": site, "actualites": bool(actualites), "langue": langue if langue in ("fr", "en") else "fr"}
    return options()


def requete_avec_site(requete, o=None):
    o = o or options()
    return "site:{} {}".format(o["site"], requete) if o.get("site") else requete


# --------------------------------------------------------------------------- nettoyage des résultats
def adresse_propre(url):
    """L'adresse sans suivi publicitaire (utm_…, fbclid…) ni ancre ; '' si ce n'est pas une adresse http(s)."""
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    requete = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith(PARAMETRES_SUIVI)]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or "/", urllib.parse.urlencode(requete), ""))


def cle_de_doublon(url):
    p = urllib.parse.urlsplit(url)
    return ((p.hostname or "").lower().removeprefix("www."), p.path.rstrip("/").lower(), p.query)


def nettoyer(resultats, nombre, par_site=PAR_SITE_MAX):
    """Adresses sans suivi, doublons retirés, au plus `par_site` résultats par site, titres et extraits propres ; l'ordre du fournisseur est gardé."""
    vus, par_hote, sortie = set(), {}, []
    for x in resultats:
        url = adresse_propre(x.get("url"))
        if not url:
            continue
        cle = cle_de_doublon(url)
        hote = cle[0]
        if cle in vus or (par_site and par_hote.get(hote, 0) >= par_site):
            continue
        vus.add(cle)
        par_hote[hote] = par_hote.get(hote, 0) + 1
        sortie.append(dict(x, url=url, titre=" ".join(str(x.get("titre") or "").split())[:200] or url, extrait=" ".join(str(x.get("extrait") or "").split())[:300],
                           date=" ".join(str(x.get("date") or "").split())[:40]))
        if len(sortie) >= nombre:
            break
    return sortie


def domaine(url):
    return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")


# --------------------------------------------------------------------------- fournisseurs
def resultats_searxng(requete):
    """SearXNG (https://docs.searxng.org) : l'API JSON d'une instance à soi, qui interroge elle-même plusieurs moteurs. Il faut y avoir activé le format JSON (voir docs/WEB_SEARCH.md)."""
    from . import web
    from . import moteur as _m
    base = config()["searxng"]
    if not base:
        raise _m.ErreurOutil(_t("SearXNG n'est pas configuré."))
    o = options()
    q = {"q": requete_avec_site(requete, o), "format": "json", "language": o.get("langue", "fr"), "safesearch": "1", "pageno": "1"}
    if o.get("periode"):
        q["time_range"] = PERIODES[o["periode"]][0]
    if o.get("actualites"):
        q["categories"] = "news"
    _, _, texte = web.web_telecharger(base + "/search?" + urllib.parse.urlencode(q), None, hote_autorise=hote_autorise())
    try:
        donnees = json.loads(texte)
    except ValueError:
        raise _m.ErreurOutil(_t("SearXNG n'a pas répondu en JSON : le format « json » est-il activé dans son settings.yml ?")) from None
    sortie = []
    for x in donnees.get("results") or []:
        if isinstance(x, dict) and x.get("url"):
            sortie.append({"titre": x.get("title") or "", "url": x.get("url"), "extrait": x.get("content") or "", "date": str(x.get("publishedDate") or "")[:10]})
    return sortie


def resultats_brave(requete):
    """Brave Search (https://brave.com/search/api/) : une API avec une clé personnelle (offre gratuite limitée). Index indépendant, pas de HTML à décortiquer."""
    from . import web
    from . import moteur as _m
    cle = config()["brave_cle"]
    if not cle:
        raise _m.ErreurOutil(_t("La clé Brave n'est pas configurée."))
    o = options()
    q = {"q": requete_avec_site(requete, o), "count": "20", "search_lang": o.get("langue", "fr"), "safesearch": "moderate"}
    if o.get("periode"):
        q["freshness"] = PERIODES[o["periode"]][1]
    point = "news/search" if o.get("actualites") else "web/search"
    adresse = BRAVE_URL.rstrip("/") + "/" + point + "?" + urllib.parse.urlencode(q)
    autorise = (urllib.parse.urlparse(adresse).hostname or "").lower() if os.environ.get("LUTIN_BRAVE_URL") else None          # une adresse imposée (tests) peut être locale ; la vraie est publique
    _, _, texte = web.web_telecharger(adresse, None, hote_autorise=autorise, entetes={"X-Subscription-Token": cle, "Accept": "application/json"})
    try:
        donnees = json.loads(texte)
    except ValueError:
        raise _m.ErreurOutil(_t("Brave n'a pas répondu en JSON.")) from None
    brut = donnees.get("results") if o.get("actualites") else (donnees.get("web") or {}).get("results")
    sortie = []
    for x in brut or []:
        if isinstance(x, dict) and x.get("url"):
            sortie.append({"titre": x.get("title") or "", "url": x.get("url"), "extrait": re.sub(r"<[^>]+>", "", x.get("description") or ""), "date": str(x.get("age") or x.get("page_age") or "")[:10]})
    return sortie


def fournisseurs_configures():
    """[(nom, fonction)] des fournisseurs que l'utilisateur a réglés, dans l'ordre où on les essaie (avant DuckDuckGo et Bing)."""
    c = config()
    sortie = []
    if c["searxng"]:
        sortie.append(("searxng", resultats_searxng))
    if c["brave_cle"]:
        sortie.append(("brave", resultats_brave))
    return sortie
