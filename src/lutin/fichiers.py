"""Fichiers produits pendant une conversation (PDF, Word, Markdown, vidéo, son…) : une carte sous le message, avec Ouvrir, Télécharger et Supprimer.

Lutin n'ouvre jamais le fichier de lui-même. Le bouton « Ouvrir » demande au système (Windows, macOS, Linux) de l'ouvrir avec l'application que l'utilisateur a choisie pour ce type de fichier : le même geste
qu'un double-clic. Il n'existe que depuis cette machine, et seulement pour des types de documents et de médias (jamais un programme ou un script).

Un fichier n'est servi, ouvert ou supprimé que s'il est inscrit dans la conversation par un outil de Lutin ET situé dans un dossier de travail ou dans le dossier de sortie de ComfyUI."""
import hashlib
import json
import mimetypes
import threading
import time
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import moteur as _m
from .i18n import t as _t

OUVRABLES = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".md", ".txt", ".csv", ".html", ".htm", ".json", ".xlsx", ".ods", ".pptx", ".odp", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
             ".mp4", ".webm", ".mov", ".mkv", ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".zip"}
TAILLE_MAX = 300 * 1024 * 1024          # octets servis à la page


def ouverture_possible():
    """Peut-on demander au système d'ouvrir un fichier ? Pas dans un conteneur ni sur un serveur sans écran : la page ne montre alors que Télécharger."""
    if os.environ.get("LUTIN_DOCKER") == "1":
        return False
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool((os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and shutil.which("xdg-open"))


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


# --------------------------------------------------------------------------- le registre : tout ce que Lutin a créé, pour faire le ménage
VERROU_REGISTRE = threading.Lock()
REGISTRE_MAX = 5000


def _registre():
    d = _m.lire_json(_m.DONNEES / "fichiers_crees.json", {})
    return d if isinstance(d, dict) else {}


def _ecrire_registre(d):
    _m.ecrire_atomique(_m.DONNEES / "fichiers_crees.json", json.dumps(d, ensure_ascii=False))


def entree_image(image_id, chemin):
    p = Path(chemin)
    try:
        taille = p.stat().st_size
    except OSError:
        taille = 0
    return {"id": image_id, "genre": "image", "chemin": str(p), "nom": p.name, "taille": taille}


def enregistrer(entrees, conversation):
    """Inscrit des fichiers créés au registre (une fois chacun) : la conversation d'où ils viennent, la date."""
    if not entrees:
        return
    with VERROU_REGISTRE:
        reg = _registre()
        liste = reg.get("liste") if isinstance(reg.get("liste"), list) else []
        connus = {e.get("id") for e in liste}
        for e in entrees:
            if e.get("id") and e["id"] not in connus:
                liste.append(dict(e, conversation=conversation, date=int(time.time())))
        reg["liste"] = liste[-REGISTRE_MAX:]
        _ecrire_registre(reg)


def _depuis_les_conversations():
    """Les fichiers déjà inscrits dans des conversations d'avant le registre : repris une seule fois."""
    trouves = []
    for f in (_m.DONNEES / "conversations").glob("*.json"):
        c = _m.lire_json(f, {}) or {}
        for m in c.get("messages", []):
            for e in m.get("fichiers_joints") or []:
                trouves.append(dict(e, genre="fichier", conversation=f.stem, date=int(f.stat().st_mtime)))
            for i in m.get("medias") or []:
                chemin = (m.get("medias_fichiers") or {}).get(i)
                if chemin:
                    trouves.append(dict(entree_image(i, chemin), conversation=f.stem, date=int(f.stat().st_mtime)))
    return trouves


def lister():
    """Les fichiers créés qui existent encore, les plus récents d'abord, avec leur taille. Ceux qui ont disparu du disque sont retirés du registre."""
    with VERROU_REGISTRE:
        reg = _registre()
        liste = reg.get("liste") if isinstance(reg.get("liste"), list) else []
        if not reg.get("rempli"):
            connus = {e.get("id") for e in liste}
            liste += [e for e in _depuis_les_conversations() if e["id"] not in connus]
            reg["rempli"] = True
        gardes, sortie = [], []
        for e in liste:
            p = Path(e.get("chemin", ""))
            try:
                if not p.is_file():
                    continue
                taille = p.stat().st_size
            except OSError:
                continue
            gardes.append(e)
            sortie.append({"id": e["id"], "genre": e.get("genre", "fichier"), "nom": e.get("nom") or p.name, "chemin": str(p), "taille": taille, "date": e.get("date", 0),
                           "conversation": e.get("conversation", ""), "conversation_existe": _m.conv_chemin(e.get("conversation", "")).exists() if e.get("conversation") else False})
        if len(gardes) != len(liste) or not _registre().get("rempli"):
            reg["liste"] = gardes
            _ecrire_registre(reg)
    sortie.sort(key=lambda x: -x["date"])
    return {"liste": sortie, "total": sum(x["taille"] for x in sortie)}


def _supprimer_directement(e):
    verifier(e).unlink()
    if e.get("genre") == "image":
        from . import images
        if e["id"] not in images.referencees():
            try:
                images.chemin(e["id"]).unlink()
            except (OSError, ValueError):
                pass


def supprimer_selection(ids):
    """Supprime ces fichiers créés (du disque, et des conversations qui les montrent) et les retire du registre. Rend ce qui a été fait et ce qui n'a pas pu l'être."""
    from . import revue
    voulus = set(ids)
    reg = _registre()
    cibles = [e for e in (reg.get("liste") or []) if e.get("id") in voulus]
    faits, ignores, libere = [], [], 0
    for e in cibles:
        taille = 0
        try:
            taille = Path(e["chemin"]).stat().st_size
        except OSError:
            pass
        conv = e.get("conversation", "")
        try:
            if conv in _m.TOURS_ACTIFS:
                raise ValueError(_t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la."))
            try:
                if conv and _m.conv_chemin(conv).exists():
                    (revue.supprimer_media(conv, e["id"]) if e.get("genre") == "image" else supprimer(conv, e["id"]))
                    if Path(e["chemin"]).is_file():
                        _supprimer_directement(e)                        # la conversation ne montrait plus ce fichier : on l'efface quand même
                else:
                    _supprimer_directement(e)
            except ValueError:
                if conv in _m.TOURS_ACTIFS:                              # une réponse a démarré entre-temps : on ne touche à rien
                    raise ValueError(_t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la."))
                if Path(e["chemin"]).is_file():
                    _supprimer_directement(e)                            # la conversation n'a plus la carte : on supprime le fichier lui-même
            faits.append(e["id"])
            libere += taille
        except (ValueError, OSError) as erreur:
            ignores.append({"nom": e.get("nom", ""), "raison": str(erreur)})
    with VERROU_REGISTRE:
        reg = _registre()
        reg["liste"] = [e for e in (reg.get("liste") or []) if e.get("id") not in set(faits)]
        _ecrire_registre(reg)
    return {"supprimes": len(faits), "libere": libere, "ignores": ignores}


def ouvrir_dossier(fichier_id):
    """Ouvre le dossier qui contient un fichier créé (l'explorateur de fichiers)."""
    e = next((x for x in (_registre().get("liste") or []) if x.get("id") == fichier_id), None)
    if e is None:
        raise ValueError(_t("Ce fichier n'est plus dans la liste."))
    p = verifier(e)
    _lancer(p.parent)
    return {"ok": True}
