"""Parcourir la bibliothèque d'Ollama : les modèles récents ou populaires, sans attendre qu'ils entrent dans le catalogue de Lutin.

Le catalogue de Lutin est une sélection commentée (notes, mémoire demandée) ; il ne peut pas connaître un modèle sorti hier. Cette page-ci lit la liste publique d'ollama.com (nom, description,
capacités, tailles) et laisse installer n'importe quel modèle en un clic. Elle n'a pas d'interface officielle à interroger : la lecture est donc tolérante, et si le site change, la liste est
simplement vide (avec un message), jamais une erreur qui casse la page. Rien n'est installé sans ton clic."""
import html
import re
import time
import urllib.parse

from . import miseajour
from .i18n import t as _t

URL = "https://ollama.com/search"
ORDRES = ("newest", "popular")
DUREE_CACHE = 15 * 60
CAPACITES = ("tools", "vision", "thinking", "embedding", "audio", "cloud")
RE_BLOC = re.compile(r'<li\s[^>]*>\s*<a href="/library/([A-Za-z0-9._-]+)"(.*?)</a>\s*</li>', re.S)
RE_TAILLE = re.compile(r"^(\d+(?:\.\d+)?[bm]|e\d+b|\d+x\d+(?:\.\d+)?b)$", re.I)
CACHE = {}


def texte(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def analyser(page):
    """La liste des modèles d'une page de résultats : [{nom, description, capacites, tailles, maj, telechargements}]. Une page méconnaissable donne une liste vide."""
    sortie = []
    for nom, corps in RE_BLOC.findall(page or ""):
        sans_age = re.sub(r'<span[^>]*title="Updated[^>]*>.*?</span>', "", corps, flags=re.S)          # « 5m » = il y a 5 minutes, pas 5 millions de paramètres
        etiquettes = [texte(s) for s in re.findall(r"<span[^>]*>(.*?)</span>", sans_age, re.S)]
        etiquettes = [e for e in etiquettes if e]
        description = re.search(r"<p[^>]*>(.*?)</p>", corps, re.S)
        maj = re.search(r'title="Updated ([^"]+)"', corps)
        telechargements = re.search(r'title="([\d,]+) downloads"', corps)
        sortie.append({
            "nom": nom,
            "description": texte(description.group(1))[:300] if description else "",
            "capacites": [e.lower() for e in etiquettes if e.lower() in CAPACITES],
            "tailles": [e.lower() for e in etiquettes if RE_TAILLE.match(e)],
            "maj": html.unescape(maj.group(1)) if maj else "",
            "telechargements": int(telechargements.group(1).replace(",", "")) if telechargements else 0,
        })
    return sortie


def chercher(terme="", ordre="newest", page=1, http=miseajour.http_get, maintenant=time.time):
    """{modeles, suite} pour une recherche (vide = tout). Lève OSError si le site ne répond pas (ou en mode hors ligne)."""
    if ordre not in ORDRES:
        raise ValueError(_t("Tri inconnu."))
    terme = re.sub(r"[^\w.:/ -]", "", str(terme or ""))[:60].strip()
    page = max(1, min(int(page or 1), 20))
    cle = (terme, ordre, page)
    en_cache = CACHE.get(cle)
    if en_cache and maintenant() - en_cache[0] < DUREE_CACHE:
        return en_cache[1]
    adresse = URL + "?" + urllib.parse.urlencode({"q": terme, "o": ordre, "p": page})
    statut, _, corps = http(adresse)
    if statut != 200:
        raise OSError(_t("ollama.com a répondu {}.").format(statut))
    page_html = corps.decode("utf-8", "replace")
    trouves = analyser(page_html)
    resultat = {"modeles": [m for m in trouves if "embedding" not in m["capacites"] and not ("cloud" in m["capacites"] and not m["tailles"])], "suite": 'data-has-more="true"' in page_html}          # ni modèles d'embeddings (pas de conversation), ni modèles seulement dans le nuage
    if not trouves:
        raise OSError(_t("La liste d'ollama.com n'a pas pu être lue (le site a peut-être changé). Tu peux toujours installer un modèle par son nom."))
    CACHE[cle] = (maintenant(), resultat)
    return resultat
