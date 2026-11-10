"""Le compte GitHub (facultatif) : lever la limite de requêtes de l'API de GitHub pour TOUT ce que Lutin lit sur GitHub.

Sans compte, GitHub ne laisse que 60 requêtes par heure et par adresse à un programme anonyme ; avec un jeton personnel, 5 000. Lutin lit GitHub pour : les versions de ses moteurs (Ollama, llama.cpp,
Colibri, ExLlamaV3), sa propre mise à jour, et la recherche de skills tiers. Le jeton :
  - ne donne AUCUN droit particulier à Lutin : un jeton sans permission suffit (il ne sert qu'à s'identifier), et il n'est envoyé qu'à api.github.com, jamais ailleurs ;
  - est rangé dans un fichier réservé à l'utilisateur (comme la clé Brave), jamais renvoyé à la page (seuls ses 4 derniers caractères le sont) et interdit à l'assistant (dossier de données de Lutin) ;
  - peut aussi venir de la variable d'environnement GITHUB_TOKEN (CI, Docker) : elle l'emporte alors."""
import json
import os
import re
import urllib.parse
from datetime import datetime

from .i18n import t as _t

HOTE_API = "api.github.com"
RE_JETON = re.compile(r"^(?:ghp_|github_pat_|gho_|ghu_|ghs_|ghr_)?[A-Za-z0-9_]{20,255}$")
ADRESSE_LIMITE = "https://api.github.com/rate_limit"          # ne compte pas dans la limite


def _chemin():
    from . import moteur as _m
    return _m.DONNEES / "github.json"


def _lu():
    try:
        d = json.loads(_chemin().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return str(d.get("jeton") or "") if isinstance(d, dict) else ""


def jeton():
    """Le jeton à utiliser (variable d'environnement d'abord, sinon celui des réglages), ou ''."""
    return (os.environ.get("GITHUB_TOKEN") or "").strip() or _lu()


def enregistrer(valeur):
    """Enregistre (ou retire, valeur vide) le jeton des réglages. Renvoie la vue, sans le jeton."""
    valeur = str(valeur or "").strip()
    if valeur and not RE_JETON.match(valeur):
        raise ValueError(_t("Ce jeton GitHub n'a pas la bonne forme (des lettres, des chiffres et _ ; il commence souvent par ghp_ ou github_pat_)."))
    from . import moteur as _m          # importé ici : github.py est lu très tôt (miseajour), avant que moteur soit prêt
    chemin = _chemin()
    if valeur:
        _m.ecrire_atomique(chemin, json.dumps({"jeton": valeur}))
        try:
            os.chmod(chemin, 0o600)          # lisible par son seul propriétaire, là où le système le permet
        except OSError:
            pass
    else:
        try:
            chemin.unlink()
        except OSError:
            pass
    return vue()


def vue():
    j = jeton()
    return {"configure": bool(j), "fin": j[-4:] if j else "", "source": "environnement" if (os.environ.get("GITHUB_TOKEN") or "").strip() else ("reglages" if j else "")}


def entetes_pour(url):
    """L'en-tête d'identification, seulement pour l'API de GitHub (le jeton ne part jamais vers un autre site)."""
    j = jeton()
    try:
        hote = urllib.parse.urlparse(url).hostname
    except ValueError:
        return {}
    return {"Authorization": "Bearer " + j} if j and hote == HOTE_API else {}


def limite_atteinte(statut, entetes):
    """La réponse dit-elle « trop de requêtes » (et non « introuvable » ou « interdit ») ?"""
    entetes = entetes or {}
    return statut in (403, 429) and (str(entetes.get("x-ratelimit-remaining", "")) == "0" or "retry-after" in entetes)


def _heure(entetes):
    try:
        return datetime.fromtimestamp(int((entetes or {}).get("x-ratelimit-reset", ""))).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def conseil():
    """La phrase qui dit quoi faire quand la limite est atteinte : ajouter son compte, ou patienter si c'est déjà fait."""
    if jeton():
        return _t("Même avec ton compte GitHub la limite est atteinte : patiente un peu.")
    return _t("Pour ne plus être limité, ajoute ton compte GitHub (Réglages > Outils > Compte GitHub) : c'est gratuit et ça lève la limite pour toute l'application.")


def suite_erreur(cause):
    """La fin d'un message d'erreur de lecture sur GitHub : si la cause est « trop de requêtes » (HTTP 403 ou 429), le conseil du compte ; sinon, patienter."""
    if "403" in str(cause) or "429" in str(cause):
        return _t("GitHub limite les requêtes (60 par heure sans compte). {}").format(conseil())
    return _t("Réessaie dans quelques minutes.")


def erreur_limite(entetes=None):
    """L'erreur à montrer quand GitHub répond « trop de requêtes » : ce qui se passe, quand ça repart, et quoi faire."""
    heure = _heure(entetes)
    base = _t("GitHub limite le nombre de requêtes (60 par heure sans compte, 5 000 avec).")
    if heure:
        base += " " + _t("Il en accepte de nouveau vers {}.").format(heure)
    return ValueError(base + " " + conseil())


def tester(http):
    """Ce que GitHub répond à ce jeton : {limite, restantes, retour, identifie, compte}. `http(url, entetes) -> (statut, entetes, corps)`."""
    statut, _, corps = http(ADRESSE_LIMITE, {"Accept": "application/vnd.github+json"})
    if statut == 401:
        raise ValueError(_t("GitHub refuse ce jeton (expiré ou mal copié). Crée-en un autre ou retire celui-ci."))
    if statut != 200:
        raise ValueError(_t("GitHub a répondu une erreur (HTTP {}). Réessaie dans quelques minutes.").format(statut))
    try:
        c = json.loads(corps.decode("utf-8")).get("resources", {}).get("core", {})
    except ValueError:
        raise ValueError(_t("Réponse illisible de GitHub."))
    compte = ""
    if jeton():
        try:
            s2, _, c2 = http("https://api.github.com/user", {"Accept": "application/vnd.github+json"})
            if s2 == 200:
                compte = str(json.loads(c2.decode("utf-8")).get("login") or "")
        except (ValueError, OSError):
            compte = ""
    retour = ""
    try:
        retour = datetime.fromtimestamp(int(c.get("reset"))).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        pass
    return {"limite": int(c.get("limit") or 0), "restantes": int(c.get("remaining") or 0), "retour": retour, "identifie": bool(jeton()), "compte": compte}
