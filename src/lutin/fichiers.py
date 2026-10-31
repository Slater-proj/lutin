"""Fichiers produits pendant une conversation (PDF, Word, Markdown, vidéo, son…) : une carte sous le message, avec Ouvrir, Télécharger et Supprimer.

Lutin n'ouvre jamais le fichier de lui-même. Le bouton « Ouvrir » demande au système (Windows, macOS, Linux) de l'ouvrir avec l'application que l'utilisateur a choisie pour ce type de fichier : le même geste
qu'un double-clic. Il n'existe que depuis cette machine, et seulement pour des types de documents et de médias (jamais un programme ou un script).

Un fichier n'est servi, ouvert ou supprimé que s'il est inscrit dans la conversation par un outil de Lutin ET situé dans un dossier de travail ou dans le dossier de sortie de ComfyUI."""
import hashlib
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from . import moteur as _m
from .i18n import t as _t

OUVRABLES = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".md", ".txt", ".csv", ".html", ".htm", ".json", ".xlsx", ".ods", ".pptx", ".odp", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
             ".mp4", ".webm", ".mov", ".mkv", ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".zip"}
TAILLE_MAX = 300 * 1024 * 1024          # octets servis à la page


def identifiant(chemin):
    return hashlib.sha1(str(chemin).encode("utf-8")).hexdigest()[:12]


def entree(chemin):
    """{id, chemin, nom, taille} pour un fichier à rattacher à un message."""
    p = Path(chemin)
    try:
        taille = p.stat().st_size
    except OSError:
        taille = 0
    return {"id": identifiant(p), "chemin": str(p), "nom": p.name, "taille": taille}


def racines_permises():
    from . import addons, travaux
    racines = []
    try:
        racines += [Path(t["chemin"]).resolve() for t in travaux.liste(_m.config_lue())]
    except (OSError, ValueError):
        pass
    racines.append(_m.RACINE.resolve())
    dossier = addons.reglages("comfyui").get("dossier") or ""
    if dossier:
        racines.append((Path(dossier) / "output").resolve())
    return racines


def trouver(ident, fichier_id):
    """(message, entrée) du fichier inscrit dans cette conversation, ou ValueError."""
    c = _m.conv_lire(ident)
    for m in c["messages"]:
        for e in m.get("fichiers_joints") or []:
            if e.get("id") == fichier_id:
                return c, m, e
    raise ValueError(_t("Ce fichier n'est plus dans la conversation."))


def verifier(entree_):
    """Le Path du fichier s'il existe et se trouve dans un dossier permis ; ValueError sinon."""
    p = Path(entree_.get("chemin", ""))
    try:
        r = p.resolve()
    except OSError:
        raise ValueError(_t("Fichier introuvable."))
    if not r.is_file():
        raise ValueError(_t("Ce fichier n'existe plus (déplacé ou supprimé)."))
    if not any(racine == r or racine in r.parents for racine in racines_permises()):
        raise ValueError(_t("Ce fichier est en dehors des dossiers de travail : refusé."))
    return r


def lire(ident, fichier_id):
    """(octets, type MIME, nom) pour le téléchargement."""
    _, _, e = trouver(ident, fichier_id)
    p = verifier(e)
    if p.stat().st_size > TAILLE_MAX:
        raise ValueError(_t("Fichier trop gros pour être envoyé à la page ({} Mo au plus) : ouvre-le depuis son dossier.").format(TAILLE_MAX // (1024 * 1024)))
    return p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream", p.name


def ouvrir(ident, fichier_id):
    """Demande au système d'ouvrir le fichier avec son application par défaut."""
    _, _, e = trouver(ident, fichier_id)
    p = verifier(e)
    if p.suffix.lower() not in OUVRABLES:
        raise ValueError(_t("Ce type de fichier ne s'ouvre pas d'ici (seuls les documents et les médias le permettent) : ouvre-le depuis son dossier."))
    _lancer(p)
    return {"ok": True}


def _lancer(p):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))                                                       # noqa: S606  (le geste d'un double-clic : l'application choisie par l'utilisateur)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError as erreur:
        raise ValueError(_t("Le système n'a pas pu ouvrir ce fichier : {}").format(erreur))


# --------------------------------------------------------------------------- fichiers envoyés par l'utilisateur (pièces jointes)
def piece_lire(piece_id, nom):
    """(octets, type MIME, nom) d'une pièce jointe, pour la télécharger de nouveau sous son vrai nom."""
    from . import pieces
    p = pieces.chemin(piece_id)
    nom = pieces.nom_propre(nom) if nom else p.name
    return p.read_bytes(), mimetypes.guess_type(nom)[0] or "application/octet-stream", nom


def piece_ouvrir(piece_id, nom):
    """Ouvre une pièce jointe avec l'application par défaut : une copie est faite sous son vrai nom (la pièce gardée porte un nom tiré de son contenu), seulement pour les documents et médias."""
    import shutil
    from . import pieces
    p = pieces.chemin(piece_id)
    nom = pieces.nom_propre(nom) if nom else p.name
    if Path(nom).suffix.lower() not in OUVRABLES:
        raise ValueError(_t("Ce type de fichier ne s'ouvre pas d'ici (seuls les documents et les médias le permettent) : ouvre-le depuis son dossier."))
    cible = _m.DONNEES / "pieces-ouvertes" / piece_id.split(".")[0][:10] / nom
    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, cible)
    _lancer(cible)
    return {"ok": True}


def supprimer(ident, fichier_id):
    """Retire la carte de la conversation et supprime le fichier."""
    if ident in _m.TOURS_ACTIFS:
        raise ValueError(_t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la."))
    c, m, e = trouver(ident, fichier_id)
    supprime = False
    try:
        p = verifier(e)
        p.unlink()
        supprime = True
    except (ValueError, OSError):
        pass                                                                           # déjà parti, ou hors des dossiers permis : la carte est retirée, le fichier n'est pas touché
    m["fichiers_joints"] = [x for x in m["fichiers_joints"] if x.get("id") != fichier_id]
    if not m["fichiers_joints"]:
        m.pop("fichiers_joints", None)
    import json
    _m.ecrire_atomique(_m.conv_chemin(ident), json.dumps(c, ensure_ascii=False))
    return {"ok": True, "fichier_supprime": supprime}
