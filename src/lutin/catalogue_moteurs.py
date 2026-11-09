"""Le catalogue des moteurs : de la donnée signée, jamais du code.

Un fichier JSON décrit les moteurs que Lutin connaît (serveurs compatibles OpenAI : LM Studio, vLLM, SGLang…) : leur adresse habituelle, leurs forces et faiblesses, un lien vers leur site. Ajouter un
moteur qui parle déjà l'interface OpenAI, c'est ajouter UNE entrée à ce fichier, sans nouvelle version de Lutin. Aucun code distant n'est jamais exécuté : ce sont des textes et des adresses.

Confiance : le fichier est signé en Ed25519 (voir ed25519.py). Lutin embarque DEUX clés publiques (une seule sert ; la seconde permet de changer de clé sans casser les installations existantes).
Un catalogue dont la signature ne correspond à aucune clé connue, ou qui a été modifié d'une virgule, est refusé.

Ordre de lecture : copie récupérée en ligne (cache) si elle est valide, signée et plus récente ; sinon copie livrée avec Lutin, qui suffit hors ligne.
Format du fichier : {"catalogue": {...}, "cle": "<identifiant de clé>", "signature": "<base 64>"} ; la signature porte sur `canonique(catalogue)`."""
import base64
import json
import re
import threading
import time
from pathlib import Path

from . import ed25519, moteurs
from .i18n import langue

# Les clés publiques (hexadécimal). Les clés privées ne sont JAMAIS dans le dépôt (voir docs/ENGINE_CATALOG.md pour la rotation).
CLES_PUBLIQUES = {
    "2026a": "495c4a818f70bc686b909854d2efc93cdb61c081ff7061423a7a309e3ef3e915",
    "2026b": "f40eb2f7e4241babeb07a7b0db7163cf2f9f7599fc40f84b7185c5559e418434",
}
FICHIER_LIVRE = Path(__file__).resolve().parent / "data" / "moteurs.json"
URL_DEFAUT = "https://raw.githubusercontent.com/Slater-proj/lutin/main/src/lutin/data/moteurs.json"          # `catalogue_moteurs_url` dans la configuration le remplace ("" = pas de lecture en ligne)
TAILLE_MAX = 256 * 1024
GENRES = ("openai", "ollama")          # « ollama » : seulement pour le moteur Ollama géré par Lutin
SYSTEMES = ("windows", "linux", "macos")
MATERIELS = ("nvidia", "amd", "intel", "apple")          # « materiel » : au moins une carte de ce fabricant est nécessaire (absent : aucune exigence)
TYPES = ("externe", "gere")          # « gere » : un moteur que Lutin installe et pilote lui-même (sa fiche vient du catalogue, son code reste dans Lutin)
GERES = ("ollama", "llamacpp")
RE_DEPOT = re.compile(r"^[A-Za-z0-9][\w.-]{0,38}/[A-Za-z0-9][\w.-]{0,99}$")
OBLIGATOIRES = ("id", "nom", "genre", "description")


class ErreurCatalogue(ValueError):
    pass


def canonique(catalogue):
    """Les octets qui sont signés : le catalogue en JSON trié, compact, en ASCII (donc identique partout)."""
    return json.dumps(catalogue, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def signer(catalogue, graine, cle):
    """L'enveloppe signée d'un catalogue (pour l'outil de signature et les tests)."""
    return {"catalogue": catalogue, "cle": cle, "signature": base64.b64encode(ed25519.signer(graine, canonique(catalogue))).decode("ascii")}


def _texte(valeur, contexte, maxi=400):
    """Un texte, ou un dictionnaire {fr, en} de textes courts."""
    textes = valeur.values() if isinstance(valeur, dict) else [valeur]
    if isinstance(valeur, dict) and not (valeur and set(valeur) <= {"fr", "en"} and "fr" in valeur):
        raise ErreurCatalogue("{} : texte à fournir en français (« fr »), éventuellement en anglais (« en »)".format(contexte))
    for t in textes:
        if not isinstance(t, str) or not t.strip() or len(t) > maxi:
            raise ErreurCatalogue("{} : texte vide ou trop long".format(contexte))


def _adresse_valide(adresse):
    return isinstance(adresse, str) and (adresse == "" or (adresse.startswith(("http://", "https://")) and " " not in adresse))


def valider(catalogue):
    """Lève ErreurCatalogue au premier défaut ; renvoie le catalogue sinon. Schéma strict : un champ inconnu est refusé."""
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("moteurs"), list) or not catalogue["moteurs"]:
        raise ErreurCatalogue("catalogue vide ou mal formé")
    if not isinstance(catalogue.get("version"), int) or isinstance(catalogue.get("version"), bool):
        raise ErreurCatalogue("numéro de version manquant")
    inconnus = set(catalogue) - {"version", "date", "moteurs"}
    if inconnus:
        raise ErreurCatalogue("champ inconnu : {}".format(sorted(inconnus)[0]))
    autorises = set(OBLIGATOIRES) | {"adresse_defaut", "cle_requise", "points_forts", "points_faibles", "plateformes", "site", "remarque", "type", "depot", "version_testee", "etiquette", "experimental", "materiel", "docker"}
    vus = set()
    for m in catalogue["moteurs"]:
        if not isinstance(m, dict):
            raise ErreurCatalogue("entrée de moteur invalide")
        for cle in OBLIGATOIRES:
            if cle not in m:
                raise ErreurCatalogue("{} : champ « {} » manquant".format(m.get("id", "?"), cle))
        ident = m["id"]
        if m.get("type", "externe") not in TYPES:
            raise ErreurCatalogue("{} : type inconnu".format(ident))
        gere = m.get("type") == "gere"
        if (not isinstance(ident, str) or not ident.replace("-", "").replace("_", "").isalnum() or not ident.islower() or ident in vus or ident == "openai"
                or (ident in GERES) != gere):
            raise ErreurCatalogue("identifiant invalide, réservé ou en double : {!r}".format(ident))
        vus.add(ident)
        if set(m) - autorises:
            raise ErreurCatalogue("{} : champ inconnu « {} »".format(ident, sorted(set(m) - autorises)[0]))
        if "depot" in m and not (isinstance(m["depot"], str) and RE_DEPOT.match(m["depot"])):
            raise ErreurCatalogue("{} : dépôt invalide (« propriétaire/nom »)".format(ident))
        if "etiquette" in m:
            try:
                if not isinstance(m["etiquette"], str) or len(m["etiquette"]) > 60:
                    raise ValueError
                re.compile(m["etiquette"])
            except (ValueError, re.error):
                raise ErreurCatalogue("{} : motif d'étiquette invalide".format(ident))
        if "experimental" in m and not isinstance(m["experimental"], bool):
            raise ErreurCatalogue("{} : « experimental » doit être vrai ou faux".format(ident))
        if "version_testee" in m and not (isinstance(m["version_testee"], str) and 0 < len(m["version_testee"]) <= 40):
            raise ErreurCatalogue("{} : version testée invalide".format(ident))
        if m["genre"] not in GENRES or (m["genre"] == "ollama" and ident != "ollama"):
            raise ErreurCatalogue("{} : genre inconnu".format(ident))
        if not isinstance(m["nom"], str) or not m["nom"].strip() or len(m["nom"]) > 60:
            raise ErreurCatalogue("{} : nom invalide".format(ident))
        _texte(m["description"], ident + " (description)")
        for liste in ("points_forts", "points_faibles"):
            if liste in m:
                if not isinstance(m[liste], list) or len(m[liste]) > 6:
                    raise ErreurCatalogue("{} : « {} » doit être une courte liste".format(ident, liste))
                for t in m[liste]:
                    _texte(t, "{} ({})".format(ident, liste))
        if "remarque" in m:
            _texte(m["remarque"], ident + " (remarque)")
        if not _adresse_valide(m.get("adresse_defaut", "")):
            raise ErreurCatalogue("{} : adresse invalide".format(ident))
        if not _adresse_valide(m.get("site", "")) or (m.get("site") and not m["site"].startswith("https://")):
            raise ErreurCatalogue("{} : site invalide (https seulement)".format(ident))
        if "cle_requise" in m and not isinstance(m["cle_requise"], bool):
            raise ErreurCatalogue("{} : « cle_requise » doit être vrai ou faux".format(ident))
        if "plateformes" in m and (not isinstance(m["plateformes"], list) or not set(m["plateformes"]) <= set(SYSTEMES)):
            raise ErreurCatalogue("{} : plateformes inconnues".format(ident))
        if "materiel" in m and (not isinstance(m["materiel"], list) or not m["materiel"] or not set(m["materiel"]) <= set(MATERIELS)):
            raise ErreurCatalogue("{} : matériel inconnu".format(ident))
        if "docker" in m and not isinstance(m["docker"], bool):
            raise ErreurCatalogue("{} : « docker » doit être vrai ou faux".format(ident))
    return catalogue


def verifier(enveloppe):
    """Le catalogue contenu dans une enveloppe signée, après vérification de la signature puis du schéma. Lève ErreurCatalogue."""
    if not isinstance(enveloppe, dict) or set(enveloppe) != {"catalogue", "cle", "signature"}:
        raise ErreurCatalogue("enveloppe mal formée")
    cle = CLES_PUBLIQUES.get(enveloppe["cle"])
    if cle is None:
        raise ErreurCatalogue("clé de signature inconnue")
    try:
        signature = base64.b64decode(enveloppe["signature"], validate=True)
    except (ValueError, TypeError):
        raise ErreurCatalogue("signature illisible")
    if not ed25519.verifier(bytes.fromhex(cle), canonique(enveloppe["catalogue"]), signature):
        raise ErreurCatalogue("signature invalide : catalogue modifié ou non signé par une clé de confiance")
    return valider(enveloppe["catalogue"])


def lire_fichier(chemin):
    return verifier(json.loads(Path(chemin).read_text(encoding="utf-8")))


def charger(cache=None, fichier=FICHIER_LIVRE):
    """Le catalogue à utiliser. La copie livrée doit être valide (sinon c'est un défaut de la distribution : l'erreur remonte). `cache` : copie récupérée en ligne, prise seulement
    si elle est signée, valide et plus récente."""
    livre = lire_fichier(fichier)
    if cache and Path(cache).is_file():
        try:
            distant = lire_fichier(cache)
            if (distant["version"], distant.get("date", "")) > (livre["version"], livre.get("date", "")):
                return distant
        except (OSError, ValueError):          # ErreurCatalogue en est une : un cache abîmé, falsifié ou mal signé est ignoré
            pass
    return livre


def telecharger(url, cache, http):
    """Catalogue en ligne -> cache/moteurs.json, seulement s'il est signé et valide. `http(url, entetes)` -> (statut, entetes, corps). Renvoie 'maj' | 'echec' | 'absent'."""
    if not url:
        return "absent"
    try:
        statut, _, corps = http(url, {})
    except OSError:
        return "echec"
    if statut != 200 or len(corps) > TAILLE_MAX:
        return "echec"
    try:
        verifier(json.loads(corps.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        return "echec"          # un catalogue modifié, mal signé ou invalide n'est jamais gardé
    cache = Path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(corps)
    return "maj"


def texte(valeur):
    """Un texte du catalogue dans la langue de l'interface (le français si l'anglais manque)."""
    if isinstance(valeur, dict):
        return valeur.get(langue()) or valeur["fr"]
    return valeur


def fiche(ident, catalogue=None):
    """La fiche d'un moteur que Lutin gère lui-même (« ollama », « llamacpp ») telle que le catalogue la décrit : {description, points_forts, points_faibles, site, remarque, version_testee} dans la langue
    courante, ou None si le catalogue ne la contient pas (la page garde alors les textes écrits dans le code)."""
    try:
        for m in (catalogue or en_cours())["moteurs"]:
            if m["id"] == ident and m.get("type") == "gere":
                v = vue(m)
                v["version_testee"] = m.get("version_testee", "")
                return v
    except (OSError, ValueError):
        pass
    return None


def vue(moteur):
    """Une entrée du catalogue prête pour la page : textes dans la langue courante."""
    return {"id": moteur["id"], "nom": moteur["nom"], "adresse": moteur.get("adresse_defaut", ""), "cle_requise": bool(moteur.get("cle_requise")), "site": moteur.get("site", ""),
            "description": texte(moteur["description"]), "points_forts": [texte(t) for t in moteur.get("points_forts", [])], "points_faibles": [texte(t) for t in moteur.get("points_faibles", [])],
            "remarque": texte(moteur["remarque"]) if moteur.get("remarque") else "", "plateformes": list(moteur.get("plateformes", SYSTEMES)), "experimental": bool(moteur.get("experimental")),
            "materiel": list(moteur.get("materiel", [])), "docker": bool(moteur.get("docker", True))}


def compatibilite(fiche, systeme, en_docker, fabricants):
    """(compatible, raison) : ce serveur peut-il tourner sur CETTE machine ? `systeme` : windows | linux | macos ; `fabricants` : les fabricants de cartes graphiques détectées.
    Une machine dont on ne connaît pas les cartes n'est pas écartée à tort : seul un fabricant CONNU et différent exclut."""
    from .i18n import t as _t
    if systeme not in fiche.get("plateformes", SYSTEMES):
        return False, _t("pas disponible sous {}").format({"windows": "Windows", "linux": "Linux", "macos": "macOS"}.get(systeme, systeme))
    if en_docker and not fiche.get("docker", True):
        return False, _t("ne s'installe pas dans Docker (pas de carte graphique ni d'environnement Python dédié dans le conteneur)")
    voulus = fiche.get("materiel") or []
    connus = {f for f in (fabricants or []) if f and f != "inconnu"}
    if voulus and connus and not (connus & set(voulus)):
        return False, _t("demande une carte graphique {}").format(" ou ".join(v.upper() if v != "apple" else "Apple" for v in voulus))
    if voulus and not connus:
        return False, _t("demande une carte graphique {} (aucune carte détectée)").format(" ou ".join(v.upper() if v != "apple" else "Apple" for v in voulus))
    return True, ""


def prereglages(cache=None):
    """Les serveurs externes proposés d'un clic (pas les moteurs que Lutin gère lui-même)."""
    return [vue(m) for m in charger(cache)["moteurs"] if m.get("type", "externe") == "externe"]


# --------------------------------------------------------------------------- lecture en ligne (au plus une par semaine, en arrière-plan)

INTERVALLE_S = 7 * 24 * 3600
ESSAI = {"quand": 0.0, "actif": False}


def fichier_cache():
    donnees = moteurs.CONTEXTE["donnees"]()
    return Path(donnees) / "moteurs_catalogue.json" if donnees else None


MEMOIRE = {"cle": None, "catalogue": None}


def en_cours():
    """Le catalogue à utiliser maintenant (copie livrée, ou copie en ligne plus récente et bien signée). Gardé en mémoire tant que les fichiers ne changent pas (la page le demande souvent)."""
    cache = fichier_cache()
    try:
        cle = (str(cache), cache.stat().st_mtime_ns if cache and cache.is_file() else 0, FICHIER_LIVRE.stat().st_mtime_ns, tuple(sorted(CLES_PUBLIQUES.items())))
    except OSError:
        cle = None
    if cle is not None and MEMOIRE["cle"] == cle:
        return MEMOIRE["catalogue"]
    c = charger(cache)
    MEMOIRE.update(cle=cle, catalogue=c)
    return c


def en_arriere_plan(url=None, http=None):
    """Va chercher le catalogue en ligne si la copie gardée a plus d'une semaine (et au plus un essai toutes les 6 h). Jamais bloquant, jamais bruyant. `url` : None = adresse par défaut, « » = désactivé."""
    cache = fichier_cache()
    if cache is None or ESSAI["actif"]:
        return
    try:
        if cache.is_file() and time.time() - cache.stat().st_mtime < INTERVALLE_S:
            return
    except OSError:
        pass
    if time.time() - ESSAI["quand"] < 6 * 3600:
        return
    ESSAI.update(actif=True, quand=time.time())

    def travail():
        try:
            from . import miseajour
            telecharger(URL_DEFAUT if url is None else url, cache, http or miseajour.http_get)
        except Exception:  # noqa: BLE001  (jamais bloquant : la copie livrée suffit)
            pass
        finally:
            ESSAI["actif"] = False
    threading.Thread(target=travail, daemon=True, name="catalogue-moteurs").start()
