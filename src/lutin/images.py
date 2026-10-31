"""Images jointes à un message (captures d'écran, photos) pour les modèles qui voient.

Les octets sont gardés dans donnees/images/ sous un nom tiré de leur contenu (la même image envoyée deux fois n'existe qu'une fois) ; la conversation ne garde que ce nom.
Rien n'est envoyé ailleurs qu'au modèle local. Le type est reconnu au contenu, jamais au nom ni à l'en-tête envoyé par la page."""
import base64
import hashlib
import re
import time

from .i18n import t as _t
from . import moteur as _m

TAILLE_MAX = 8 * 1024 * 1024       # octets par image
PAR_MESSAGE = 4
RECENTS = 6                         # les images ne sont renvoyées au modèle que pour les derniers messages : les anciennes alourdiraient chaque réponse pour rien
RE_ID = re.compile(r"^[0-9a-f]{20}\.(png|jpg|gif|webp)$")
TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def dossier():
    return _m.DONNEES / "images"


def type_de(octets):
    """Extension reconnue d'après les premiers octets, ou None."""
    if octets[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if octets[:3] == b"\xff\xd8\xff":
        return "jpg"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "webp"
    return None


def enregistrer(octets):
    if not octets:
        raise ValueError(_t("Image vide."))
    if len(octets) > TAILLE_MAX:
        raise ValueError(_t("Image trop grosse ({} Mo au plus).").format(TAILLE_MAX // (1024 * 1024)))
    ext = type_de(octets)
    if ext is None:
        raise ValueError(_t("Format d'image non géré : PNG, JPEG, GIF ou WebP."))
    ident = hashlib.sha256(octets).hexdigest()[:20] + "." + ext
    f = dossier() / ident
    if not f.is_file():
        dossier().mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(octets)
        tmp.replace(f)
    return ident


def chemin(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError(_t("Image inconnue."))
    f = dossier() / ident
    if not f.is_file():
        raise ValueError(_t("Image inconnue."))
    return f


def lire(ident):
    """(octets, type MIME)."""
    f = chemin(ident)
    return f.read_bytes(), TYPES[f.suffix[1:]]


def verifier_liste(ids):
    """Liste d'identifiants valides et existants (au plus PAR_MESSAGE) ; ValueError sinon."""
    ids = [str(i) for i in (ids or [])]
    if len(ids) > PAR_MESSAGE:
        raise ValueError(_t("{} images au plus par message.").format(PAR_MESSAGE))
    for i in ids:
        chemin(i)
    return ids


def pour_le_modele(messages, voit=True):
    """Copie des messages où les identifiants d'images des derniers messages deviennent du base64 (ce qu'attend Ollama).
    Les anciennes images sont retirées, avec une mention dans le texte : le modèle sait qu'elles existaient."""
    sortie = []
    debut_recent = max(0, len(messages) - RECENTS)
    for n, m in enumerate(messages):
        ids = m.get("images")
        if not ids:
            sortie.append(m)
            continue
        m = dict(m)
        if n >= debut_recent and voit:
            encodees = []
            for i in ids:
                try:
                    encodees.append(base64.b64encode(chemin(i).read_bytes()).decode("ascii"))
                except (OSError, ValueError):
                    pass                      # fichier purgé : on continue sans
            m["images"] = encodees
            if not encodees:
                m.pop("images")
        else:
            m.pop("images")
            m["content"] = (m.get("content") or "") + "\n[{} image(s) jointe(s), non visible(s) ici]".format(len(ids))
        sortie.append(m)
    return sortie


def referencees():
    """Identifiants cités par au moins une conversation."""
    vus = set()
    for c in (_m.DONNEES / "conversations").glob("*.json"):
        for m in (_m.lire_json(c, {}) or {}).get("messages", []):
            vus.update(m.get("images") or [])
            vus.update(m.get("medias") or [])
    return vus


def nettoyer(age_jours=2):
    """Supprime les images que plus aucune conversation ne cite, après un délai (le temps d'envoyer le message). Renvoie le nombre supprimé."""
    if not dossier().is_dir():
        return 0
    gardees, limite, n = referencees(), time.time() - age_jours * 86400, 0
    for f in dossier().iterdir():
        try:
            if f.name not in gardees and f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n
