"""Pièces jointes qui ne sont pas des images : documents (PDF, Word, LibreOffice, PowerPoint, Excel, HTML) et fichiers texte (notes, code, tableaux CSV, JSON, journaux…).

Le fichier est gardé dans donnees/pieces/ sous un nom tiré de son contenu ; son texte est extrait UNE fois, à l'envoi (un PDF illisible est signalé tout de suite, pas au milieu d'une réponse). La conversation ne garde que
le nom et l'identifiant ; au moment de demander une réponse au modèle, le texte des pièces des derniers messages est ajouté au message de l'utilisateur, dans la limite d'une part de la fenêtre de contexte
(le reste est coupé, avec une mention). Rien n'est exécuté : les documents sont seulement lus."""
import hashlib
import re
import secrets
import time
from pathlib import Path

from . import text_extraction
from . import core as _m
from .i18n import t as _t

MAX_SIZE = 20 * 1024 * 1024
PER_MESSAGE = 5
RECENT = 6                 # le texte des pièces n'est renvoyé au modèle que pour les derniers messages : les anciennes alourdiraient chaque réponse pour rien
CONTEXT_SHARE = 0.5      # au plus la moitié de la fenêtre de contexte pour les pièces d'une demande
CHARS_PER_TOKEN = 3
MIN_PART = 2000           # chaque pièce garde au moins ce début, même si elles sont nombreuses
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".srt", ".vtt", ".tex",
             ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".cmd", ".ps1", ".sql", ".r", ".lua", ".swift"}
RE_ID = re.compile(r"^[0-9a-f]{20}\.[a-z0-9]{1,8}$")


def folder():
    return _m.DONNEES / "pieces"


def clean_name(nom):
    """Le nom affiché : sans chemin, sans caractère de contrôle, 120 caractères au plus."""
    nom = re.sub(r"[\x00-\x1f\x7f]", "", str(nom or "")).replace("\\", "/").rsplit("/", 1)[-1].strip()
    return nom[:120] or _t("fichier")


def decode(octets):
    """Le texte d'un fichier texte, ou None si c'est du binaire (octets nuls, ou trop de caractères de contrôle)."""
    if b"\x00" in octets[:8192]:
        return None
    for codage in ("utf-8-sig", "cp1252"):
        try:
            texte = octets.decode(codage)
        except UnicodeDecodeError:
            continue
        gene = sum(1 for c in texte[:8192] if ord(c) < 32 and c not in "\n\r\t\f")
        return texte if gene < 8 else None
    return None


def extension_of(nom, octets):
    """L'extension retenue pour le fichier gardé, ou None si ce n'est ni un document connu ni du texte."""
    ext = Path(nom).suffix.lower()
    if ext in text_extraction.FORMATS or ext in TEXT_EXTENSIONS:
        return ext
    return ".txt" if decode(octets) is not None else None


def file_text(chemin, ext):
    if ext in TEXT_EXTENSIONS or ext == ".txt":
        t = decode(Path(chemin).read_bytes())
        if t is None:
            raise text_extraction.ExtractionError(_t("Ce fichier n'est pas du texte lisible."))
        return t.strip()
    return text_extraction.texte(chemin)


def save(octets, nom):
    """(identifiant, nom affiché, nombre de caractères) ; ValueError si le fichier est vide, trop gros, d'un format inconnu ou illisible."""
    if not octets:
        raise ValueError(_t("Fichier vide."))
    if len(octets) > MAX_SIZE:
        raise ValueError(_t("Fichier trop gros ({} Mo au plus).").format(MAX_SIZE // (1024 * 1024)))
    nom = clean_name(nom)
    ext = extension_of(nom, octets)
    if ext is None:
        raise ValueError(_t("Format non géré : « {} ». Joins un PDF, un document Word, LibreOffice, PowerPoint ou Excel, une page HTML, une image, ou un fichier texte.").format(Path(nom).suffix or nom))
    ident = hashlib.sha256(octets).hexdigest()[:20] + ext
    f = folder() / ident
    if not f.is_file():
        folder().mkdir(parents=True, exist_ok=True)
        tmp = f.with_name("{}.{}.tmp".format(f.name, secrets.token_hex(4)))          # à soi : deux envois du même fichier à la fois partageaient un nom
        try:
            tmp.write_bytes(octets)
            tmp.replace(f)
        except OSError:
            if not f.is_file():                    # l'autre envoi l'a écrit (même contenu, même nom) : rien à refaire
                raise
        finally:
            tmp.unlink(missing_ok=True)
    try:
        texte = read_text(ident)
    except text_extraction.ExtractionError as erreur:
        f.unlink(missing_ok=True)
        (folder() / (ident + ".texte")).unlink(missing_ok=True)
        raise ValueError(str(erreur)) from erreur
    if not texte.strip():
        f.unlink(missing_ok=True)
        (folder() / (ident + ".texte")).unlink(missing_ok=True)
        raise ValueError(_t("Aucun texte lisible dans « {} » (un PDF scanné ne contient que des images).").format(nom))
    return ident, nom, len(texte)


def chemin(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError(_t("Fichier joint inconnu."))
    f = folder() / ident
    if not f.is_file():
        raise ValueError(_t("Fichier joint inconnu."))
    return f


def _extract_when_readable(f, essais=40):
    """Sous Windows, lire un fichier que l'autre envoi du même contenu vient de remplacer lève PermissionError un instant : on relit un peu plus tard
    (même règle que storage.lire_json ; tests/test_fichiers.py, envoi en double)."""
    for _ in range(essais):
        try:
            return file_text(f, f.suffix.lower())
        except PermissionError:
            time.sleep(0.05)
    return file_text(f, f.suffix.lower())


def read_text(ident):
    """Le texte extrait de la pièce (extrait une fois, gardé à côté)."""
    f = chemin(ident)
    cache = folder() / (ident + ".texte")
    try:
        if cache.is_file() and cache.stat().st_mtime >= f.stat().st_mtime:
            return cache.read_text(encoding="utf-8")
    except OSError:
        pass
    texte = _extract_when_readable(f)
    try:
        cache.write_text(texte, encoding="utf-8")
    except OSError:
        pass
    return texte


def check_list(pieces):
    """Liste [{id, nom}] nettoyée (au plus PAR_MESSAGE) ; ValueError si une pièce n'existe pas."""
    sortie = []
    for p in pieces or []:
        if not isinstance(p, dict):
            raise ValueError(_t("Fichier joint inconnu."))
        chemin(p.get("id"))
        sortie.append({"id": p["id"], "nom": clean_name(p.get("nom"))})
    if len(sortie) > PER_MESSAGE:
        raise ValueError(_t("{} fichiers au plus par message.").format(PER_MESSAGE))
    return sortie


def character_budget(num_ctx):
    return int(num_ctx * CONTEXT_SHARE * CHARS_PER_TOKEN)


def for_model(messages, budget):
    """Copie des messages où le texte des pièces des derniers messages est ajouté au message de l'utilisateur (borné par `budget` caractères pour toutes les pièces). Les anciennes pièces sont
    seulement nommées. Le contenu enregistré dans la conversation n'est jamais modifié."""
    recents = [n for n, m in enumerate(messages) if m.get("pieces") and n >= len(messages) - RECENT]
    part = max(MIN_PART, budget // max(1, sum(len(messages[n]["pieces"]) for n in recents)))
    sortie = []
    for n, m in enumerate(messages):
        if not m.get("pieces"):
            sortie.append(m)
            continue
        m = dict(m)
        blocs = []
        for p in m.pop("pieces"):
            if n in recents:
                try:
                    texte = read_text(p["id"])
                except (ValueError, text_extraction.ExtractionError, OSError):
                    blocs.append(_t("[Fichier joint « {} » : devenu illisible]").format(p.get("nom", "")))
                    continue
                coupe = len(texte) - part
                if coupe > 0:
                    texte = texte[:part] + _t("\n[… {} caractères coupés : le fichier est plus long que la place disponible]").format(coupe)
                blocs.append(_t("--- Fichier joint : {} ---\n{}\n--- Fin de {} ---").format(p.get("nom", ""), texte, p.get("nom", "")))
            else:
                blocs.append(_t("[Fichier joint « {} » : non rejoué ici]").format(p.get("nom", "")))
        m["content"] = (m.get("content") or "") + "\n\n" + "\n\n".join(blocs)
        sortie.append(m)
    return sortie


def referenced():
    """Identifiants cités par au moins une conversation."""
    from . import store
    vus = set()
    for c in store.every():
        for m in c.get("messages", []):
            vus.update(p.get("id") for p in (m.get("pieces") or []) if isinstance(p, dict))
    return vus


def clean(age_jours=2):
    """Supprime les pièces que plus aucune conversation ne cite, après un délai. Renvoie le nombre de fichiers supprimés."""
    if not folder().is_dir():
        return 0
    gardees, limite, n = referenced(), time.time() - age_jours * 86400, 0
    for f in folder().iterdir():
        base = f.name[:-len(".texte")] if f.name.endswith(".texte") else (f.name[:-len(".tmp")] if f.name.endswith(".tmp") else f.name)
        try:
            if base not in gardees and f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n
