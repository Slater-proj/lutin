"""Les variantes de précision (quantification) d'un modèle Ollama : q4_K_M, q5_K_M, q8_0, fp16…

Un modèle est enregistré avec une précision plus ou moins grande pour ses « poids ». Plus elle est basse, plus le fichier est petit et rapide, et plus le modèle perd en finesse, surtout les petits modèles
(appels d'outils mal formés, réponses moins justes). Ollama installe par défaut du 4 bits (q4_K_M) ; la page de chaque modèle sur ollama.com liste aussi les autres précisions (« qwen3:8b-q8_0 »).
Ici on lit cette liste, avec la taille de chaque variante, pour que Lutin dise laquelle tient sur ta machine et laquelle vaut le coup. Rien n'est installé sans ton clic."""
import re
import time

from . import decouverte, miseajour
from .i18n import t as _t

URL = "https://ollama.com/library/{}/tags"
DUREE_CACHE = 30 * 60
CACHE = {}
RE_BLOC = re.compile(r'<a href="/library/([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)" class="md:hidden[^"]*">(.*?)</a>', re.S)
RE_TAILLE = re.compile(r"([0-9]+(?:[.][0-9]+)?)\s*(GB|MB)", re.I)
RE_PRECISION = re.compile(r"^(q[0-9](?:_[0-9A-Za-z]+)*|fp16|bf16|f16|fp32)$", re.I)
RE_ID = re.compile(r"^([a-z0-9._-]+):([a-z0-9._]+)$", re.I)          # un modèle de la bibliothèque officielle, avec sa taille (pas d'espace de noms, pas de précision déjà choisie)


def decrire(precision):
    """Une phrase sur ce que change cette précision (ordre de grandeur, pas une mesure sur ta machine)."""
    p = precision.lower()
    if p.startswith("q2") or p.startswith("q3"):
        return _t("Très compressé : petit et rapide, mais le modèle perd nettement en justesse. À éviter pour les outils.")
    if p.startswith("q4"):
        return _t("Le défaut : environ 4 fois plus petit que l'original, rapide. Un peu moins précis, surtout pour les petits modèles.")
    if p.startswith("q5"):
        return _t("Compromis : un peu plus gros et un peu plus lent que le 4 bits, nettement plus fidèle.")
    if p.startswith("q6"):
        return _t("Très fidèle, environ 1,5 fois plus gros que le 4 bits.")
    if p.startswith("q8"):
        return _t("Presque sans perte, environ 2 fois plus gros et plus lent que le 4 bits. Recommandé pour les appels d'outils d'un petit modèle si la mémoire le permet.")
    return _t("Précision d'origine : très gros, pour les machines avec beaucoup de mémoire.")


def analyser(page, nom, etiquette):
    """{defaut: {go}, variantes: [{precision, id, go}]} lues dans la page des étiquettes d'un modèle. `etiquette` : la taille (« 8b »). Une page méconnaissable donne une liste vide."""
    defaut, variantes = None, []
    for modele, tag, corps in RE_BLOC.findall(page or ""):
        if modele != nom:
            continue
        m = RE_TAILLE.search(decouverte.texte(corps))
        if not m:
            continue
        go = round(float(m.group(1)) / (1000 if m.group(2).upper() == "MB" else 1), 2)
        if tag == etiquette:
            defaut = {"id": "{}:{}".format(nom, tag), "go": go}
        elif tag.startswith(etiquette + "-") and RE_PRECISION.match(tag[len(etiquette) + 1:]):
            variantes.append({"precision": tag[len(etiquette) + 1:], "id": "{}:{}".format(nom, tag), "go": go})
    if defaut:
        for v in variantes:
            v["defaut"] = abs(v["go"] - defaut["go"]) <= max(0.15, 0.05 * defaut["go"])          # la variante que « modele:taille » installe déjà
    return {"defaut": defaut, "variantes": sorted(variantes, key=lambda v: v["go"])}


def lister(modele, http=miseajour.http_get, maintenant=time.time):
    """Les précisions disponibles pour `modele` (« qwen3:8b »). Lève ValueError si ce n'est pas un modèle de la bibliothèque officielle, OSError si le site ne répond pas."""
    m = RE_ID.match(str(modele or ""))
    if not m or RE_PRECISION.match(m.group(2)) or re.search(r"-(q[0-9]|fp16|bf16)", m.group(2), re.I):
        raise ValueError(_t("Les variantes de précision se choisissent à partir d'un modèle de la bibliothèque d'Ollama avec sa taille (par exemple qwen3:8b)."))
    nom, etiquette = m.group(1), m.group(2)
    en_cache = CACHE.get(nom)
    if en_cache and maintenant() - en_cache[0] < DUREE_CACHE:
        page = en_cache[1]
    else:
        statut, _, corps = http(URL.format(nom))
        if statut != 200:
            raise OSError(_t("ollama.com a répondu {}.").format(statut))
        page = corps.decode("utf-8", "replace")
        CACHE[nom] = (maintenant(), page)
    resultat = analyser(page, nom, etiquette)
    if not resultat["variantes"] and not resultat["defaut"]:
        raise OSError(_t("Les variantes de ce modèle n'ont pas pu être lues sur ollama.com."))
    return resultat
