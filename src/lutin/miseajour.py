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


def obsoletes(catalogue, installes, ignores=()):
    """Modèles installés que le catalogue dit remplacés (`remplace_par`) par un autre qui est installé lui aussi : on propose de libérer la place. Rien n'est supprimé sans clic."""
    par_id = cat.par_id(catalogue)
    sortie = []
    for nom in installes:
        vieux = par_id.get(nom)
        nouveau = (vieux or {}).get("remplace_par")
        cle = "obsolete:" + nom
        if not nouveau or nouveau not in installes or cle in ignores:
            continue
        sortie.append({"cle": cle, "type": "obsolete", "modele": nom, "remplace_par": nouveau, "go": vieux.get("go", 0),
                       "raison": _t("{} est remplacé par {}, déjà installé : tu peux supprimer l'ancien pour libérer de la place.").format(nom, nouveau)})
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


class ErreurVerification(ValueError):
    """La roue téléchargée n'est pas celle que la publication annonce : on ne l'installe pas."""


TAILLE_ROUE_MAX = 60_000_000
PAUSES = (2, 5, 12)          # secondes entre les essais quand GitHub est momentanément indisponible (504, 502, 503, 429, coupure) : 4 essais en tout


def _panne_passagere(statut):
    return statut >= 500 or statut == 429


def _avec_reprises(action, pauses=PAUSES, dormir=None):
    """`action()` -> (statut, en-têtes, corps) ; recommence quand GitHub répond par une panne passagère (5xx, 429) ou que le réseau coupe un instant. Le dernier résultat est rendu tel quel : jamais de contournement,
    seulement de la patience (la vérification de la somme reste obligatoire)."""
    for pause in (*pauses, None):
        try:
            statut, entetes, corps = action()
        except OSError:
            if pause is None:
                raise
        else:
            if not _panne_passagere(statut) or pause is None:
                return statut, entetes, corps
        (dormir or time.sleep)(pause)
RE_NOM_ROUE = re.compile(r"^lutin-[0-9A-Za-z.+_-]+-py3-none-any\.whl$")


def somme_attendue(texte, nom_fichier):
    """La somme SHA-256 de `nom_fichier` dans un SHA256SUMS.txt (« <64 chiffres hexa>  nom », comme `sha256sum`), ou None si le fichier n'y figure pas."""
    for ligne in str(texte).splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", ligne)
        if m and m.group(2) == nom_fichier:
            return m.group(1).lower()
    return None


def telecharger_roue_verifiee(url_roue, dossier, http=http_get, ouvrir=urllib.request.urlopen, nom_valide=RE_NOM_ROUE, exiger_sommes=False, prefixe="https://", pauses=PAUSES):
    """Télécharge la roue dans `dossier`, calcule sa somme SHA-256 pendant la lecture et la compare au SHA256SUMS.txt publié à côté. Renvoie (chemin, verifie).
    `verifie` est faux seulement quand la publication n'a pas de SHA256SUMS.txt (anciennes versions) : l'appelant le dit. Une somme qui ne correspond pas, un fichier absent de la liste ou une roue trop grosse lèvent ErreurVerification ;
    le réseau absent lève OSError. L'installation se fait ensuite depuis CE fichier : aucun octet non vérifié n'est installé."""
    nom = str(url_roue).rsplit("/", 1)[-1]
    if not str(url_roue).startswith(prefixe) or not nom_valide.match(nom):
        raise ErreurVerification(_t("Adresse de roue inattendue : {}").format(str(url_roue)[:120]))
    adresse_sommes = str(url_roue).rsplit("/", 1)[0] + "/SHA256SUMS.txt"
    statut, _, corps = _avec_reprises(lambda: http(adresse_sommes, delai=20), pauses)          # GitHub a parfois un 504 d'une minute : on patiente avant de renoncer
    attendue = None
    if statut == 200:
        attendue = somme_attendue(corps.decode("utf-8", "replace"), nom)
        if attendue is None:
            raise ErreurVerification(_t("{} ne figure pas dans SHA256SUMS.txt : mise à jour refusée.").format(nom))
    elif statut != 404 or exiger_sommes:          # `exiger_sommes` : pour un programme d'un tiers, pas de somme publiée = pas de téléchargement
        if _panne_passagere(statut):
            raise ErreurVerification(_t("GitHub est momentanément indisponible (HTTP {}) : la somme de contrôle de la mise à jour n'a pas pu être lue après plusieurs essais. Rien n'a été installé ; réessaie dans quelques minutes.").format(statut))
        raise ErreurVerification(_t("SHA256SUMS.txt illisible (HTTP {}) : mise à jour refusée.").format(statut))
    horsligne.garde(url_roue)
    requete = urllib.request.Request(url_roue, headers={"User-Agent": "lutin"})
    chemin = Path(dossier) / nom

    def lire():
        h, total = hashlib.sha256(), 0
        with ouvrir(requete, timeout=60) as r, open(chemin, "wb") as sortie:
            while True:
                bloc = r.read(1 << 16)
                if not bloc:
                    break
                total += len(bloc)
                if total > TAILLE_ROUE_MAX:
                    raise ErreurVerification(_t("Roue anormalement grosse : mise à jour refusée."))
                h.update(bloc)
                sortie.write(bloc)
        return h

    for pause in (*pauses, None):          # une coupure en cours de téléchargement : on recommence au début (le fichier est vérifié en entier)
        try:
            h = lire()
            break
        except OSError:
            if pause is None:
                raise
            time.sleep(pause)
    if attendue and h.hexdigest() != attendue:
        chemin.unlink(missing_ok=True)
        raise ErreurVerification(_t("La somme SHA-256 de {} ne correspond pas à celle de la publication : mise à jour refusée.").format(nom))
    return chemin, bool(attendue)


def roue_de_version(version, depot=DEPOT):
    """L'adresse de la roue d'une version publiée (retour arrière), ou ValueError si le numéro n'a pas la forme X.Y.Z (rien d'autre n'est jamais passé à pip)."""
    v = str(version or "").strip().lstrip("v")
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", v):
        raise ValueError(_t("Numéro de version invalide (exemple : 0.22.0)."))
    return v, "https://github.com/{0}/releases/download/v{1}/lutin-{1}-py3-none-any.whl".format(depot, v)


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
            nouvelles += obsoletes(catalogue, installes, ignores)
            recalcule += ["nouveau", "obsolete"]
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
