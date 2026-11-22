"""Ce qui sort de la machine : le nettoyage des requêtes et le journal des recherches envoyées à un service extérieur.

Une recherche chez Tavily, Exa, Perplexity, Brave, DuckDuckGo ou Bing quitte la machine avec le texte de la requête. Deux protections, sans aucun appel à un modèle (donc sans latence) :
  - `nettoyer_requete` retire d'une requête ce qui ne devrait jamais partir : adresses e-mail, numéros de téléphone, numéros de carte bancaire (validés par la clé de Luhn), IBAN, clés et jetons,
    adresses IP du réseau local, chemins qui contiennent un nom d'utilisateur. Ce qui a été retiré est dit (la catégorie, jamais la valeur) ;
  - `noter` écrit chaque envoi dans `sorties.jsonl` (heure, service, requête telle qu'elle est partie, catégories retirées, réussite) ; la page Santé le montre et permet de le vider.
Une instance SearXNG chez soi n'est pas « extérieure » : rien n'y est nettoyé ni noté. Le fichier garde au plus 300 envois."""
import json
import re
import threading
import time

from . import storage as _donnees
from .i18n import t as _t

MAX_ENTRIES = 300
LOCK = threading.Lock()

_KEYS = re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|xox[abp]|AKIA|AIza|tvly|pplx|exa|BSA)[-_A-Za-z0-9]{12,}\b")
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
_CARD = re.compile(r"(?<![\d.])(?:\d[ \-]?){13,19}(?![\d.])")
_PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .\-]?\(?0?\)?|0)\d(?:[ .\-]?\d{2}){4}(?![\w.])|(?<![\w.])\+\d[\d .\-]{8,14}\d(?![\w.])")
_PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")
_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s]*)?|(?<![\w.])/(?:home|Users)/[^/\s]+(?:/[^\s]*)?")


def _luhn(chiffres):
    somme, double = 0, False
    for c in reversed(chiffres):
        n = int(c)
        if double:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        somme += n
        double = not double
    return somme % 10 == 0


def clean_query(requete):
    """(requête propre, catégories retirées). Prudent : une date, un numéro de version ou une année ne sont pas touchés ; un numéro de carte n'est retiré que s'il passe la clé de Luhn."""
    texte = str(requete or "")
    retire = []

    def sans(motif, nom, garde=None):
        nonlocal texte

        def remplace(m):
            if garde is not None and not garde(m.group(0)):
                return m.group(0)
            if nom not in retire:
                retire.append(nom)
            return " "
        texte = motif.sub(remplace, texte)
    sans(_EMAIL, _t("adresse e-mail"))
    sans(_KEYS, _t("clé ou jeton secret"))
    sans(_PATH, _t("chemin contenant un nom d'utilisateur"))
    sans(_CARD, _t("numéro de carte bancaire"), lambda s: _luhn(re.sub(r"\D", "", s)) and 13 <= len(re.sub(r"\D", "", s)) <= 19)
    sans(_IBAN, "IBAN", lambda s: len(s.replace(" ", "")) >= 15)
    sans(_PHONE, _t("numéro de téléphone"))
    sans(_PRIVATE_IP, _t("adresse du réseau local"))
    sans(_TOKEN, _t("clé ou jeton secret"))
    return re.sub(r"\s+", " ", texte).strip(), retire


def _path():
    from . import core as _m
    return _m.DONNEES / "sorties.jsonl"


def record(service, requete, retire=(), ok=True):
    """Une ligne dans le journal. Ne lève jamais : un journal qui échoue ne doit pas empêcher une recherche."""
    try:
        ligne = json.dumps({"quand": time.strftime("%Y-%m-%d %H:%M:%S"), "service": str(service), "requete": str(requete)[:300], "retire": list(retire), "ok": bool(ok)}, ensure_ascii=False)
        with LOCK:
            chemin = _path()
            chemin.parent.mkdir(parents=True, exist_ok=True)
            with open(chemin, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
            if chemin.stat().st_size > MAX_ENTRIES * 700:          # rogner de temps en temps, sans relire le fichier à chaque envoi
                lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_ENTRIES:]
                _donnees.write_atomic(chemin, "\n".join(lignes) + "\n")
    except (OSError, ValueError):
        pass


def read(n=60):
    """Les derniers envois, du plus récent au plus ancien."""
    try:
        lignes = _path().read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(n), MAX_ENTRIES)):]
    except OSError:
        return []
    sortie = []
    for ligne in reversed(lignes):
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict):
            sortie.append(x)
    return sortie


def clear():
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass
