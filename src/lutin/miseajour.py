"""Vérification des modèles au lancement : y a-t-il une mise à jour d'un modèle installé, ou un meilleur modèle pour ta machine ?

Règles : jamais bloquant (thread), au plus une fois par 24 h, silencieux hors ligne, ne télécharge JAMAIS de modèle tout seul : il PROPOSE. La nouvelle version de Lutin lui-même est annoncée de la même façon (verifier_lutin).
Seules données envoyées : des requêtes GET anonymes (le catalogue, et le registre d'Ollama pour comparer des empreintes). Désactivable (réglage `verifier_maj`).
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import catalogue as cat
from . import horsligne, selection
from .i18n import t as _t

CATALOGUE_URL_DEFAUT = "https://raw.githubusercontent.com/Slater-proj/lutin/main/src/lutin/data/modeles.json"          # le catalogue de la branche principale ; `catalogue_url` dans la configuration le remplace ("" = pas de catalogue en ligne)
DEPOT = "Slater-proj/lutin"
REGISTRE = "https://registry.ollama.ai/v2"
INTERVALLE_S = 24 * 3600
TAILLE_MAX = 1_000_000
ACCEPT_MANIFESTE = "application/vnd.docker.distribution.manifest.v2+json"


def http_get(url, entetes=None, delai=10, ouvrir=urllib.request.urlopen):
    """(statut, en-têtes en minuscules, corps). Lève OSError si le réseau est absent. HTTPS obligatoire."""
    if not url.startswith("https://"):
        raise OSError(_t("adresse non sécurisée refusée"))
    horsligne.garde(url)
    req = urllib.request.Request(url, headers=dict(entetes or {}, **{"User-Agent": "lutin"}))
    try:
        with ouvrir(req, timeout=delai) as r:
            corps = r.read(TAILLE_MAX + 1)
            return r.status, dict({k.lower(): v for k, v in r.headers.items()}, **{"x-lutin-url-finale": r.geturl()}), corps          # l'adresse après redirections : la page des publications y met le numéro de version
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
            sortie.append({"cle": "maj:" + nom, "type": "maj", "modele": nom, "raison": _t("Une version plus récente de ce modèle est disponible.")})
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
            raison = _t("Ton modèle n'est plus dans le catalogue ; celui-ci est recommandé pour ta machine.")
        elif vieux.get("remplace_par") == nouveau.id:
            raison = _t("Le modèle installé est remplacé par celui-ci.")
        elif selection.meilleur_contexte(vieux, budget, profil.ram_libre_go or profil.ram_go * 0.5) is None:
            raison = _t("Le modèle installé ne tient plus dans la mémoire disponible.")
        elif nouveau.modele["notes"].get(role, 0) >= vieux["notes"].get(role, 0) + 1:
            raison = _t("Mieux noté pour ce rôle ({} contre {}).").format(nouveau.modele["notes"][role], vieux["notes"].get(role, 0))
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


def version_par_page(depot=DEPOT, http=http_get):
    """La dernière version d'après la page publique des publications (github.com/…/releases/latest redirige vers …/tag/vX.Y.Z), sans passer par l'API de GitHub. Lève OSError."""
    _, entetes, _ = http("https://github.com/{}/releases/latest".format(depot), {"Accept": "text/html"})
    m = re.search(r"/releases/tag/v?(\d+\.\d+\.\d+[^/?#]*)$", entetes.get("x-lutin-url-finale", ""))
    return m.group(1) if m else None


def derniere_release_detail(depot=DEPOT, http=http_get):
    """(version sans « v », adresse de la roue, cause de l'échec) de la dernière publication. L'API de GitHub d'abord ; si elle ne répond pas (réseau d'entreprise, API bloquée),
    la page publique des publications. Sans réponse : (None, None, texte de l'erreur)."""
    erreur = ""
    try:
        statut, _, corps = http("https://api.github.com/repos/{}/releases/latest".format(depot), {"Accept": "application/vnd.github+json"})
        if statut == 200:
            d = json.loads(corps.decode("utf-8"))
            roue = next((a.get("browser_download_url") for a in d.get("assets", []) if str(a.get("name", "")).endswith(".whl")), None)
            version = str(d.get("tag_name", "")).lstrip("v") or None
            if version:
                return version, roue, ""
            erreur = _t("aucune publication trouvée")
        else:
            erreur = "api.github.com : HTTP {}".format(statut)
    except (OSError, ValueError) as e:
        erreur = "api.github.com : {}".format(e)
    try:
        version = version_par_page(depot, http)
        if version:
            return version, "https://github.com/{0}/releases/download/v{1}/lutin-{1}-py3-none-any.whl".format(depot, version), ""
    except OSError as e:
        erreur = "{} ; github.com : {}".format(erreur, e)
    return None, None, erreur


def derniere_release(depot=DEPOT, http=http_get):
    """(version sans « v », adresse de la roue) de la dernière publication GitHub ; (None, None) si le réseau ou la publication manque."""
    version, roue, _ = derniere_release_detail(depot, http)
    return version, roue


def numeros(version):
    """(1, 2, 3) pour « 1.2.3rc4+x » ; () si illisible."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(version or ""))
    return tuple(int(x) for x in m.groups()) if m else ()


def plus_recente(distante, locale):
    """Vrai si la version distante est strictement plus récente (jamais de retour en arrière, même si la version locale est une candidate ou illisible)."""
    return bool(numeros(distante)) and numeros(distante) > (numeros(locale) or (0, 0, 0))


def commande_mise_a_jour():
    """La commande à donner pour se mettre à jour : dans un conteneur, c'est l'image qu'on remplace."""
    return "docker compose pull && docker compose up -d" if os.path.exists("/.dockerenv") or os.environ.get("LUTIN_DOCKER") else "lutin update"


def fichier_version(dossiers):
    return Path(dossiers["cache"]) / "lutin-version.json"


def lire_fichier_version(chemin):
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def verifier_lutin(dossiers, depot=DEPOT, http=http_get, maintenant=time.time, force=False):
    """Y a-t-il une version de Lutin plus récente ? Au plus une fois par 24 h, jamais bloquant (une seule requête GET anonyme vers l'API de GitHub), silencieux hors ligne.
    Le résultat est gardé dans cache/lutin-version.json ; la page l'affiche, rien n'est installé sans toi."""
    chemin = fichier_version(dossiers)
    d = lire_fichier_version(chemin)
    if not force and maintenant() - float(d.get("date") or 0) < INTERVALLE_S:
        return d
    version, _, erreur = derniere_release_detail(depot, http)
    if version:
        d.update(date=maintenant(), version=version, depot=depot)
        d.pop("erreur", None)
    else:
        d["erreur"] = erreur            # la page la montre (« Impossible de joindre GitHub : … ») ; la date ne bouge pas : on réessaiera
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass
    return d


def nouvelle_version(chemin, locale):
    """{version, actuelle, page, commande} si le fichier du cache annonce une version plus récente que la locale et que tu ne l'as pas ignorée ; None sinon. Jamais de réseau."""
    d = lire_fichier_version(chemin)
    v = str(d.get("version") or "")
    if not plus_recente(v, locale) or v == d.get("ignoree"):
        return None
    return {"version": v, "actuelle": locale, "page": "https://github.com/{}/releases/tag/v{}".format(d.get("depot") or DEPOT, v), "commande": commande_mise_a_jour()}


def ignorer_version(chemin, version):
    """« Ignorer cette version » : plus de rappel pour elle (la suivante sera annoncée)."""
    d = lire_fichier_version(chemin)
    d["ignoree"] = str(version)
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    Path(chemin).write_text(json.dumps(d, indent=1), encoding="utf-8")


PORTEES = ("maj", "nouveaux", "tout")


def verifier(profil, cfg, dossiers, ollama, http=http_get, maintenant=time.time, force=False, portee="tout"):
    """Une vérification. Écrit cache/propositions.json et renvoie son contenu. Ne lève jamais d'exception.

    portee « maj » : seulement les mises à jour des modèles installés ; « nouveaux » : le catalogue en ligne puis les meilleurs modèles pour cette machine ; « tout » : les deux.
    Une vérification partielle garde les propositions de l'autre sorte. Seule la vérification complète automatique est limitée à une fois par 24 h."""
    if portee not in PORTEES:
        raise ValueError(_t("portée inconnue : {}").format(portee))
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
    hors_ligne = horsligne.actif(Path(dossiers.get("config", "")) / "config.json" if dossiers.get("config") else None)
    if hors_ligne:
        resultat["erreurs"].append(_t("mode hors ligne strict : seule la liste livrée avec Lutin est comparée, les mises à jour de modèles ne sont pas cherchées"))
        portee_reseau = False
    else:
        portee_reseau = True
    try:
        if portee in ("nouveaux", "tout") and portee_reseau:
            url = cfg.get("catalogue_url")
            resultat["catalogue"] = telecharger_catalogue(CATALOGUE_URL_DEFAUT if url is None else url, cache, http)
            if resultat["catalogue"] == "echec":
                resultat["erreurs"].append(_t("catalogue en ligne indisponible : copie locale utilisée"))
        catalogue = cat.charger(cache / "catalogue.json")
        installes = ollama.installes()
        ignores = set(cfg.get("modeles", {}).get("ignores", []))
        nouvelles, recalcule = [], []
        if portee in ("maj", "tout") and portee_reseau:
            nouvelles += mises_a_jour(installes, http)
            recalcule.append("maj")
        if portee in ("nouveaux", "tout"):
            nouvelles += nouveautes(profil, catalogue, cfg.get("modeles", {}).get("choisis", {}), installes, ignores)
            recalcule.append("nouveau")
        gardees = [p for p in ancien.get("propositions", []) if p.get("type") not in recalcule]
        resultat["propositions"] = [p for p in gardees + nouvelles if p["cle"] not in ignores]
    except Exception as e:  # noqa: BLE001 — la vérification ne doit jamais gêner le démarrage
        resultat["erreurs"].append(_t("vérification impossible : {}").format(e))
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
