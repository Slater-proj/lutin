"""Ouvrir un fichier du dossier de travail depuis une réponse : le chemin cité par le modèle devient un lien cliquable.

Le modèle écrit un chemin sous des formes variées (`C:\\Users\\x\\projet\\galerie.html`, `\\\\NAS\\Partage\\projet\\galerie.html`, `file:///…`, `tests/galerie.html`). Ce module retrouve CE fichier DANS le dossier de travail
(jamais ailleurs) puis le sert dans le navigateur, sans l'exécuter :
  - le chemin est cherché relatif au dossier de travail, puis par la fin du chemin (un même partage réseau a plusieurs noms : `\\\\NAS\\…` ou `\\\\192.168.1.59\\…`), la fin la plus longue d'abord ;
  - les règles de l'assistant s'appliquent (rien hors du dossier de travail, ni `.git`, ni les données de Lutin) ;
  - une page HTML ou un SVG s'ouvre en « bac à sable » : ses scripts peuvent tourner mais n'ont aucun accès à Lutin (ni cookies, ni interface) ; ses images voisines (`results/a.png`) se chargent, car l'adresse reflète le dossier ;
  - ce qui n'est pas un document affichable (programme, archive…) est proposé en téléchargement, jamais lancé."""
import mimetypes
import re
import urllib.parse
from pathlib import Path

from . import tools as _outils
from .i18n import t as _t

TAILLE_MAX = 80_000_000
AFFICHABLES = ("text/", "image/", "audio/", "video/", "application/pdf", "application/json")
BAC_A_SABLE = "sandbox allow-scripts allow-popups allow-forms"          # sans « allow-same-origin » : la page n'est pas de l'origine de Lutin


def normaliser(texte):
    """Les morceaux du chemin cité, sans « file:/// », sans lettre de disque ni nom de serveur, avec des « / »."""
    t = urllib.parse.unquote(str(texte or "").strip().strip("`'\" "))
    t = re.sub(r"^file:/*", "", t, flags=re.I).replace("\\", "/")
    t = re.sub(r"^([A-Za-z]):/", "", t)
    return [x for x in t.split("/") if x and x != "."]


def resoudre(texte, racine):
    """Le fichier du dossier de travail que ce texte désigne, ou None. Refuse tout ce qui sort du dossier."""
    morceaux = normaliser(texte)
    if not morceaux or ".." in morceaux:
        return None
    racine = Path(racine).resolve()
    for debut in range(len(morceaux)):          # le chemin entier d'abord, puis sa fin la plus longue
        reste = morceaux[debut:]
        if debut and len(reste) < 2:
            break          # une fin d'un seul nom (« index.html ») est trop vague pour deviner
        candidat = racine.joinpath(*reste)
        try:
            p = candidat.resolve()
            if p.is_file() and (racine in p.parents):
                _outils.chemin_sur(str(p))          # les règles de l'assistant : .git, données de Lutin…
                return p
        except (OSError, ValueError, _outils._m.ErreurOutil):
            continue
    return None


def adresse(p, racine):
    """/ouvrir/<chemin relatif encodé> : l'adresse qui garde les chemins relatifs de la page (ses images voisines) valables."""
    rel = Path(p).resolve().relative_to(Path(racine).resolve()).as_posix()
    return "/ouvrir/" + "/".join(urllib.parse.quote(x) for x in rel.split("/"))


def lire(rel_url, racine):
    """(octets, type, en-têtes) du fichier désigné par l'adresse /ouvrir/… ; ValueError si introuvable ou trop gros."""
    morceaux = [x for x in urllib.parse.unquote(str(rel_url or "")).replace("\\", "/").split("/") if x]
    if not morceaux or ".." in morceaux:
        raise ValueError(_t("Fichier introuvable dans le dossier de travail."))
    try:
        p = _outils.chemin_sur("/".join(morceaux))
    except _outils._m.ErreurOutil as e:
        raise ValueError(str(e))
    if not p.is_file():
        raise ValueError(_t("Fichier introuvable dans le dossier de travail."))
    if p.stat().st_size > TAILLE_MAX:
        raise ValueError(_t("Ce fichier est trop gros pour être ouvert ici ({} Mo).").format(p.stat().st_size // 1_000_000))
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    entetes = {"X-Content-Type-Options": "nosniff"}
    if mime in ("text/html", "image/svg+xml") or p.suffix.lower() in (".html", ".htm", ".svg"):
        mime = "text/html; charset=utf-8" if p.suffix.lower() != ".svg" else "image/svg+xml"
        entetes["Content-Security-Policy"] = BAC_A_SABLE
    elif any(mime.startswith(a) for a in AFFICHABLES):
        entetes["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; media-src 'self'; sandbox"
        if mime.startswith("text/") and "charset" not in mime:
            mime += "; charset=utf-8"
    else:
        entetes["Content-Disposition"] = "attachment; filename*=UTF-8''" + urllib.parse.quote(p.name)          # un programme, une archive : téléchargé, jamais lancé
        entetes["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return p.read_bytes(), mime, entetes
